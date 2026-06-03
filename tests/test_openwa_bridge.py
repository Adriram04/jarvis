"""Tests for OpenWABridge.

Todos los tests usan mocks de aiohttp — no hacen peticiones reales.
No se envían mensajes reales a WhatsApp.
"""
import asyncio
import os
import sys
import types

import pytest

# Ensure backend is importable when run from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))


# ---------------------------------------------------------------------------
# Helpers: fake aiohttp context managers
# ---------------------------------------------------------------------------

def _fake_response(status, body):
    """Build a minimal fake aiohttp response object."""
    import json as _json
    text_body = _json.dumps(body) if isinstance(body, (dict, list)) else str(body or '')

    class _FakeResponse:
        def __init__(self):
            self.status = status

        async def text(self):
            return text_body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return _FakeResponse()


def _fake_session(get_resp=None, post_resp=None):
    """Build a fake aiohttp.ClientSession."""
    class _FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, url, **kwargs):
            return get_resp or _fake_response(200, {"status": "ok"})

        def post(self, url, **kwargs):
            return post_resp or _fake_response(200, {"success": True})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return _FakeSession


def _patch_aiohttp(monkeypatch, get_resp=None, post_resp=None):
    """Patch aiohttp.ClientSession inside the bridge module."""
    from integrations import openwa_bridge as bridge_module
    fake_session_cls = _fake_session(get_resp, post_resp)

    fake_aiohttp = types.ModuleType("aiohttp")
    fake_aiohttp.ClientSession = fake_session_cls

    class _FakeTimeout:
        def __init__(self, total=None):
            pass
    fake_aiohttp.ClientTimeout = _FakeTimeout

    monkeypatch.setattr(bridge_module, "__import__", None, raising=False)
    # Patch at import-time call inside the function
    import unittest.mock as mock
    monkeypatch.setattr("builtins.__import__", lambda name, *args, **kwargs: fake_aiohttp if name == "aiohttp" else __import__(name, *args, **kwargs))


def _make_bridge(enabled=True, api_key="test-key-abc", session_id="jarvis-main", send_style="send-text"):
    """Create an OpenWABridge with controlled env vars."""
    from integrations.openwa_bridge import OpenWABridge
    bridge = OpenWABridge.__new__(OpenWABridge)
    bridge.enabled = enabled
    bridge.base_url = "http://127.0.0.1:2785/api"
    bridge.api_key = api_key
    bridge.session_id = session_id
    bridge.timeout_seconds = 5.0
    bridge.send_style = send_style
    return bridge


def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# 1. OpenWA disabled → error limpio
# ---------------------------------------------------------------------------

def test_disabled_returns_clean_error():
    bridge = _make_bridge(enabled=False)
    result = run(bridge.send_message("+34600111222", "hola"))
    assert result["success"] is False
    assert "JARVIS_OPENWA_ENABLED=false" in result["summary"]
    assert result["provider"] == "openwa"


# ---------------------------------------------------------------------------
# 2. Falta API key → error limpio
# ---------------------------------------------------------------------------

def test_missing_api_key_returns_clean_error():
    bridge = _make_bridge(api_key="")
    result = run(bridge.send_message("+34600111222", "hola"))
    assert result["success"] is False
    assert "API_KEY" in result["summary"] or "api_key" in result["summary"].lower()


# ---------------------------------------------------------------------------
# 3. check_status llama a /health
# ---------------------------------------------------------------------------

def test_check_status_calls_health(monkeypatch):
    called_urls = []

    async def fake_get(self, path, timeout=None):
        called_urls.append(path)
        return {"success": True, "status": 200, "text": '{"status":"ok"}', "json": {"status": "ok"}}

    bridge = _make_bridge()
    monkeypatch.setattr(bridge.__class__, "_http_get", fake_get)
    result = run(bridge.check_status())
    assert "/health" in called_urls
    assert result["available"] is True
    assert result["provider"] == "openwa"


# ---------------------------------------------------------------------------
# 4. Normaliza +34 600 111 222 → 34600111222@c.us
# ---------------------------------------------------------------------------

def test_normalize_phone_with_spaces_and_prefix():
    bridge = _make_bridge()
    result = bridge._normalize_target("+34 600 111 222")
    assert result == "34600111222@c.us"


def test_normalize_phone_with_dashes():
    bridge = _make_bridge()
    result = bridge._normalize_target("34 600-111-222")
    assert result == "34600111222@c.us"


def test_normalize_plain_digits():
    bridge = _make_bridge()
    result = bridge._normalize_target("34600111222")
    assert result == "34600111222@c.us"


# ---------------------------------------------------------------------------
# 5. Respeta canonical_target terminado en @c.us
# ---------------------------------------------------------------------------

def test_respects_canonical_target_c_us():
    bridge = _make_bridge()
    result = bridge._normalize_target("+34600111222", canonical_target="34600111222@c.us")
    assert result == "34600111222@c.us"


# ---------------------------------------------------------------------------
# 6. Respeta canonical_target terminado en @g.us
# ---------------------------------------------------------------------------

def test_respects_canonical_target_g_us():
    bridge = _make_bridge()
    result = bridge._normalize_target("grupo", canonical_target="120363000000000000@g.us")
    assert result == "120363000000000000@g.us"


# ---------------------------------------------------------------------------
# 7. send-text funciona (HTTP 200)
# ---------------------------------------------------------------------------

def test_send_text_success(monkeypatch):
    post_calls = []

    async def fake_post(self, path, data, timeout=None):
        post_calls.append((path, data))
        return {"success": True, "status": 200, "text": '{"id":"msg1"}', "json": {"id": "msg1"}}

    bridge = _make_bridge()
    monkeypatch.setattr(bridge.__class__, "_http_post", fake_post)
    result = run(bridge.send_message("34600111222@c.us", "hola"))
    assert result["success"] is True
    assert any("send-text" in p for p, _ in post_calls)


# ---------------------------------------------------------------------------
# 8. Si send-text devuelve 404 usa fallback /messages
# ---------------------------------------------------------------------------

def test_send_text_404_falls_back_to_messages(monkeypatch):
    call_count = {"n": 0}

    async def fake_post(self, path, data, timeout=None):
        call_count["n"] += 1
        if "send-text" in path:
            return {"success": False, "status": 404, "text": "Not Found", "json": None}
        # fallback /messages
        return {"success": True, "status": 200, "text": '{"id":"msg2"}', "json": {"id": "msg2"}}

    bridge = _make_bridge()
    monkeypatch.setattr(bridge.__class__, "_http_post", fake_post)
    result = run(bridge.send_message("34600111222@c.us", "hola"))
    assert result["success"] is True
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# 9. 401 / 403 / 500 no lanzan excepción, devuelven result limpio
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status_code", [401, 403, 500])
def test_http_errors_return_clean_result(monkeypatch, status_code):
    async def fake_post(self, path, data, timeout=None):
        return {"success": False, "status": status_code, "text": "Error", "json": None}

    bridge = _make_bridge()
    monkeypatch.setattr(bridge.__class__, "_http_post", fake_post)
    result = run(bridge.send_message("34600111222@c.us", "hola"))
    assert result["success"] is False
    assert isinstance(result["summary"], str)
    assert len(result["summary"]) > 0


# ---------------------------------------------------------------------------
# 10. execute_action("send_message", payload) llama a send_message
# ---------------------------------------------------------------------------

def test_execute_action_send_message(monkeypatch):
    called = {}

    async def fake_send(self, target, message, canonical_target=None, metadata=None):
        called["target"] = target
        called["message"] = message
        return {"success": True, "service": "openwa", "provider": "openwa", "action_type": "send_message",
                "target": target, "canonical_target": target, "summary": "OK", "raw": None}

    bridge = _make_bridge()
    monkeypatch.setattr(bridge.__class__, "send_message", fake_send)
    result = run(bridge.execute_action("send_message", {"target": "34600111222@c.us", "message": "test"}))
    assert result["success"] is True
    assert called["target"] == "34600111222@c.us"


# ---------------------------------------------------------------------------
# 11. execute_action("send_whatsapp_message", payload) llama a send_message
# ---------------------------------------------------------------------------

def test_execute_action_send_whatsapp_message(monkeypatch):
    called = {}

    async def fake_send(self, target, message, canonical_target=None, metadata=None):
        called["ok"] = True
        return {"success": True, "service": "openwa", "provider": "openwa", "action_type": "send_whatsapp_message",
                "target": target, "canonical_target": target, "summary": "OK", "raw": None}

    bridge = _make_bridge()
    monkeypatch.setattr(bridge.__class__, "send_message", fake_send)
    result = run(bridge.execute_action("send_whatsapp_message", {"target": "34600111222@c.us", "message": "test"}))
    assert result["success"] is True
    assert called.get("ok") is True


# ---------------------------------------------------------------------------
# 12. execute_action("openclaw_send_message", {channel: "whatsapp"}) usa OpenWA
# ---------------------------------------------------------------------------

def test_execute_action_openclaw_send_message_whatsapp(monkeypatch):
    called = {}

    async def fake_send(self, target, message, canonical_target=None, metadata=None):
        called["ok"] = True
        return {"success": True, "service": "openwa", "provider": "openwa", "action_type": "openclaw_send_message",
                "target": target, "canonical_target": target, "summary": "OK", "raw": None}

    bridge = _make_bridge()
    monkeypatch.setattr(bridge.__class__, "send_message", fake_send)
    result = run(bridge.execute_action("openclaw_send_message", {
        "channel": "whatsapp",
        "target": "34600111222@c.us",
        "message": "hola",
    }))
    assert result["success"] is True
    assert called.get("ok") is True


# ---------------------------------------------------------------------------
# 13. execute_action con acción no soportada → error limpio sin excepción
# ---------------------------------------------------------------------------

def test_execute_action_unsupported_returns_clean_error():
    bridge = _make_bridge()
    result = run(bridge.execute_action("create_calendar_event", {"title": "Reunión"}))
    assert result["success"] is False
    assert "no soportada" in result["summary"].lower() or "no soportad" in result["summary"].lower()
    assert result["provider"] == "openwa"
