import pytest

import server
from openclaw_events_manager import OpenClawEventsManager
from openclaw_messages_manager import OpenClawMessagesManager
from openclaw_targets_manager import OpenClawTargetsManager
from pending_actions_manager import PendingActionsManager


class FakeSession:
    def __init__(self):
        self.sent = []

    async def send(self, input=None, end_of_turn=False, **kwargs):
        self.sent.append({"input": input, "end_of_turn": end_of_turn, **kwargs})


class FakeProjectManager:
    def __init__(self):
        self.logs = []

    def log_chat(self, sender, message):
        self.logs.append((sender, message))


class FakeAudioLoop:
    def __init__(self):
        self.session = FakeSession()
        self.project_manager = FakeProjectManager()

    def resolve_tool_confirmation(self, request_id, confirmed):
        self.resolved = (request_id, confirmed)


class FakeOpenClawBridge:
    def __init__(self):
        self.calls = []

    async def execute_action(self, action_type, payload):
        self.calls.append((action_type, payload))
        return {
            "success": True,
            "service": "openclaw",
            "action_type": action_type,
            "summary": "Mensaje enviado mediante whatsapp a Laura.",
            "raw": {"ok": True},
            "external_id": "msg-1",
            "warnings": [],
        }


@pytest.fixture
def openclaw_voice_flow(monkeypatch, tmp_path):
    targets = OpenClawTargetsManager(tmp_path / "targets.json")
    messages = OpenClawMessagesManager(tmp_path / "messages.json")
    pending = PendingActionsManager(tmp_path / "pending.json")
    events = OpenClawEventsManager(tmp_path / "events.json")
    loop = FakeAudioLoop()
    bridge = FakeOpenClawBridge()
    emissions = []

    async def fake_emit(event, data=None, *args, **kwargs):
        emissions.append((event, data, kwargs))

    monkeypatch.setattr(server, "openclaw_targets_manager", targets)
    monkeypatch.setattr(server, "openclaw_messages_manager", messages)
    monkeypatch.setattr(server, "pending_actions_manager", pending)
    monkeypatch.setattr(server, "openclaw_events_manager", events)
    monkeypatch.setattr(server, "openclaw_bridge", bridge)
    monkeypatch.setattr(server, "audio_loop", loop)
    monkeypatch.setattr(server.sio, "emit", fake_emit)
    return targets, messages, pending, loop, emissions, bridge


@pytest.mark.asyncio
async def test_openclaw_voice_intent_does_not_pass_original_text_to_model(openclaw_voice_flow):
    targets, _, pending, loop, emissions, _ = openclaw_voice_flow
    text = "manda un mensaje a Laura diciendo hola"
    targets.add_target(
        "whatsapp",
        "user",
        "Laura",
        "+34722129717",
        canonical_target="+34722129717",
        aliases=["Laura"],
        allowed=True,
    )

    await server.user_input("sid-1", {"text": text})

    assert pending.get_pending_actions()[0]["payload"]["canonical_target"] == "+34722129717"
    assert any(event == "openclaw_pending_action" for event, _, _ in emissions)
    assert any(event == "tool_confirmation_request" for event, _, _ in emissions)
    assert not any(item["input"] == text for item in loop.session.sent)
    assert not any(item["end_of_turn"] for item in loop.session.sent)


@pytest.mark.asyncio
async def test_unhandled_text_keeps_general_model_flow(openclaw_voice_flow):
    _, _, _, loop, _, _ = openclaw_voice_flow
    text = "hola jarvis"

    await server.user_input("sid-1", {"text": text})

    assert any(item["input"] == text and item["end_of_turn"] for item in loop.session.sent)


@pytest.mark.asyncio
async def test_confirm_tool_executes_local_pending_action(openclaw_voice_flow):
    targets, _, pending, _, emissions, bridge = openclaw_voice_flow
    targets.add_target("whatsapp", "user", "Laura", "+34722129717", canonical_target="+34722129717", aliases=["Laura"], allowed=True)

    await server.user_input("sid-1", {"text": "avísale a Laura que salgo ya"})
    action = pending.get_pending_actions()[0]
    await server.confirm_tool("sid-1", {"id": action["id"], "confirmed": True})

    executed = pending.get_action(action["id"])
    assert executed["status"] == "executed"
    assert bridge.calls[0][0] == "send_message"
    assert bridge.calls[0][1]["canonical_target"] == "+34722129717"
    assert any(event == "transcription" and "Mensaje enviado" in data["text"] for event, data, _ in emissions)


@pytest.mark.asyncio
async def test_text_confirmation_executes_local_pending_action(openclaw_voice_flow):
    targets, _, pending, loop, emissions, bridge = openclaw_voice_flow
    targets.add_target("whatsapp", "user", "Laura", "+34722129717", canonical_target="+34722129717", aliases=["Laura"], allowed=True)

    await server.user_input("sid-1", {"text": "dile a Laura que hola"})
    action = pending.get_pending_actions()[0]
    await server.user_input("sid-1", {"text": "lo confirmo"})

    executed = pending.get_action(action["id"])
    assert executed["status"] == "executed"
    assert bridge.calls[0][0] == "send_message"
    assert not any(item["input"] == "lo confirmo" for item in loop.session.sent)
    assert any(event == "transcription" and "Mensaje enviado" in data["text"] for event, data, _ in emissions)


@pytest.mark.asyncio
async def test_text_confirmation_accepts_composite_phrase(openclaw_voice_flow):
    targets, _, pending, loop, emissions, bridge = openclaw_voice_flow
    targets.add_target("whatsapp", "user", "Laura", "+34722129717", canonical_target="+34722129717", aliases=["Laura"], allowed=True)

    await server.user_input("sid-1", {"text": "dile a Laura que hola"})
    action = pending.get_pending_actions()[0]
    await server.user_input("sid-1", {"text": "si confirmo"})

    executed = pending.get_action(action["id"])
    assert executed["status"] == "executed"
    assert bridge.calls[0][0] == "send_message"
    assert not any(item["input"] == "si confirmo" for item in loop.session.sent)
    assert any(event == "transcription" and "Mensaje enviado" in data["text"] for event, data, _ in emissions)


@pytest.mark.asyncio
async def test_confirm_tool_cancels_local_pending_action(openclaw_voice_flow):
    targets, _, pending, _, emissions, bridge = openclaw_voice_flow
    targets.add_target("whatsapp", "user", "Laura", "+34722129717", canonical_target="+34722129717", aliases=["Laura"], allowed=True)

    await server.user_input("sid-1", {"text": "dile a Laura que hola"})
    action = pending.get_pending_actions()[0]
    await server.confirm_tool("sid-1", {"id": action["id"], "confirmed": False})

    cancelled = pending.get_action(action["id"])
    assert cancelled["status"] == "cancelled"
    assert bridge.calls == []
    assert any(event == "transcription" and "cancelada" in data["text"].lower() for event, data, _ in emissions)


@pytest.mark.asyncio
async def test_text_cancellation_cancels_local_pending_action(openclaw_voice_flow):
    targets, _, pending, loop, emissions, bridge = openclaw_voice_flow
    targets.add_target("whatsapp", "user", "Laura", "+34722129717", canonical_target="+34722129717", aliases=["Laura"], allowed=True)

    await server.user_input("sid-1", {"text": "dile a Laura que hola"})
    action = pending.get_pending_actions()[0]
    await server.user_input("sid-1", {"text": "no lo envies"})

    cancelled = pending.get_action(action["id"])
    assert cancelled["status"] == "cancelled"
    assert bridge.calls == []
    assert not any(item["input"] == "no lo envies" for item in loop.session.sent)
    assert any(event == "transcription" and "cancelada" in data["text"].lower() for event, data, _ in emissions)
