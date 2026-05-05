import os
import json
import asyncio
import ast
import subprocess
import sys
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from typing import List, Optional

load_dotenv()

DEFAULT_CAD_SCRIPT_TIMEOUT_SECONDS = 30
BLOCKED_GENERATED_CODE_IMPORTS = {
    "ctypes",
    "importlib",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
}
BLOCKED_GENERATED_CODE_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "input",
    "open",
}

class CadAgent:
    def __init__(self, on_thought=None, on_status=None):
        self.client = genai.Client(http_options={"api_version": "v1beta"}, api_key=os.getenv("GEMINI_API_KEY"))
        # Using Gemini 2.5 Pro for thinking/streaming support
        self.model = "gemini-3-pro-preview"
        self.on_thought = on_thought  # Callback for streaming thoughts 
        self.on_status = on_status  # Callback for retry status info
        self.script_timeout_seconds = self._resolve_script_timeout_seconds()
        
        self.system_instruction = """
You are a Python-based 3D CAD Engineer using the `build123d` library.
Your goal is to write a Python script that generates a 3D model based on the user's request.

Requirements:
1. Start with `from build123d import *`.
2. Include `import numpy as np` if you use any numpy functions (like `np.sign`, `np.pi`).
3. You MUST assign the final object to a variable named `result_part`.
4. If you create a sketch or line, extrude it to make it a solid `Part`.
5. The model should be centered at (0,0,0) and have reasonable dimensions (mm).
6. **IMPORTANT**: Do NOT use old or PascalCase function names for core operations.
   - Use `make_face()` instead of `MakeFace()`.
   - Use `extrude()` instead of `Extrude()`.
   - Use `fillet()` instead of `Fillet()`.
   - Use `chamfer()` instead of `Chamfer()`.
   - Use `revolve()` instead of `Revolve()`.
   - Use `loft()` instead of `Loft()`.
   - Use `sweep()` instead of `Sweep()`.
   - Use `offset()` instead of `Offset()`.
   - generally prefer lowercase builder methods inside contexts.

7. **Vector Access**: Do NOT access vector components like `v.X`, `v.Y`, `v.Z` unless you are sure they exist (use `v.X` etc on Vector objects, but ensure they are Vectors).
8. **Final Output**: The script MUST end by exporting the final part to an STL file named 'output.stl'.
   - `export_stl(result_part, 'output.stl')`

9. **Robustness**: Operations like `fillet()` and `chamfer()` will crash if the radius is too large for the geometry.
   - Use conservative values (e.g., 0.5mm to 2mm) unless you are certain of the dimensions.
   - If a fillet is purely aesthetic, keep it small to ensure success.

Example Script:
```python
from build123d import *

with BuildPart() as p:
    Box(10, 10, 10)
    Fillet(p.edges(), radius=1)

result_part = p.part
export_stl(result_part, 'output.stl')
```
"""

    def _resolve_script_timeout_seconds(self):
        raw_value = os.getenv("JARVIS_CAD_SCRIPT_TIMEOUT_SECONDS")
        if not raw_value:
            return DEFAULT_CAD_SCRIPT_TIMEOUT_SECONDS

        try:
            timeout = int(raw_value)
        except ValueError:
            print(f"[CadAgent DEBUG] [WARN] Invalid JARVIS_CAD_SCRIPT_TIMEOUT_SECONDS='{raw_value}'. Using default.")
            return DEFAULT_CAD_SCRIPT_TIMEOUT_SECONDS

        return max(1, timeout)

    def _validate_generated_code(self, code):
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return False, f"Generated script has a syntax error: {exc}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".")[0]
                    if root_name in BLOCKED_GENERATED_CODE_IMPORTS:
                        return False, f"Generated script imports blocked module '{root_name}'."

            elif isinstance(node, ast.ImportFrom):
                root_name = (node.module or "").split(".")[0]
                if root_name in BLOCKED_GENERATED_CODE_IMPORTS:
                    return False, f"Generated script imports blocked module '{root_name}'."

            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_GENERATED_CODE_CALLS:
                    return False, f"Generated script calls blocked function '{node.func.id}'."

        return True, ""

    def _normalize_subprocess_output(self, value):
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return str(value)

    async def _run_generated_script(self, script_path):
        work_dir = os.path.dirname(os.path.abspath(script_path))

        try:
            return await asyncio.to_thread(
                subprocess.run,
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                cwd=work_dir,
                timeout=self.script_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = self._normalize_subprocess_output(exc.stdout)
            stderr = self._normalize_subprocess_output(exc.stderr)
            timeout_msg = (
                f"CAD script timed out after {self.script_timeout_seconds} seconds. "
                "The generated code may contain an infinite loop or overly heavy geometry."
            )
            combined_stderr = "\n".join(part for part in (stderr, timeout_msg) if part)
            print(f"[CadAgent DEBUG] [TIMEOUT] {timeout_msg}")
            return subprocess.CompletedProcess(exc.cmd, 124, stdout, combined_stderr)
        except Exception as exc:
            print(f"[CadAgent DEBUG] [ERR] Subprocess run failed: {exc}")
            return subprocess.CompletedProcess([sys.executable, script_path], 1, "", str(exc))

    async def _write_and_run_generated_script(self, script_path, code, output_stl):
        is_safe, safety_error = self._validate_generated_code(code)
        if not is_safe:
            print(f"[CadAgent DEBUG] [BLOCKED] {safety_error}")
            return subprocess.CompletedProcess([sys.executable, script_path], 1, "", safety_error)

        safe_output_path = output_stl.replace("\\", "\\\\")
        code_with_path = code.replace("output.stl", safe_output_path)

        with open(script_path, "w") as f:
            f.write(code_with_path)

        print(f"[CadAgent DEBUG] [EXEC] Running local script: {script_path}")
        return await self._run_generated_script(script_path)

    async def generate_prototype(self, prompt: str, output_dir: Optional[str] = None):
        """
        Generates 3D geometry by asking Gemini for a script, then running it LOCALLY.
        Args:
            prompt: User's description of the model to generate.
            output_dir: Directory to save the script and STL. If None, uses temp dir.
        """
        print(f"[CadAgent DEBUG] [START] Generation started for: '{prompt}'")
        
        try:
            # Use provided output_dir or fall back to temp
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                work_dir = output_dir
            else:
                import tempfile
                work_dir = tempfile.gettempdir()
            
            # Generate timestamped filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_stl = os.path.join(work_dir, f"output_{timestamp}.stl")
            script_path = os.path.join(work_dir, "current_design.py")

            max_retries = 3
            current_prompt = f"You are a build123d expert. Write a generic python script to create a 3D model of: {prompt}. Ensure you export to 'output.stl'. Unscaled."
            
            for attempt in range(max_retries):
                print(f"[CadAgent DEBUG] Attempt {attempt + 1}/{max_retries}")
                
                # Emit status update
                if self.on_status:
                    status_info = {
                        "status": "generating" if attempt == 0 else "retrying",
                        "attempt": attempt + 1,
                        "max_attempts": max_retries,
                        "error": None
                    }
                    self.on_status(status_info)
                
                # 1. Ask Gemini for the code with streaming and thinking
                raw_content = ""
                stream = await self.client.aio.models.generate_content_stream(
                    model=self.model,
                    contents=current_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_instruction,
                        temperature=1.0,
                        thinking_config=types.ThinkingConfig(include_thoughts=True)
                    )
                )
                async for chunk in stream:
                    if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                        for part in chunk.candidates[0].content.parts:
                            if not part.text:
                                continue
                            elif part.thought:
                                # Stream thought to callback
                                if self.on_thought:
                                    self.on_thought(part.text)
                            else:
                                # Accumulate answer text
                                raw_content += part.text
                
                if not raw_content:
                    print("[CadAgent DEBUG] [ERR] Empty response from model.")
                    return None

                # 2. Extract Code Block
                import re
                code_match = re.search(r'```python(.*?)```', raw_content, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                else:
                    # Fallback: assume entire text is code if no blocks, or fail
                    print("[CadAgent DEBUG] [WARN] No ```python block found. Trying heuristic...")
                    if "import build123d" in raw_content:
                        code = raw_content
                    else:
                        print("[CadAgent DEBUG] [ERR] Could not extract python code.")
                        return None
                
                # 3. Save and execute locally with lightweight safety checks and timeout.
                proc = await self._write_and_run_generated_script(script_path, code, output_stl)
                stdout, stderr = proc.stdout, proc.stderr
                
                if proc.returncode != 0:
                    error_msg = stderr
                    # Extract a concise error message for display
                    error_lines = error_msg.strip().split('\n')
                    short_error = error_lines[-1][:100] if error_lines else "Unknown error"
                    print(f"[CadAgent DEBUG] [ERR] Script Execution Failed:\n{error_msg}")
                    
                    # Emit retry status with error
                    if self.on_status:
                        self.on_status({
                            "status": "retrying",
                            "attempt": attempt + 1,
                            "max_attempts": max_retries,
                            "error": short_error
                        })
                    
                    # Preparing feedback for next attempt
                    current_prompt = f"""
The Python script you generated failed to execute with the following error:
{error_msg}

Please fix the code to resolve this error. Return the full corrected script. 
Ensure you still export to 'output.stl'.
Original request: {prompt}
"""
                    continue # Retry loop
                
                print(f"[CadAgent DEBUG] [OK] Script executed successfully.")
                
                # 5. Read Output
                if os.path.exists(output_stl):
                    print(f"[CadAgent DEBUG] [file] '{output_stl}' found.")
                    with open(output_stl, "rb") as f:
                        stl_data = f.read()
                        
                    import base64
                    b64_stl = base64.b64encode(stl_data).decode('utf-8')
                    
                    return {
                        "format": "stl",
                        "data": b64_stl,
                        "file_path": output_stl
                    }
                else:
                     print(f"[CadAgent DEBUG] [ERR] '{output_stl}' was not generated.")
                     # If script ran but no output, treat as failure and retry?
                     # Ideally yes.
                     current_prompt = f"The script executed successfully but 'output.stl' was not found. Ensure you call `export_stl(result_part, 'output.stl')` at the end."
                     continue

            # If loop finishes without success
            print("[CadAgent DEBUG] [ERR] All attempts failed.")
            if self.on_status:
                self.on_status({
                    "status": "failed",
                    "attempt": max_retries,
                    "max_attempts": max_retries,
                    "error": "All generation attempts failed"
                })
            return None

        except Exception as e:
            print(f"CadAgent Error: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def iterate_prototype(self, prompt: str, output_dir: Optional[str] = None):
        """
        Iterates on the existing design by reading 'current_design.py' and applying changes.
        Args:
            prompt: User's description of the changes to make.
            output_dir: Directory containing existing script and where to save new STL.
        """
        print(f"[CadAgent DEBUG] [START] Iteration started for: '{prompt}'")
        
        # Use provided output_dir or fall back to temp
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            work_dir = output_dir
        else:
            import tempfile
            work_dir = tempfile.gettempdir()
        
        # Generate timestamped filename for the output
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        script_path = os.path.join(work_dir, "current_design.py")
        output_stl = os.path.join(work_dir, f"output_{timestamp}.stl")
        
        existing_code = ""
        
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                existing_code = f.read()
            
            # Sanitize existing code: replace any absolute paths with 'output.stl'
            # This prevents the LLM from seeing/reproducing Windows paths that cause Unicode escape errors
            import re
            # Match both escaped (\\) and unescaped (\) Windows paths to output.stl
            existing_code = re.sub(
                r"['\"]C:\\\\?Users\\\\?[^'\"]+\\\\?output[^'\"]*\.stl['\"]",
                "'output.stl'",
                existing_code
            )
            # Also handle forward-slash variants
            existing_code = re.sub(
                r"['\"]C:/Users/[^'\"]+/output[^'\"]*\.stl['\"]",
                "'output.stl'",
                existing_code
            )
        else:
             print("[CadAgent DEBUG] [WARN] No existing script found. Falling back to fresh generation.")
             return await self.generate_prototype(prompt)

        try:

            max_retries = 3
            current_prompt = f"""
You are iterating on an existing 3D model script.

Current Python Code:
```python
{existing_code}
```

User Request: {prompt}

Task: Rewrite the code to satisfy the user's request while maintaining the rest of the model structure.
Ensure you still export to 'output.stl'.
"""
            
            for attempt in range(max_retries):
                print(f"[CadAgent DEBUG] Iteration Attempt {attempt + 1}/{max_retries}")
                
                # Emit status update
                if self.on_status:
                    status_info = {
                        "status": "generating" if attempt == 0 else "retrying",
                        "attempt": attempt + 1,
                        "max_attempts": max_retries,
                        "error": None
                    }
                    self.on_status(status_info)
                
                # 1. Ask Gemini for the code with streaming and thinking
                raw_content = ""
                stream = await self.client.aio.models.generate_content_stream(
                    model=self.model,
                    contents=current_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_instruction,
                        temperature=1.0,
                        thinking_config=types.ThinkingConfig(include_thoughts=True)
                    )
                )
                async for chunk in stream:
                    if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                        for part in chunk.candidates[0].content.parts:
                            if not part.text:
                                continue
                            elif part.thought:
                                # Stream thought to callback
                                if self.on_thought:
                                    self.on_thought(part.text)
                            else:
                                # Accumulate answer text
                                raw_content += part.text
                
                if not raw_content:
                    print("[CadAgent DEBUG] [ERR] Empty response from model.")
                    return None

                # 2. Extract Code Block
                import re
                code_match = re.search(r'```python(.*?)```', raw_content, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                else:
                    # Fallback: assume entire text is code if no blocks, or fail
                    print("[CadAgent DEBUG] [WARN] No ```python block found. Trying heuristic...")
                    if "import build123d" in raw_content:
                        code = raw_content
                    else:
                        print("[CadAgent DEBUG] [ERR] Could not extract python code.")
                        return None
                
                # 3. Overwrite, then execute locally with lightweight safety checks and timeout.
                proc = await self._write_and_run_generated_script(script_path, code, output_stl)
                stdout, stderr = proc.stdout, proc.stderr
                
                if proc.returncode != 0:
                    error_msg = stderr
                    print(f"[CadAgent DEBUG] [ERR] Script Execution Failed:\n{error_msg}")
                    
                    # Preparing feedback for next attempt
                    current_prompt = f"""
The updated Python script you generated failed to execute with the following error:
{error_msg}

Please fix the code to resolve this error. Return the full corrected script. 
Ensure you still export to 'output.stl'.
"""
                    continue # Retry loop
                
                print(f"[CadAgent DEBUG] [OK] Script executed successfully.")
                
                # 5. Read Output
                if os.path.exists(output_stl):
                    print(f"[CadAgent DEBUG] [file] '{output_stl}' found.")
                    with open(output_stl, "rb") as f:
                        stl_data = f.read()
                        
                    import base64
                    b64_stl = base64.b64encode(stl_data).decode('utf-8')
                    
                    return {
                        "format": "stl",
                        "data": b64_stl,
                        "file_path": output_stl
                    }
                else:
                     print(f"[CadAgent DEBUG] [ERR] '{output_stl}' was not generated.")
                     current_prompt = f"The script executed successfully but '{output_stl}' was not found. Ensure you call `export_stl(result_part, 'output.stl')` at the end."
                     continue

            # If loop finishes without success
            print("[CadAgent DEBUG] [ERR] All attempts failed.")
            if self.on_status:
                self.on_status({
                    "status": "failed",
                    "attempt": max_retries,
                    "max_attempts": max_retries,
                    "error": "All iteration attempts failed"
                })
            return None

        except Exception as e:
            print(f"CadAgent Error: {e}")
            import traceback
            traceback.print_exc()
            return None

