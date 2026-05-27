from fastapi.testclient import TestClient

import server
from openclaw_autopilot_manager import OpenClawAutopilotManager
from openclaw_events_manager import OpenClawEventsManager
from openclaw_messages_manager import OpenClawMessagesManager
from openclaw_targets_manager import OpenClawTargetsManager
from pending_actions_manager import PendingActionsManager


def _reset_openclaw_state(monkeypatch, tmp_path):
    events = OpenClawEventsManager(tmp_path / "events.json")
    messages = OpenClawMessagesManager(tmp_path / "messages.json")
    autopilot = OpenClawAutopilotManager(tmp_path / "rules.json")
    pending = PendingActionsManager(tmp_path / "pending.json")
    targets = OpenClawTargetsManager(tmp_path / "targets.json")
    monkeypatch.setattr(server, "openclaw_events_manager", events)
    monkeypatch.setattr(server, "openclaw_messages_manager", messages)
    monkeypatch.setattr(server, "openclaw_autopilot_manager", autopilot)
    monkeypatch.setattr(server, "pending_actions_manager", pending)
    monkeypatch.setattr(server, "openclaw_targets_manager", targets)
    monkeypatch.setenv("JARVIS_OPENCLAW_AUTOPILOT_ENABLED", "true")
    return events, messages, autopilot, pending, targets


def test_rejects_wrong_secret(monkeypatch, tmp_path):
    _reset_openclaw_state(monkeypatch, tmp_path)
    monkeypatch.setenv("JARVIS_OPENCLAW_INBOUND_SECRET", "good-secret")
    client = TestClient(server.app)

    response = client.post("/api/openclaw/inbound", json={"message": "hola"}, headers={"X-Jarvis-OpenClaw-Secret": "bad"})

    assert response.status_code == 401
    assert response.json()["success"] is False


def test_accepts_when_no_secret_configured(monkeypatch, tmp_path):
    _reset_openclaw_state(monkeypatch, tmp_path)
    monkeypatch.delenv("JARVIS_OPENCLAW_INBOUND_SECRET", raising=False)
    client = TestClient(server.app)

    response = client.post("/api/openclaw/inbound", json={"channel": "whatsapp", "target": "+346", "text": "hola"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["incoming"]["message"] == "hola"


def test_normalizes_inbound_and_creates_event(monkeypatch, tmp_path):
    events, messages, _, _, _ = _reset_openclaw_state(monkeypatch, tmp_path)
    monkeypatch.delenv("JARVIS_OPENCLAW_INBOUND_SECRET", raising=False)
    client = TestClient(server.app)

    response = client.post("/api/openclaw/inbound", json={
        "channel": "whatsapp",
        "kind": "user",
        "target": "+34625941034",
        "display_target": "Adrian",
        "sender": {"id": "+34625941034", "name": "Adrian"},
        "message": {"id": "msg-1", "text": "hola"},
    })

    body = response.json()
    assert body["data"]["incoming"]["message"] == "hola"
    assert body["data"]["incoming"]["sender_name"] == "Adrian"
    assert events.list_events(type="inbound")[0]["message"] == "hola"
    assert messages.list_new_messages("whatsapp", "+34625941034")[0]["message"] == "hola"


def test_matched_false_when_no_rules(monkeypatch, tmp_path):
    _reset_openclaw_state(monkeypatch, tmp_path)
    monkeypatch.delenv("JARVIS_OPENCLAW_INBOUND_SECRET", raising=False)
    client = TestClient(server.app)

    response = client.post("/api/openclaw/inbound", json={"channel": "whatsapp", "target": "canonical-a", "text": "hola"})

    assert response.json()["matched"] is False


def test_matched_true_when_rule_matches(monkeypatch, tmp_path):
    _, _, autopilot, _, _ = _reset_openclaw_state(monkeypatch, tmp_path)
    monkeypatch.delenv("JARVIS_OPENCLAW_INBOUND_SECRET", raising=False)
    autopilot.create_rule(
        "whatsapp",
        "canonical-a",
        "draft_only",
        {"type": "keywords", "keywords": ["reunion"]},
        {"instruction": "Responder breve.", "forbidden_topics": [], "max_messages_per_hour": 3},
        kind="user",
        display_target="Adrian",
    )
    client = TestClient(server.app)

    response = client.post("/api/openclaw/inbound", json={
        "channel": "whatsapp",
        "kind": "user",
        "target": "canonical-a",
        "text": "reunión mañana",
    })

    assert response.json()["matched"] is True
    assert response.json()["rule_id"]


def test_ask_before_send_creates_pending_action(monkeypatch, tmp_path):
    _, _, autopilot, pending, _ = _reset_openclaw_state(monkeypatch, tmp_path)
    monkeypatch.delenv("JARVIS_OPENCLAW_INBOUND_SECRET", raising=False)
    autopilot.create_rule(
        "whatsapp",
        "canonical-a",
        "ask_before_send",
        {"type": "all_messages"},
        {"instruction": "Responder que estoy ocupado.", "forbidden_topics": [], "max_messages_per_hour": 3},
        kind="user",
        display_target="Adrian",
    )
    client = TestClient(server.app)

    response = client.post("/api/openclaw/inbound", json={
        "channel": "whatsapp",
        "kind": "user",
        "target": "canonical-a",
        "display_target": "Adrian",
        "text": "hola",
    })

    body = response.json()
    assert body["matched"] is True
    assert body["mode"] == "ask_before_send"
    assert body["pending_action_id"]
    assert pending.get_action(body["pending_action_id"])["action_type"] == "send_message"


def test_inbound_creates_unknown_contact(monkeypatch, tmp_path):
    _, _, _, _, targets = _reset_openclaw_state(monkeypatch, tmp_path)
    monkeypatch.delenv("JARVIS_OPENCLAW_INBOUND_SECRET", raising=False)
    client = TestClient(server.app)

    response = client.post("/api/openclaw/inbound", json={
        "channel": "whatsapp",
        "kind": "user",
        "target": "+34722129717",
        "display_target": "Laura",
        "sender": {"id": "+34722129717", "name": "Laura"},
        "text": "hola",
    })

    assert response.json()["success"] is True
    target = targets.find_by_canonical_target("whatsapp", "+34722129717")
    assert target["display_name"] == "Laura"
    assert target["source"] == "inbound"


def test_inbound_group_creates_manual_target(monkeypatch, tmp_path):
    _, _, _, _, targets = _reset_openclaw_state(monkeypatch, tmp_path)
    monkeypatch.delenv("JARVIS_OPENCLAW_INBOUND_SECRET", raising=False)
    client = TestClient(server.app)

    response = client.post("/api/openclaw/inbound", json={
        "channel": "whatsapp",
        "kind": "group",
        "target": "120363000000000000@g.us",
        "display_target": "Grupo TFG",
        "text": "hola grupo",
    })

    assert response.json()["success"] is True
    assert targets.find_by_canonical_target("whatsapp", "120363000000000000@g.us")["display_name"] == "Grupo TFG"
