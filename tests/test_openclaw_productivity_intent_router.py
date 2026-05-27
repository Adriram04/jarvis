from openclaw_productivity_intent_router import (
    PRODUCTIVITY_DRAFTS,
    route_openclaw_productivity_voice_intent,
)
from pending_actions_manager import PendingActionsManager


def _pending(tmp_path):
    PRODUCTIVITY_DRAFTS.clear()
    return PendingActionsManager(tmp_path / "pending.json")


def test_calendar_voice_intent_creates_confirmed_pending_action(tmp_path):
    pending = _pending(tmp_path)

    result = route_openclaw_productivity_voice_intent(
        "crea una tarea en el calendario manana a las 17 de llamar a Lucas",
        pending,
    )

    action = pending.get_pending_actions()[0]
    assert result["handled"] is True
    assert result["mode"] == "confirmation_required"
    assert action["action_type"] == "create_calendar_event"
    assert action["payload"]["title"] == "llamar a lucas"
    assert "T17:00:00" in action["payload"]["start"]


def test_calendar_missing_datetime_keeps_short_draft(tmp_path):
    pending = _pending(tmp_path)

    first = route_openclaw_productivity_voice_intent("crea una tarea en el calendario de llamar a Lucas", pending)
    second = route_openclaw_productivity_voice_intent("manana a las 18", pending)

    assert first["mode"] == "missing_datetime"
    assert second["mode"] == "confirmation_required"
    assert pending.get_pending_actions()[0]["action_type"] == "create_calendar_event"


def test_linkedin_publish_creates_pending_action(tmp_path):
    pending = _pending(tmp_path)

    result = route_openclaw_productivity_voice_intent(
        "publica en LinkedIn que diga Jarvis ya puede publicar desde voz",
        pending,
    )

    action = pending.get_pending_actions()[0]
    assert result["handled"] is True
    assert result["mode"] == "confirmation_required"
    assert action["action_type"] == "publish_social_post"
    assert action["payload"]["platform"] == "linkedin"
    assert action["payload"]["content"] == "jarvis ya puede publicar desde voz"


def test_linkedin_prepare_is_safe_draft(tmp_path):
    pending = _pending(tmp_path)

    result = route_openclaw_productivity_voice_intent(
        "prepara en LinkedIn que diga demo de Jarvis",
        pending,
    )

    assert result["handled"] is True
    assert result["mode"] == "safe"
    assert pending.get_pending_actions() == []
