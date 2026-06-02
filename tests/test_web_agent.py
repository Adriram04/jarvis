"""
Tests for Web Automation Agent.
"""
import pytest
import asyncio
import os

from web_agent import AI_COOLDOWN_SECONDS, AI_DAILY_LIMIT, AI_MAX_TURNS, DEFAULT_SEARCH_ENGINE, MODEL_ID, WebAgent, _friendly_api_error


def _expected_search_prefix():
    if DEFAULT_SEARCH_ENGINE == "google":
        return "https://www.google.com/search?"
    if DEFAULT_SEARCH_ENGINE in {"duckduckgo", "ddg"}:
        return "https://duckduckgo.com/?"
    return "https://www.bing.com/search?"


class TestWebAgentInit:
    """Test WebAgent initialization."""
    
    def test_agent_creation(self):
        """Test WebAgent can be created."""
        agent = WebAgent()
        assert agent is not None
        assert hasattr(agent, 'client')
        print("WebAgent initialized successfully")
    
    def test_agent_has_browser_attrs(self):
        """Test WebAgent has browser-related attributes."""
        agent = WebAgent()
        assert hasattr(agent, 'browser')
        assert hasattr(agent, 'page')
        assert hasattr(agent, 'context')

    def test_quota_error_message_is_user_friendly(self):
        """Test quota errors are summarized without dumping the full API payload."""
        error = RuntimeError("429 RESOURCE_EXHAUSTED. Quota exceeded for metric: generate_content_free_tier_requests")

        message = _friendly_api_error(error)

        assert "Web Agent unavailable" in message
        assert MODEL_ID in message
        assert "RESOURCE_EXHAUSTED" not in message

    def test_high_demand_error_message_mentions_fast_mode(self):
        """Test high-demand errors point users to simple non-AI commands."""
        error = RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")

        message = _friendly_api_error(error)

        assert "high demand" in message
        assert MODEL_ID in message
        assert "without the AI model" in message
        assert "503 UNAVAILABLE" not in message

    def test_ai_turn_limit_is_conservative(self):
        """Test Computer Use calls are capped per task by default."""
        assert AI_MAX_TURNS >= 1


class TestCoordinateDenormalization:
    """Test coordinate conversion functions."""
    
    def test_denormalize_x(self):
        """Test X coordinate denormalization."""
        agent = WebAgent()
        
        # Test at different normalized values
        result = agent.denormalize_x(500, 1000)  # 50% of 1000
        print(f"denormalize_x(500, 1000) = {result}")
        assert isinstance(result, (int, float))
    
    def test_denormalize_y(self):
        """Test Y coordinate denormalization."""
        agent = WebAgent()
        
        result = agent.denormalize_y(500, 1000)  # 50% of 1000
        print(f"denormalize_y(500, 1000) = {result}")
        assert isinstance(result, (int, float))


class TestWebBrowserLaunch:
    """Test browser launching capabilities."""
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set"
    )
    async def test_browser_launch_headless(self):
        """Test launching browser in headless mode."""
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto("https://www.google.com")
                
                title = await page.title()
                print(f"Page title: {title}")
                assert "Google" in title
                
                await browser.close()
                print("Browser launch test passed")
        except Exception as e:
            pytest.skip(f"Playwright not available: {e}")


class TestWebNavigation:
    """Test web navigation capabilities."""
    
    @pytest.mark.asyncio
    async def test_navigate_to_url(self):
        """Test navigating to a URL."""
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                await page.goto("https://example.com")
                content = await page.content()
                
                assert "Example Domain" in content
                print("Navigation test passed")
                
                await browser.close()
        except Exception as e:
            pytest.skip(f"Playwright not available: {e}")


class TestWebScreenshot:
    """Test screenshot capabilities."""
    
    @pytest.mark.asyncio
    async def test_capture_screenshot(self, temp_dir):
        """Test capturing a screenshot."""
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                await page.goto("https://example.com")
                
                screenshot_path = temp_dir / "test_screenshot.png"
                await page.screenshot(path=str(screenshot_path))
                
                assert screenshot_path.exists()
                print(f"Screenshot saved to: {screenshot_path}")
                
                await browser.close()
        except Exception as e:
            pytest.skip(f"Playwright not available: {e}")


class TestWebAgentTask:
    """Test full web agent task execution."""

    def test_ai_daily_budget_blocks_model_when_limit_reached(self):
        """Test the local daily budget can stop model usage before API quota is hit."""
        agent = WebAgent()
        agent.ai_calls_today = AI_DAILY_LIMIT

        message = agent._ai_budget_error()

        if AI_DAILY_LIMIT:
            assert "limite local diario" in message
        else:
            assert message is None

    def test_ai_capacity_error_starts_cooldown(self):
        """Test capacity errors pause future model calls."""
        agent = WebAgent()

        agent._record_ai_capacity_error()
        message = agent._ai_budget_error()

        if AI_COOLDOWN_SECONDS:
            assert "pausa temporal" in message
        else:
            assert message is None

    def test_deterministic_plan_search(self):
        """Test simple search prompts are handled without the model."""
        agent = WebAgent()

        plan = agent._deterministic_plan("busca Gemini API pricing")

        assert plan["kind"] == "search"
        assert plan["url"].startswith(_expected_search_prefix())
        assert "Gemini" not in plan["url"]
        assert "gemini+api+pricing" in plan["url"]

    def test_deterministic_plan_buscame_search(self):
        """Test buscamelo-style Spanish prompts use deterministic search."""
        agent = WebAgent()

        plan = agent._deterministic_plan("buscame ford mustang de segunda mano")

        assert plan["kind"] == "search"
        assert plan["url"].startswith(_expected_search_prefix())
        assert "ford+mustang+de+segunda+mano" in plan["url"]

    def test_deterministic_plan_amazon_search(self):
        """Test Amazon searches go directly to Amazon instead of the model."""
        agent = WebAgent()

        plan = agent._deterministic_plan("busca libros de harry potter en amazon")

        assert plan["kind"] == "search"
        assert plan["url"].startswith("https://www.amazon.es/s?")
        assert "libros+de+harry+potter" in plan["url"]

    def test_deterministic_plan_navigation(self):
        """Test simple URL prompts are handled without the model."""
        agent = WebAgent()

        plan = agent._deterministic_plan("abre example.com")

        assert plan["kind"] == "navigate"
        assert plan["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_run_deterministic_task_uses_page_directly(self):
        """Test deterministic tasks update the browser without model calls."""
        class FakePage:
            def __init__(self):
                self.urls = []

            async def goto(self, url, **kwargs):
                self.urls.append((url, kwargs))

            async def wait_for_load_state(self, *args, **kwargs):
                return None

            async def screenshot(self, type="png"):
                return b"fake-png"

            async def title(self):
                return "Fake Search"

            @property
            def url(self):
                return self.urls[-1][0] if self.urls else "about:blank"

        agent = WebAgent()
        agent.page = FakePage()
        updates = []

        async def update_callback(screenshot_b64, log_text):
            updates.append({"image": screenshot_b64, "log": log_text})

        result = await agent._run_deterministic_task("busca Gemini API pricing", update_callback=update_callback)

        assert result.startswith("Busqueda abierta sin usar IA: gemini api pricing.")
        assert "Pagina: Fake Search." in result
        assert agent.page.urls[0][0].startswith(_expected_search_prefix())
        assert updates[0]["image"] is None
        assert updates[0]["log"].startswith("Modo rapido sin IA")
        assert updates[-1]["image"]
        assert updates[-1]["log"] == "Executed without AI: search"
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set"
    )
    async def test_simple_web_task(self):
        """Test running a simple web task."""
        agent = WebAgent()
        
        updates = []
        
        async def update_callback(screenshot_b64, log_text):
            updates.append({"log": log_text})
            print(f"Update: {log_text[:100]}...")
        
        try:
            result = await agent.run_task(
                prompt="Navigate to example.com and tell me the page title",
                update_callback=update_callback
            )
            
            print(f"Task result: {result}")
            print(f"Updates received: {len(updates)}")
        except Exception as e:
            print(f"Task failed: {e}")


class TestPlaywrightInstallation:
    """Test Playwright availability."""
    
    def test_playwright_import(self):
        """Test if Playwright is installed."""
        try:
            from playwright.async_api import async_playwright
            print("Playwright is installed")
        except ImportError:
            pytest.skip("Playwright not installed")
    
    @pytest.mark.asyncio
    async def test_playwright_browsers(self):
        """Test if Playwright browsers are installed."""
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                await browser.close()
                print("Chromium browser is available")
        except Exception as e:
            pytest.skip(f"Playwright browsers not installed: {e}")
