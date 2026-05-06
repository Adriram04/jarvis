import os
import json
import asyncio
import ast
import subprocess
import sys
import re
import math
from datetime import datetime
from google import genai
from google.genai import errors, types
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from typing import List, Optional

load_dotenv()

DEFAULT_CAD_SCRIPT_TIMEOUT_SECONDS = 30
DEFAULT_CAD_MODEL = "gemini-2.5-flash"
DEFAULT_CAD_FALLBACK_MODELS = "gemini-2.5-flash-lite"
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
        # Use broadly available models for CAD script generation, with fallback
        # when the primary model is temporarily saturated.
        self.models = self._resolve_model_list()
        self.model = self.models[0]
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

        For rectangular plates/supports with through holes, subtract cylinders
        directly inside the same BuildPart context. Do NOT create a nested
        BuildPart for holes:
        ```python
        from build123d import *

        with BuildPart() as p:
            Box(80, 40, 8)
            with Locations((-30, -10, 0), (-30, 10, 0), (30, -10, 0), (30, 10, 0)):
                Cylinder(radius=3, height=20, mode=Mode.SUBTRACT)

        result_part = p.part
        export_stl(result_part, 'output.stl')
        ```

        Example Script:
        ```python
        from build123d import *

        with BuildPart() as p:
            Box(10, 10, 10)
            fillet(p.edges(), radius=1)

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

    def _resolve_model_list(self):
        primary_model = os.getenv("JARVIS_CAD_MODEL", DEFAULT_CAD_MODEL).strip()
        fallback_models = os.getenv("JARVIS_CAD_FALLBACK_MODELS", DEFAULT_CAD_FALLBACK_MODELS)

        models = [primary_model]
        models.extend(model.strip() for model in fallback_models.split(","))

        unique_models = []
        for model in models:
            if model and model not in unique_models:
                unique_models.append(model)

        return unique_models or [DEFAULT_CAD_MODEL]

    def _is_retryable_model_error(self, exc):
        if isinstance(exc, errors.ServerError):
            return True
        if isinstance(exc, errors.ClientError):
            message = str(exc)
            return "429" in message or "RESOURCE_EXHAUSTED" in message or "Too Many Requests" in message
        return False

    async def _generate_cad_code_response(self, prompt):
        last_error = None

        for index, model in enumerate(self.models):
            raw_content = ""
            try:
                print(f"[CadAgent DEBUG] [MODEL] Requesting CAD code with {model}")
                stream = await self.client.aio.models.generate_content_stream(
                    model=model,
                    contents=prompt,
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
                                if self.on_thought:
                                    self.on_thought(part.text)
                            else:
                                raw_content += part.text

                return raw_content, model

            except (errors.ClientError, errors.ServerError) as exc:
                last_error = exc
                if not self._is_retryable_model_error(exc) or index >= len(self.models) - 1:
                    raise

                next_model = self.models[index + 1]
                message = f"Model {model} unavailable or rate limited. Trying {next_model}."
                print(f"[CadAgent DEBUG] [MODEL] {message}")
                if self.on_status:
                    self.on_status({
                        "status": "retrying",
                        "attempt": None,
                        "max_attempts": None,
                        "error": message,
                        "model": next_model
                    })

        if last_error:
            raise last_error

        return "", self.model

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

        output_filename = os.path.basename(output_stl)
        code_with_path = code.replace("output.stl", output_filename)

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code_with_path)

        print(f"[CadAgent DEBUG] [EXEC] Running local script: {script_path}")
        return await self._run_generated_script(script_path)

    def _extract_hole_count(self, prompt):
        normalized = prompt.lower()
        digit_match = re.search(r"\b(\d{1,2})\s*(?:agujeros?|holes?)\b", normalized)
        if digit_match:
            return max(1, min(12, int(digit_match.group(1))))

        word_numbers = {
            "uno": 1,
            "un": 1,
            "one": 1,
            "dos": 2,
            "two": 2,
            "tres": 3,
            "three": 3,
            "cuatro": 4,
            "four": 4,
            "cinco": 5,
            "five": 5,
            "seis": 6,
            "six": 6,
        }

        for word, value in word_numbers.items():
            if re.search(rf"\b{word}\b", normalized):
                return value

        return 4

    def _is_rectangular_support_prompt(self, prompt):
        normalized = prompt.lower()
        has_base = any(term in normalized for term in (
            "soporte",
            "support",
            "placa",
            "plate",
            "base",
            "bracket",
        ))
        has_rectangular = "rectangular" in normalized or "rectangle" in normalized
        has_holes = any(term in normalized for term in ("agujero", "agujeros", "hole", "holes"))
        return has_base and has_rectangular and has_holes

    def _rectangular_support_fallback_code(self, prompt, output_stl):
        hole_count = self._extract_hole_count(prompt)
        output_filename = os.path.basename(output_stl)

        if hole_count == 1:
            positions = [(0, 0, 0)]
        elif hole_count == 2:
            positions = [(-25, 0, 0), (25, 0, 0)]
        elif hole_count == 3:
            positions = [(-25, -10, 0), (25, -10, 0), (0, 10, 0)]
        else:
            positions = [(-30, -10, 0), (-30, 10, 0), (30, -10, 0), (30, 10, 0)]

        if hole_count > 4:
            positions = []
            radius = 26
            for index in range(hole_count):
                angle = 2 * 3.141592653589793 * index / hole_count
                positions.append((round(radius * math.cos(angle), 3), round(radius * math.sin(angle), 3), 0))

        return f"""from build123d import *
import math

support_length = 80
support_width = 40
support_height = 8
hole_radius = 3
hole_positions = {positions!r}

with BuildPart() as p:
    Box(support_length, support_width, support_height)
    with Locations(*hole_positions):
        Cylinder(radius=hole_radius, height=support_height * 3, mode=Mode.SUBTRACT)

    try:
        fillet(p.edges(), radius=0.8)
    except Exception:
        pass

result_part = p.part
export_stl(result_part, {output_filename!r})
"""

    async def _try_parametric_fallback(self, prompt, script_path, output_stl):
        if not self._is_rectangular_support_prompt(prompt):
            return None

        print("[CadAgent DEBUG] [FALLBACK] Trying deterministic rectangular support generator.")
        code = self._rectangular_support_fallback_code(prompt, output_stl)
        proc = await self._write_and_run_generated_script(script_path, code, output_stl)
        if proc.returncode != 0 or not os.path.exists(output_stl):
            print(f"[CadAgent DEBUG] [FALLBACK] Failed:\n{proc.stderr}")
            return None

        with open(output_stl, "rb") as f:
            stl_data = f.read()

        import base64
        return {
            "format": "stl",
            "data": base64.b64encode(stl_data).decode("utf-8"),
            "file_path": output_stl
        }

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
                
                # 1. Ask Gemini for the code with streaming and thinking.
                try:
                    raw_content, used_model = await self._generate_cad_code_response(current_prompt)
                    print(f"[CadAgent DEBUG] [MODEL] CAD response generated with {used_model}")
                except (errors.ClientError, errors.ServerError) as exc:
                    print(f"[CadAgent DEBUG] [MODEL] CAD model request failed: {exc}")
                    fallback = await self._try_parametric_fallback(prompt, script_path, output_stl)
                    if fallback:
                        return fallback
                    if self.on_status:
                        self.on_status({
                            "status": "retrying",
                            "attempt": attempt + 1,
                            "max_attempts": max_retries,
                            "error": str(exc)[:200]
                        })
                    continue
                
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
            fallback = await self._try_parametric_fallback(prompt, script_path, output_stl)
            if fallback:
                return fallback

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
            with open(script_path, "r", encoding="utf-8", errors="replace") as f:
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
                
                # 1. Ask Gemini for the code with streaming and thinking.
                raw_content, used_model = await self._generate_cad_code_response(current_prompt)
                print(f"[CadAgent DEBUG] [MODEL] CAD response generated with {used_model}")
                
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

