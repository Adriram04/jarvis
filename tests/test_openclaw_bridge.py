import asyncio
import json

from integrations.openclaw_bridge import OpenClawBridge


def test_openclaw_disabled_returns_clean_message(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "false")
    bridge = OpenClawBridge()

    result = asyncio.run(bridge.execute_action("send_message", {"message": "hola"}))

    assert result["success"] is False
    assert result["summary"] == "OpenClaw no esta habilitado."
    assert result["service"] == "openclaw"


def test_check_status_uses_gateway_call_health(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    monkeypatch.setenv("JARVIS_OPENCLAW_MODE", "cli")
    bridge = OpenClawBridge()
    seen = {}

    async def fake_run_cli(args, timeout):
        seen["args"] = args
        seen["timeout"] = timeout
        return {"success": True, "stdout": json.dumps({"ok": True}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    result = asyncio.run(bridge.check_status())

    assert seen["args"][:4] == ["gateway", "call", "health", "--json"]
    assert seen["timeout"] == 20
    assert result["success"] is True
    assert result["summary"] == "OpenClaw Gateway esta activo."


def test_check_status_fallback_uses_status_if_health_fails(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    monkeypatch.setenv("JARVIS_OPENCLAW_MODE", "cli")
    bridge = OpenClawBridge()
    calls = []

    async def fake_run_cli(args, timeout):
        calls.append(args)
        if args[2] == "health":
            return {"success": False, "stderr": "method not found", "returncode": 1, "command": ["openclaw", *args]}
        return {"success": True, "stdout": json.dumps({"runtimeVersion": "2026.5.7"}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    result = asyncio.run(bridge.check_status())

    assert calls[0][:3] == ["gateway", "call", "health"]
    assert calls[1][:3] == ["gateway", "call", "status"]
    assert result["success"] is True


def test_health_ok_and_whatsapp_connected_normalizes_success(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    raw = {
        "success": True,
        "stdout": json.dumps({
            "ok": True,
            "channels": {
                "whatsapp": {
                    "enabled": True,
                    "configured": True,
                    "running": True,
                    "connected": True,
                    "status": "healthy",
                    "linked": True,
                }
            },
        }),
        "returncode": 0,
    }

    result = bridge._normalize_result(raw, "check_status")

    assert result["success"] is True
    assert result["summary"] == "OpenClaw Gateway esta activo. WhatsApp esta conectado."


def test_status_runtime_version_normalizes_success(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()

    result = bridge._normalize_result(
        {"success": True, "stdout": json.dumps({"runtimeVersion": "2026.5.7"}), "returncode": 0},
        "check_status",
    )

    assert result["success"] is True
    assert result["summary"] == "OpenClaw Gateway esta activo."


def test_event_loop_degraded_is_warning(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()

    result = bridge._normalize_result(
        {"success": True, "stdout": json.dumps({"ok": True, "eventLoop": "degraded"}), "returncode": 0},
        "check_status",
    )

    assert result["success"] is True
    assert "OpenClaw reporta event loop degradado." in result["warnings"]


def test_execute_action_send_message_builds_message_send(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    seen = {}

    async def fake_run_cli(args, timeout):
        seen["args"] = args
        return {"success": True, "stdout": json.dumps({"success": True}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    result = asyncio.run(bridge.execute_action("send_message", {
        "channel": "whatsapp",
        "target": "Grupo TFG",
        "message": "Mensaje de prueba desde Jarvis",
    }))

    assert seen["args"] == [
        "message",
        "send",
        "--channel",
        "whatsapp",
        "--target",
        "Grupo TFG",
        "--message",
        "Mensaje de prueba desde Jarvis",
        "--json",
    ]
    assert result["success"] is True
    assert result["summary"] == "Mensaje enviado mediante whatsapp a Grupo TFG."


def test_execute_action_send_whatsapp_message_uses_whatsapp_default(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    seen = {}

    async def fake_run_cli(args, timeout):
        seen["args"] = args
        return {"success": True, "stdout": "sent", "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    asyncio.run(bridge.execute_action("send_whatsapp_message", {"target": "+15555550123", "text": "Hi"}))

    assert "--channel" in seen["args"]
    assert seen["args"][seen["args"].index("--channel") + 1] == "whatsapp"


def test_execute_action_never_uses_openclaw_run(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    commands = []

    async def fake_run_cli(args, timeout):
        commands.append(args)
        return {"success": True, "stdout": "ok", "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    asyncio.run(bridge.execute_action("send_message", {"target": "Grupo TFG", "message": "Hola"}))

    assert all(not args or args[0] != "run" for args in commands)


def test_email_calendar_social_without_generic_method_returns_missing_method(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    monkeypatch.delenv("JARVIS_OPENCLAW_GENERIC_CALL_METHOD", raising=False)
    bridge = OpenClawBridge()

    result = asyncio.run(bridge.execute_action("send_email", {"to": "a@example.com"}))

    assert result["success"] is False
    assert result["warnings"] == ["missing_openclaw_method"]


def test_generic_fallback_uses_gateway_call_method(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    monkeypatch.setenv("JARVIS_OPENCLAW_GENERIC_CALL_METHOD", "jarvis.execute")
    bridge = OpenClawBridge()
    seen = {}

    async def fake_run_cli(args, timeout):
        seen["args"] = args
        return {"success": True, "stdout": json.dumps({"success": True, "details": "done"}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    result = asyncio.run(bridge.execute_action("send_email", {"to": "a@example.com"}))

    assert seen["args"][:3] == ["gateway", "call", "jarvis.execute"]
    assert "--params" in seen["args"]
    assert result["success"] is True


def test_file_not_found_returns_clean_message(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    monkeypatch.setenv("JARVIS_OPENCLAW_EXECUTABLE", "definitely-not-openclaw")
    bridge = OpenClawBridge()

    result = asyncio.run(bridge.check_status())

    assert result["success"] is False
    assert result["summary"] == "OpenClaw executable is not available."


def test_timeout_returns_clean_message(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()

    async def fake_run_cli(args, timeout):
        return {"unavailable": True, "summary": "OpenClaw CLI timed out.", "warnings": ["timeout"]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    result = asyncio.run(bridge.execute_action("send_message", {"target": "x", "message": "y"}))

    assert result["success"] is False
    assert result["summary"] == "OpenClaw CLI timed out."


def test_secrets_are_redacted(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()

    result = bridge._normalize_result({
        "success": False,
        "details": "x" * 1000,
        "payload": {"token": "secret-token"},
        "command": ["openclaw", "gateway", "call", "x", "--token", "secret-token"],
    }, "send_message")

    assert len(result["summary"]) <= 503
    assert result["raw"]["payload"]["token"] == "[REDACTED]"
    assert result["raw"]["command"][-1] == "[REDACTED]"


def test_specific_error_summaries(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()

    unknown = bridge._normalize_result({"success": False, "stderr": "Unknown command: x", "returncode": 1}, "send_message")
    method = bridge._normalize_result({"success": False, "stderr": "method not found", "returncode": 1}, "send_email")
    scope = bridge._normalize_result({"success": False, "stderr": "missing scope", "returncode": 1}, "send_message")

    assert unknown["summary"] == "Comando OpenClaw no reconocido."
    assert method["summary"] == "Metodo RPC de OpenClaw no encontrado."
    assert scope["summary"] == "OpenClaw respondio, pero faltan permisos para esa operacion."
