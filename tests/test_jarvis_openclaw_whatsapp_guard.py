import jarvis
import time
from openclaw_targets_manager import OpenClawTargetsManager
from pending_actions_manager import PendingActionsManager


def _loop_without_init():
    return jarvis.AudioLoop.__new__(jarvis.AudioLoop)


def test_generic_whatsapp_send_tool_creates_local_pending_action(tmp_path):
    loop = _loop_without_init()
    loop.openclaw_targets_manager = OpenClawTargetsManager(tmp_path / "targets.json")
    loop.pending_actions_manager = PendingActionsManager(tmp_path / "pending.json")
    confirmations = []
    transcriptions = []
    loop.on_tool_confirmation = confirmations.append
    loop.on_transcription = transcriptions.append
    loop.openclaw_targets_manager.add_target(
        "whatsapp",
        "user",
        "Laura",
        "+34722129717",
        canonical_target="+34722129717",
        aliases=["Laura", "mi pareja"],
    )

    result = loop._blocked_whatsapp_openclaw_tool_result(
        "openclaw_send_message",
        {"channel": "whatsapp", "target": "mi pareja", "message": "hola"},
    )

    assert result["success"] is False
    assert "confirmation_required" in result["warnings"]
    assert "whatsapp_local_pending_action" in result["warnings"]
    pending = loop.pending_actions_manager.get_pending_actions()[0]
    assert pending["payload"]["canonical_target"] == "+34722129717"
    assert pending["payload"]["display_target"] == "Laura"
    assert confirmations[0]["id"] == pending["id"]
    # User-facing confirmation text is delivered via the transcription callback
    assert "Laura" in transcriptions[0]["text"]
    assert "Confirmalo" in transcriptions[0]["text"]


def test_generic_whatsapp_send_tool_does_not_duplicate_existing_pending_action(tmp_path):
    loop = _loop_without_init()
    loop.openclaw_targets_manager = OpenClawTargetsManager(tmp_path / "targets.json")
    loop.pending_actions_manager = PendingActionsManager(tmp_path / "pending.json")
    loop.on_tool_confirmation = lambda data: None
    loop.openclaw_targets_manager.add_target(
        "whatsapp",
        "user",
        "Laura",
        "+34722129717",
        canonical_target="+34722129717",
        aliases=["Laura"],
    )

    first = loop._blocked_whatsapp_openclaw_tool_result(
        "openclaw_send_message",
        {"channel": "whatsapp", "target": "Laura", "message": "hola"},
    )
    second = loop._blocked_whatsapp_openclaw_tool_result(
        "openclaw_send_message",
        {"channel": "whatsapp", "target": "Laura", "message": "hola"},
    )

    assert first["raw"]["id"] == second["raw"]["id"]
    assert len(loop.pending_actions_manager.get_pending_actions()) == 1


def test_generic_whatsapp_send_tool_reports_unknown_alias(tmp_path):
    loop = _loop_without_init()
    loop.openclaw_targets_manager = OpenClawTargetsManager(tmp_path / "targets.json")
    loop.pending_actions_manager = PendingActionsManager(tmp_path / "pending.json")

    result = loop._blocked_whatsapp_openclaw_tool_result(
        "openclaw_send_message",
        {"channel": "whatsapp", "target": "Luke", "message": "soy"},
    )

    assert result["success"] is False
    assert "No tengo guardado" in result["summary"]
    assert "whatsapp_target_not_found" in result["warnings"]


def test_generic_whatsapp_read_tool_is_blocked_locally():
    loop = _loop_without_init()

    result = loop._blocked_whatsapp_openclaw_tool_result(
        "openclaw_read_conversation",
        {"channel": "whatsapp", "target": "Laura"},
    )

    assert result["success"] is False
    assert "inbound guardados" in result["summary"]
    assert "whatsapp_read_local_only" in result["warnings"]


def test_non_whatsapp_tool_is_not_blocked():
    loop = _loop_without_init()

    result = loop._blocked_whatsapp_openclaw_tool_result(
        "openclaw_execute_action",
        {"action_type": "list_calendar_events", "payload": {}},
    )

    assert result is None


def test_input_echo_guard_ignores_transcript_while_model_audio_is_active():
    loop = _loop_without_init()
    loop._input_echo_guard_enabled = True
    loop._model_audio_active_until = time.time() + 1
    loop._recent_model_output_text = ""
    loop._recent_model_output_until = 0

    assert loop._should_ignore_input_transcript("He preparado el WhatsApp") is True


def test_input_echo_guard_ignores_recent_model_text_after_audio():
    loop = _loop_without_init()
    loop._input_echo_guard_enabled = True
    loop._model_audio_active_until = 0
    loop._recent_model_output_text = ""
    loop._recent_model_output_until = 0

    loop._remember_model_output_text("He preparado el WhatsApp para Salva. Confirmalo para enviarlo.")

    assert loop._should_ignore_input_transcript("He preparado el WhatsApp para Salva") is True
    assert loop._should_ignore_input_transcript("Confirmo") is False
