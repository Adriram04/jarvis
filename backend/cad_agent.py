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

DEFAULT_CAD_SCRIPT_TIMEOUT_SECONDS = 45
DEFAULT_CAD_MODEL = "gemini-2.5-flash"
DEFAULT_CAD_FALLBACK_MODELS = "gemini-2.5-flash-lite"
# More reasoning headroom helps the (free) flash model design complex parts
# correctly. Flash supports a dynamic thinking budget; -1 = let the model
# decide, a positive value caps it. Tunable via env without changing models.
DEFAULT_CAD_THINKING_BUDGET = -1
# More self-correction passes = better final geometry without a pricier model.
DEFAULT_CAD_MAX_RETRIES = 4
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
        self.thinking_budget = self._resolve_int_env(
            "JARVIS_CAD_THINKING_BUDGET", DEFAULT_CAD_THINKING_BUDGET
        )
        self.max_retries = max(1, self._resolve_int_env(
            "JARVIS_CAD_MAX_RETRIES", DEFAULT_CAD_MAX_RETRIES
        ))
        
        self.system_instruction = """
You are a senior mechanical/CAD engineer who writes Python scripts with the
`build123d` library to produce models that will be 3D printed on a normal FDM
printer. Your output must be both syntactically correct AND physically
printable and useful in the real world.

## DESIGN PROCESS (think before coding)
Before writing code, plan the part:
1. Decompose the object into simple primitive solids (boxes, cylinders,
   wedges) and features (holes, fillets, ribs). A "phone stand", "bracket" or
   "robot arm" is just a few primitives fused together plus some cuts.
2. Pick realistic real-world dimensions in millimetres for the named object.
   Examples of sensible defaults:
   - Phone stand: base ~80x70mm, back rest leaning ~65deg, a lip ~8mm tall to
     hold the phone, a slot/cutout for the charging cable.
   - Wall/desk bracket: L-shaped, legs ~40-60mm, thickness ~5mm, M3/M4 screw
     holes (3.4mm / 4.5mm) with a reinforcing rib in the corner.
   - Robot arm segment / gripper: linked rectangular links ~60-100mm with pin
     holes at the joints (clearance ~0.4mm around 4-5mm pins).
3. Define all key dimensions as named variables at the TOP of the script so the
   geometry is parametric and easy to fix.
4. Build each feature, then make sure everything fuses into ONE watertight
   solid.

## 3D-PRINTABILITY RULES (very important - the model must actually print)
- The build plate is the XY plane. Orient the part so it has a FLAT face that
  rests on the bed for good adhesion. Prefer giving the part a flat bottom
  rather than balancing it on a point or a curved face.
- Avoid unsupported overhangs steeper than ~45deg from vertical. Add chamfers,
  fillets or support ribs/gussets so steep features can print without supports.
  For a leaning back-rest, add a triangular gusset/leg underneath it.
- Minimum wall thickness >= 1.6mm. Minimum free-standing pin/peg diameter
  >= 3mm. Do not create paper-thin or hair-thin features; they will fail.
- NO floating or disconnected geometry. Every piece must physically connect to
  the rest of the body (overlap solids slightly before fusing, e.g. embed a
  joining face by ~0.5-1mm so the boolean union is robust).
- Screw/bolt holes: use clearance diameters (M3 ~3.4mm, M4 ~4.5mm). Round small
  internal corners with small fillets to reduce stress concentrations.
- If the request implies multiple SEPARATE printed pieces (e.g. an assembly),
  lay them out side by side on the plate (translate them apart in X/Y so they
  do NOT overlap) and fuse them all into the single `result_part` so they
  export together but print as distinct pieces with clearance between them.

## build123d API RULES
1. Start with `from build123d import *`.
2. Add `import numpy as np` ONLY if you actually use numpy.
3. You MUST assign the final object to a variable named `result_part`.
4. Extrude/revolve/loft any sketch or wire into a solid `Part`; never leave the
   result as a 2D sketch.
5. Use lowercase builder methods, NOT PascalCase: `make_face()`, `extrude()`,
   `fillet()`, `chamfer()`, `revolve()`, `loft()`, `sweep()`, `offset()`.
6. To cut holes/pockets, subtract primitives inside the SAME `BuildPart`
   context with `mode=Mode.SUBTRACT`. Do NOT nest a second BuildPart for holes.
7. To add material, build in the same context (default ADD) or fuse parts with
   `+`. Keep joining solids overlapping so the union stays watertight.
8. `fillet()`/`chamfer()` CRASH if the radius is too large for the adjacent
   geometry. Keep radii conservative (0.5-2mm) and only fillet edges you are
   sure about. Wrap risky fillets in try/except and continue if they fail, so a
   cosmetic fillet never aborts the whole model.
9. Do not access `v.X`/`v.Y`/`v.Z` unless `v` is definitely a Vector.

## FINAL OUTPUT
- The script MUST end by exporting the final solid to 'output.stl':
  `export_stl(result_part, 'output.stl')`
- Return the script inside a single ```python ... ``` block.

## EXAMPLES

Rectangular support plate with through holes (single context, no nested
BuildPart):
```python
from build123d import *

plate_l, plate_w, plate_t = 80, 40, 8
hole_r = 3

with BuildPart() as p:
    Box(plate_l, plate_w, plate_t)
    with Locations((-30, -10, 0), (-30, 10, 0), (30, -10, 0), (30, 10, 0)):
        Cylinder(radius=hole_r, height=plate_t * 3, mode=Mode.SUBTRACT)
    try:
        fillet(p.edges().filter_by(Axis.Z), radius=1)
    except Exception:
        pass

result_part = p.part
export_stl(result_part, 'output.stl')
```

Phone stand (flat base + solid angled back that prints support-free + front
lip + cable slot). Note how the inclined support is a SOLID right-triangle
prism built from a 2D profile, so there is nothing floating to support:
```python
from build123d import *
import math

base_w, base_d, base_t = 80, 75, 6     # width(X) x depth(Y) x thickness(Z)
back_h = 70                            # height of the angled back support
back_angle = 65                        # phone leans 65deg from horizontal
lip_h, lip_t = 10, 6                   # front lip that stops the phone sliding

back_run = back_h / math.tan(math.radians(back_angle))  # depth of the incline

with BuildPart() as p:
    # Flat base for good bed adhesion
    Box(base_w, base_d, base_t)

    # Angled back support as a SOLID right-triangle prism (prints support-free).
    # The profile lives in the Y-Z plane and is extruded across the width (X).
    with BuildSketch(Plane.YZ) as profile:
        with BuildLine():
            Polyline(
                (base_d / 2, base_t / 2),               # rear bottom
                (base_d / 2, base_t / 2 + back_h),      # rear top
                (base_d / 2 - back_run, base_t / 2),    # front bottom
                close=True,
            )
        make_face()
    extrude(amount=base_w / 2, both=True)

    # Front lip
    with Locations((0, -base_d / 2 + lip_t / 2, base_t / 2 + lip_h / 2)):
        Box(base_w, lip_t, lip_h)

    # Cable slot through the base
    with Locations((0, 0, 0)):
        Cylinder(radius=6, height=base_t * 3, mode=Mode.SUBTRACT)

    try:
        fillet(p.edges().filter_by(Axis.Z), radius=1.5)
    except Exception:
        pass

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

    def _resolve_int_env(self, env_name, default):
        raw_value = os.getenv(env_name)
        if raw_value is None or raw_value == "":
            return default
        try:
            return int(raw_value)
        except ValueError:
            print(f"[CadAgent DEBUG] [WARN] Invalid {env_name}='{raw_value}'. Using default {default}.")
            return default

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
                        thinking_config=types.ThinkingConfig(
                            include_thoughts=True,
                            thinking_budget=self.thinking_budget,
                        )
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

            max_retries = self.max_retries
            current_prompt = (
                f"Design and write a build123d Python script for a 3D-PRINTABLE model of: {prompt}.\n"
                "First plan the part: decompose it into primitive solids and features, choose realistic "
                "real-world dimensions in millimetres, and define them as named variables at the top. "
                "Make sure the result is a single watertight solid with a flat base for the print bed, no "
                "unsupported steep overhangs, and walls/pins thick enough to print. "
                "Export to 'output.stl'."
            )
            
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

            max_retries = self.max_retries
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

