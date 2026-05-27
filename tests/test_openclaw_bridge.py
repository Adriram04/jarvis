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


def test_directory_self_builds_command(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    seen = {}

    async def fake_run_cli(args, timeout):
        seen["args"] = args
        return {"success": True, "stdout": json.dumps({"success": True}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    asyncio.run(bridge.directory_self())

    assert seen["args"] == ["directory", "self", "--channel", "whatsapp", "--json"]


def test_directory_peers_builds_command(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    seen = {}

    async def fake_run_cli(args, timeout):
        seen["args"] = args
        return {"success": True, "stdout": json.dumps({"success": True}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    asyncio.run(bridge.directory_peers(query="Adri", limit=25, account="main"))

    assert seen["args"] == [
        "directory",
        "peers",
        "list",
        "--channel",
        "whatsapp",
        "--limit",
        "25",
        "--query",
        "Adri",
        "--account",
        "main",
        "--json",
    ]


def test_directory_groups_builds_command(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    seen = {}

    async def fake_run_cli(args, timeout):
        seen["args"] = args
        return {"success": True, "stdout": json.dumps({"success": True}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    asyncio.run(bridge.directory_groups(limit=10))

    assert seen["args"] == ["directory", "groups", "list", "--channel", "whatsapp", "--limit", "10", "--json"]


def test_resolve_target_uses_kind_group(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    seen = {}

    async def fake_run_cli(args, timeout):
        seen["args"] = args
        return {"success": True, "stdout": json.dumps({"success": True}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    asyncio.run(bridge.resolve_target("whatsapp", "Grupo TFG", kind="group"))

    assert seen["args"] == ["channels", "resolve", "--channel", "whatsapp", "--kind", "group", "Grupo TFG", "--json"]


def test_send_message_uses_canonical_target_when_present(monkeypatch):
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
        "canonical_target": "120363000000000000@g.us",
        "display_target": "Grupo TFG",
        "message": "Hola",
    }))

    assert seen["args"][seen["args"].index("--target") + 1] == "120363000000000000@g.us"
    assert result["summary"] == "Mensaje enviado mediante whatsapp a Grupo TFG."


def test_whatsapp_send_skips_required_resolve(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    monkeypatch.setenv("JARVIS_OPENCLAW_REQUIRE_RESOLVE", "true")
    bridge = OpenClawBridge()
    calls = []

    async def fake_run_cli(args, timeout):
        calls.append(args)
        return {"success": True, "stdout": json.dumps({"success": True}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    asyncio.run(bridge.execute_action("send_message", {"channel": "whatsapp", "target": "+34722129717", "message": "Hola"}))

    assert len(calls) == 1
    assert calls[0][:2] == ["message", "send"]
    assert ["channels", "resolve"] not in calls


def test_send_message_adds_dry_run(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    seen = {}

    async def fake_run_cli(args, timeout):
        seen["args"] = args
        return {"success": True, "stdout": json.dumps({"success": True}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    asyncio.run(bridge.execute_action("send_message", {"target": "+34625941034", "message": "Hola", "dry_run": True}))

    assert "--dry-run" in seen["args"]


def test_read_conversation_uses_message_read(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    seen = {}

    async def fake_run_cli(args, timeout):
        seen["args"] = args
        return {"success": True, "stdout": json.dumps({"success": True}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    asyncio.run(bridge.read_conversation("whatsapp", "+34625941034", limit=5, message_id="abc"))

    assert seen["args"] == [
        "message",
        "read",
        "--channel",
        "whatsapp",
        "--target",
        "+34625941034",
        "--limit",
        "5",
        "--message-id",
        "abc",
        "--json",
    ]


def test_list_messages_calls_message_read_not_message_list(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    calls = []

    async def fake_run_cli(args, timeout):
        calls.append(args)
        return {"success": True, "stdout": json.dumps({"success": True}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    asyncio.run(bridge.list_messages("telegram", "chat-1"))

    assert calls[0][:2] == ["message", "read"]
    assert calls[0][:2] != ["message", "list"]


def test_whatsapp_list_messages_does_not_call_cli_read(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()
    calls = []

    async def fake_run_cli(args, timeout):
        calls.append(args)
        return {"success": True, "stdout": json.dumps({"success": True}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    result = asyncio.run(bridge.list_messages("whatsapp", "+34722129717"))

    assert calls == []
    assert result["code"] == "OPENCLAW_WHATSAPP_READ_UNSUPPORTED"


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


def test_calendar_actions_use_productivity_gateway_method_by_default(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    monkeypatch.delenv("JARVIS_OPENCLAW_GENERIC_CALL_METHOD", raising=False)
    bridge = OpenClawBridge()
    seen = {}

    async def fake_run_cli(args, timeout):
        seen["args"] = args
        return {"success": True, "stdout": json.dumps({"success": True, "details": "created"}), "returncode": 0, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    result = asyncio.run(bridge.execute_action("create_calendar_event", {"title": "Demo"}))

    assert seen["args"][:3] == ["gateway", "call", "jarvis.productivity.execute"]
    assert result["success"] is True


def test_social_actions_report_missing_productivity_method_when_plugin_absent(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    monkeypatch.delenv("JARVIS_OPENCLAW_GENERIC_CALL_METHOD", raising=False)
    bridge = OpenClawBridge()

    async def fake_run_cli(args, timeout):
        return {"success": False, "stderr": "method not found", "returncode": 1, "command": ["openclaw", *args]}

    monkeypatch.setattr(bridge, "_run_cli", fake_run_cli)
    result = asyncio.run(bridge.execute_action("publish_social_post", {"platform": "linkedin", "content": "Hola"}))

    assert result["success"] is False
    assert result["warnings"] == ["missing_openclaw_productivity_method"]


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


def test_allowlist_error_is_normalized(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()

    result = bridge._normalize_result(
        {
            "success": False,
            "stderr": "target +34000000000 is not listed in the configured WhatsApp allowlist",
            "returncode": 1,
        },
        "send_message",
    )

    assert result["success"] is False
    assert result["code"] == "OPENCLAW_WHATSAPP_ALLOWLIST_BLOCKED"
    assert result["error"] == "Target is not allowed by the configured WhatsApp allowlist."


def test_whatsapp_resolve_unsupported_is_normalized(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()

    result = bridge._normalize_result(
        {
            "success": False,
            "stderr": 'Error: Channel "whatsapp" does not support resolve.',
            "returncode": 1,
        },
        "resolve_target",
    )

    assert result["success"] is False
    assert result["code"] == "OPENCLAW_WHATSAPP_RESOLVE_UNSUPPORTED"
    assert result["error"] == "WhatsApp no soporta resolución de targets mediante OpenClaw. Usa agenda local de Jarvis."


def test_whatsapp_read_unsupported_is_normalized(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENCLAW_ENABLED", "true")
    bridge = OpenClawBridge()

    result = bridge._normalize_result(
        {
            "success": False,
            "stderr": "Error: Message action read not supported for channel whatsapp.",
            "returncode": 1,
        },
        "read_conversation",
    )

    assert result["success"] is False
    assert result["code"] == "OPENCLAW_WHATSAPP_READ_UNSUPPORTED"
    assert result["error"] == "WhatsApp no soporta lectura de historial mediante OpenClaw. Usa mensajes inbound guardados en Jarvis."
