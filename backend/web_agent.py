import os
import time
import asyncio
import base64
import re
import unicodedata
from datetime import date
from urllib.parse import quote_plus
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from google import genai
from google.genai import types

# 1. Load API Key
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("Please set GEMINI_API_KEY in your .env file")

# 2. Configuration
SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900
# UPDATED: Use the specific Computer Use preview model
MODEL_ID = os.getenv("JARVIS_WEB_AGENT_MODEL", "gemini-3-flash-preview")
DEFAULT_SEARCH_ENGINE = os.getenv("JARVIS_WEB_AGENT_SEARCH_ENGINE", "bing").strip().lower() or "bing"


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)) or default)
    except Exception:
        return int(default)


AI_MAX_TURNS = max(1, _env_int("JARVIS_WEB_AGENT_AI_MAX_TURNS", 4))
AI_DAILY_LIMIT = max(0, _env_int("JARVIS_WEB_AGENT_AI_DAILY_LIMIT", 20))
AI_COOLDOWN_SECONDS = max(0, _env_int("JARVIS_WEB_AGENT_AI_COOLDOWN_SECONDS", 1800))


class WebAgentQuotaError(RuntimeError):
    """Raised when the Gemini Computer Use model is unavailable due to quota."""


def _friendly_api_error(error):
    message = str(error)
    if "RESOURCE_EXHAUSTED" in message or "Quota exceeded" in message or "429" in message:
        return (
            "Web Agent unavailable: Gemini Computer Use quota is exhausted or not enabled "
            f"for this API project/model ({MODEL_ID}). Check your Gemini billing/quota, "
            "or try again later if this is a temporary rate limit."
        )
    if "UNAVAILABLE" in message or "high demand" in message or "503" in message:
        return (
            "Web Agent unavailable: Gemini Computer Use is experiencing high demand "
            f"for this model ({MODEL_ID}). Simple navigation/search commands can still run "
            "without the AI model; try a simpler command or wait before using complex visual automation."
        )
    return f"Web Agent API error: {message}"


def _is_ai_capacity_error(error):
    message = str(error)
    return any(token in message for token in ("RESOURCE_EXHAUSTED", "Quota exceeded", "429", "UNAVAILABLE", "high demand", "503"))


def _normalize_text(text):
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents.lower()).strip()


def _strip_url_punctuation(value):
    return str(value or "").strip().strip(".,;:!?¡¿()[]{}<>\"'")

class WebAgent:
    def __init__(self):
        self.client = genai.Client(api_key=API_KEY)
        self.browser = None
        self.context = None
        self.page = None
        self.ai_usage_date = date.today().isoformat()
        self.ai_calls_today = 0
        self.ai_cooldown_until = 0.0

    def denormalize_x(self, x: int, width: int) -> int:
        return int((x / 1000) * width)

    def denormalize_y(self, y: int, height: int) -> int:
        return int((y / 1000) * height)

    def _refresh_ai_budget_day(self):
        today = date.today().isoformat()
        if self.ai_usage_date != today:
            self.ai_usage_date = today
            self.ai_calls_today = 0

    def _ai_budget_error(self):
        self._refresh_ai_budget_day()
        now = time.time()
        if now < self.ai_cooldown_until:
            remaining = max(1, int(self.ai_cooldown_until - now))
            return (
                "Web Agent IA en pausa temporal para no seguir consumiendo cuota "
                f"tras un error de capacidad. Reintenta en {remaining} segundos o usa una busqueda simple."
            )
        if AI_DAILY_LIMIT and self.ai_calls_today >= AI_DAILY_LIMIT:
            return (
                "Web Agent IA no usada: limite local diario alcanzado "
                f"({self.ai_calls_today}/{AI_DAILY_LIMIT}). Las busquedas simples siguen funcionando sin IA."
            )
        return None

    def _record_ai_call(self):
        self._refresh_ai_budget_day()
        self.ai_calls_today += 1

    def _record_ai_capacity_error(self):
        if AI_COOLDOWN_SECONDS:
            self.ai_cooldown_until = max(self.ai_cooldown_until, time.time() + AI_COOLDOWN_SECONDS)

    def _extract_url(self, prompt):
        match = re.search(
            r"(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+(?::\d+)?(?:/[^\s]*)?)",
            str(prompt or ""),
        )
        if not match:
            return None
        url = _strip_url_punctuation(match.group(1))
        if not re.match(r"^https?://", url, re.IGNORECASE):
            url = f"https://{url}"
        return url

    def _extract_search_query(self, prompt):
        text = str(prompt or "").strip()
        normalized = _normalize_text(text)
        patterns = [
            r"(?:abre\s+el\s+agente\s+web\s+y\s+busca|busca\s+en\s+google|buscar\s+en\s+google|buscame|busqueme|busca|buscar|encuentrame|encuentra|mirame|mira|search\s+for|search|find|investiga|consulta)\s+(.+)",
            r"(?:googlea|google)\s+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if not match:
                continue
            query = match.group(1).strip()
            query = re.sub(r"^(?:sobre|por|acerca de|informacion sobre)\s+", "", query).strip()
            query = query.strip(" .,!?:;\"'")
            return query or None
        return None

    def _search_url_for_query(self, query, prompt):
        normalized = _normalize_text(f"{prompt} {query}")
        query = str(query or "").strip()

        if "amazon" in normalized:
            cleaned = re.sub(r"\b(?:en\s+)?amazon(?:\.(?:es|com))?\b", " ", query, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s+", " ", cleaned).strip() or query
            return f"https://www.amazon.es/s?k={quote_plus(cleaned)}"

        engine = "google" if "google" in normalized else DEFAULT_SEARCH_ENGINE
        if engine == "google":
            return f"https://www.google.com/search?q={quote_plus(query)}"
        if engine in {"duckduckgo", "ddg"}:
            return f"https://duckduckgo.com/?q={quote_plus(query)}"
        return f"https://www.bing.com/search?q={quote_plus(query)}"

    def _deterministic_plan(self, prompt):
        text = str(prompt or "").strip()
        if not text:
            return None

        normalized = _normalize_text(text)
        query = self._extract_search_query(text)
        if query:
            search_url = self._search_url_for_query(query, text)
            return {
                "kind": "search",
                "url": search_url,
                "log": f"Busqueda sin IA: {query}",
                "summary": f"Busqueda abierta sin usar IA: {query}",
            }

        url = self._extract_url(text)
        if url and (
            re.search(r"\b(abre|abrir|open|navega|navegar|ve|entra|ir|go)\b", normalized)
            or normalized == _normalize_text(url)
            or normalized.startswith(("http://", "https://", "www."))
        ):
            return {
                "kind": "navigate",
                "url": url,
                "log": f"Navegacion sin IA: {url}",
                "summary": f"Pagina abierta sin usar IA: {url}",
            }

        if normalized in {"abre el navegador", "abrir navegador", "open browser", "open web browser"}:
            return {
                "kind": "navigate",
                "url": "https://www.google.com",
                "log": "Navegador abierto sin IA",
                "summary": "Navegador abierto sin usar IA.",
            }

        return None

    async def _emit_page_update(self, update_callback, log_text):
        if not update_callback:
            return
        screenshot = await self.page.screenshot(type="png")
        encoded_image = base64.b64encode(screenshot).decode("utf-8")
        await update_callback(encoded_image, log_text)

    async def _run_deterministic_task(self, prompt, update_callback=None):
        plan = self._deterministic_plan(prompt)
        if not plan:
            return None

        print(f"[FAST] {plan['log']}")
        if update_callback:
            await update_callback(None, f"Modo rapido sin IA: {plan['log']}")

        await self.page.goto(plan["url"], wait_until="domcontentloaded")
        try:
            await self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        await self._emit_page_update(update_callback, f"Executed without AI: {plan['kind']}")
        page_title = ""
        try:
            page_title = await self.page.title()
        except Exception:
            pass
        suffix = f" Pagina: {page_title}." if page_title else ""
        return f"{plan['summary']}.{suffix} URL: {self.page.url}"

    async def execute_function_calls(self, function_calls):
        results = []
        
        for call in function_calls:
            # Extract ID if available, otherwise it might be None or empty depending on the SDK version
            # But the Computer Use model typically expects IDs to be threaded back.
            call_id = getattr(call, 'id', None)
            fn_name = call.name
            args = call.args
            print(f"[ACTION] Action: {fn_name} {args}")

            # --- SAFETY CHECK ---
            requires_acknowledgement = False
            if "safety_decision" in args:
                 decision = args["safety_decision"]
                 if decision.get("decision") == "require_confirmation":
                     print(f"   [SAFETY] Safety Alert: {decision.get('explanation')}")
                     print("   -> Auto-acknowledging to proceed.")
                     requires_acknowledgement = True

            result_data = {}
            
            try:
                # --- NAVIGATION ---
                if fn_name == "open_web_browser":
                    pass 
                elif fn_name == "navigate":
                    await self.page.goto(args["url"])
                elif fn_name == "go_back":
                    await self.page.go_back()
                elif fn_name == "go_forward":
                    await self.page.go_forward()
                elif fn_name == "search":
                    await self.page.goto("https://www.google.com")
                elif fn_name == "wait_5_seconds":
                    await asyncio.sleep(5)

                # --- MOUSE CLICKS & TYPING ---
                elif fn_name == "click_at":
                    x = self.denormalize_x(args["x"], SCREEN_WIDTH)
                    y = self.denormalize_y(args["y"], SCREEN_HEIGHT)
                    await self.page.mouse.click(x, y)
                    
                elif fn_name == "type_text_at":
                    x = self.denormalize_x(args["x"], SCREEN_WIDTH)
                    y = self.denormalize_y(args["y"], SCREEN_HEIGHT)
                    text = args["text"]
                    press_enter = args.get("press_enter", False)
                    clear_before = args.get("clear_before_typing", True)
                    
                    await self.page.mouse.click(x, y)
                    if clear_before:
                        # 'Meta+A' for Mac, 'Control+A' for Windows/Linux
                        # Simply using Control+A is usually fine for headless linux/windows envs
                        await self.page.keyboard.press("Control+A") 
                        await self.page.keyboard.press("Backspace")
                    
                    await self.page.keyboard.type(text)
                    if press_enter:
                        await self.page.keyboard.press("Enter")

                # --- MOUSE MOVEMENT / HOVER ---
                elif fn_name == "hover_at":
                    x = self.denormalize_x(args["x"], SCREEN_WIDTH)
                    y = self.denormalize_y(args["y"], SCREEN_HEIGHT)
                    await self.page.mouse.move(x, y)

                elif fn_name == "drag_and_drop":
                    start_x = self.denormalize_x(args["x"], SCREEN_WIDTH)
                    start_y = self.denormalize_y(args["y"], SCREEN_HEIGHT)
                    end_x = self.denormalize_x(args["destination_x"], SCREEN_WIDTH)
                    end_y = self.denormalize_y(args["destination_y"], SCREEN_HEIGHT)
                    
                    await self.page.mouse.move(start_x, start_y)
                    await self.page.mouse.down()
                    await self.page.mouse.move(end_x, end_y)
                    await self.page.mouse.up()

                # --- KEYBOARD ---
                elif fn_name == "key_combination":
                    key_comb = args.get("keys")
                    await self.page.keyboard.press(key_comb)

                # --- SCROLLING ---
                elif fn_name == "scroll_document" or fn_name == "scroll_at":
                    magnitude = args.get("magnitude", 800)
                    direction = args.get("direction", "down")
                    
                    # If scroll_at, move mouse there first
                    if fn_name == "scroll_at":
                        x = self.denormalize_x(args["x"], SCREEN_WIDTH)
                        y = self.denormalize_y(args["y"], SCREEN_HEIGHT)
                        await self.page.mouse.move(x, y)

                    dx, dy = 0, 0
                    if direction == "down": dy = magnitude
                    elif direction == "up": dy = -magnitude
                    elif direction == "right": dx = magnitude
                    elif direction == "left": dx = -magnitude
                    
                    await self.page.mouse.wheel(dx, dy)

                else:
                    print(f"[WARN] Warning: Model requested unimplemented function {fn_name}")

                # Wait a moment for UI to settle
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"[ERR] Error executing {fn_name}: {e}")
                result_data = {"error": str(e)}

            # Add the acknowledgement flag if needed
            if requires_acknowledgement:
                result_data["safety_acknowledgement"] = True

            results.append((call_id, fn_name, result_data))
        
        return results

    async def get_function_responses(self, results):
        # UPDATED: Changed "jpeg" to "png" to satisfy Computer Use model requirements
        screenshot_bytes = await self.page.screenshot(type="png") 
        current_url = self.page.url
        
        function_responses = []
        for call_id, name, result in results:
            response_data = {"url": current_url}
            response_data.update(result)
            
            # Construct the response object
            # Note: The SDK might change how 'id' is passed. 
            # If 'types.FunctionResponse' supports 'id', we pass it.
            # Based on standard Google GenAI SDK usage for function calling:
            function_responses.append(
                types.FunctionResponse(
                    name=name,
                    id=call_id, # critical for matching request-response
                    response=response_data,
                    parts=[types.FunctionResponsePart(
                        inline_data=types.FunctionResponseBlob(
                            # UPDATED: Changed "image/jpeg" to "image/png"
                            mime_type="image/png",
                            data=screenshot_bytes
                        )
                    )]
                )
            )
        return function_responses, screenshot_bytes

    async def run_task(self, prompt, update_callback=None):
        """
        Runs the agent with the given prompt.
        update_callback: async function(screenshot_b64: str, logs: str)
        Returns the final response from the agent.
        """
        print(f"[START] WebAgent started. Goal: {prompt}")
        final_response = "Agent finished without a final summary."

        async with async_playwright() as p:
            # Launch browser (Headless=True usually, but for dev we might keep it hidden)
            # Use headless=True for server deployment
            self.browser = await p.chromium.launch(headless=True) 
            self.context = await self.browser.new_context(
                viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            self.page = await self.context.new_page()
            
            # Start at Google
            await self.page.goto("https://www.google.com")

            # UPDATED: Capture initial screenshot as PNG
            initial_screenshot = await self.page.screenshot(type="png")
            
            # Send initial state
            if update_callback:
                encoded_image = base64.b64encode(initial_screenshot).decode('utf-8')
                await update_callback(encoded_image, "Web Agent Initialized")

            deterministic_result = await self._run_deterministic_task(prompt, update_callback)
            if deterministic_result:
                if self.browser:
                    await self.browser.close()
                    self.browser = None
                print("[CLOSE] Browser closed.")
                return deterministic_result

            config = types.GenerateContentConfig(
                tools=[types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER
                    )
                )],
                thinking_config=types.ThinkingConfig(include_thoughts=True)
            )

            chat_history = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part(text=prompt),
                        # UPDATED: Use PNG mime type
                        types.Part.from_bytes(data=initial_screenshot, mime_type="image/png")
                    ]
                )
            ]

            budget_error = self._ai_budget_error()
            if budget_error:
                print(f"[BUDGET] {budget_error}")
                if update_callback:
                    await update_callback(None, f"Error: {budget_error}")
                if self.browser:
                    await self.browser.close()
                    self.browser = None
                return budget_error

            MAX_TURNS = AI_MAX_TURNS
            
            for turn in range(MAX_TURNS):
                print(f"\n--- Turn {turn + 1} ---")
                
                try:
                    budget_error = self._ai_budget_error()
                    if budget_error:
                        print(f"[BUDGET] {budget_error}")
                        if update_callback:
                            await update_callback(None, f"Error: {budget_error}")
                        final_response = budget_error
                        break
                    self._record_ai_call()
                    response = await self.client.aio.models.generate_content(
                        model=MODEL_ID,
                        contents=chat_history,
                        config=config
                    )
                except Exception as e:
                    friendly_error = _friendly_api_error(e)
                    print(f"[CRITICAL] {friendly_error}")
                    if _is_ai_capacity_error(e):
                        self._record_ai_capacity_error()
                    if update_callback:
                        await update_callback(None, f"Error: {friendly_error}")
                    if self.browser:
                        await self.browser.close()
                        self.browser = None
                    raise WebAgentQuotaError(friendly_error) from e
                
                # Check for empty response
                if not response.candidates:
                    print("[WARN] Model returned no content.")
                    break
                
                candidate = response.candidates[0]
                model_content = candidate.content
                chat_history.append(model_content)

                # Process thoughts and tool calls
                has_tool_use = False
                thought_text = ""
                agent_text = ""
                
                for part in model_content.parts:
                    if part.thought:
                        print(f"[THOUGHT] Thought: {part.text}")
                        thought_text += f"[Thoughts] {part.text}\n"
                    elif part.text:
                        print(f"[AGENT] Agent: {part.text}")
                        thought_text += f"[Agent] {part.text}\n"
                        agent_text = part.text
                    if part.function_call:
                        has_tool_use = True
                
                if agent_text:
                    final_response = agent_text

                if update_callback and thought_text:
                     # Send thoughts without image update yet
                     pass # await update_callback(None, thought_text)

                function_calls = [part.function_call for part in model_content.parts if part.function_call]
                
                if not function_calls:
                    if not has_tool_use:
                        print("[DONE] Task finished details.")
                        if update_callback: await update_callback(None, "Task Finished")
                        break
                    else:
                        print("...Thinking...")
                        continue

                # Execute Actions
                results = await self.execute_function_calls(function_calls)
                
                # Capture new state
                print("[SNAP] Capturing new state...")
                function_responses, screenshot_bytes = await self.get_function_responses(results)
                
                # Update frontend
                if update_callback:
                    encoded_image = base64.b64encode(screenshot_bytes).decode('utf-8')
                    # Format a log message from the actions taken
                    actions_log = ", ".join([r[1] for r in results])
                    await update_callback(encoded_image, f"Executed: {actions_log}")

                # Send Response Back
                response_parts = [types.Part(function_response=fr) for fr in function_responses]
                chat_history.append(types.Content(role="user", parts=response_parts))

            if self.browser:
                await self.browser.close()
                self.browser = None
            print("[CLOSE] Browser closed.")
            return final_response

if __name__ == "__main__":
    agent = WebAgent()
    asyncio.run(agent.run_task("Go to google.com and search for 'Gemini API' pricing."))
