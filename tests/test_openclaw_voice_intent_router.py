import pytest

from openclaw_messages_manager import OpenClawMessagesManager
from openclaw_targets_manager import OpenClawTargetsManager
from openclaw_voice_intent_router import (
    pending_whatsapp_drafts,
    route_openclaw_voice_intent,
    semantic_parse_whatsapp_intent,
)
from pending_actions_manager import PendingActionsManager


def _managers(tmp_path):
    pending_whatsapp_drafts.clear()
    targets = OpenClawTargetsManager(tmp_path / "targets.json")
    messages = OpenClawMessagesManager(tmp_path / "messages.json")
    pending = PendingActionsManager(tmp_path / "pending.json")
    return targets, messages, pending


def _seed_contacts(targets):
    laura = targets.add_target(
        "whatsapp",
        "user",
        "Laura",
        "+34722129717",
        canonical_target="+34722129717",
        aliases=["Laura", "mi novia", "novia"],
        relationship="novia",
        favorite=True,
        allowed=True,
    )
    mama = targets.add_target(
        "whatsapp",
        "user",
        "Mamá",
        "+34611111111",
        canonical_target="+34611111111",
        aliases=["mama", "mamá", "mi madre", "madre"],
        relationship="madre",
        favorite=True,
        allowed=True,
    )
    carlos = targets.add_target(
        "whatsapp",
        "user",
        "Carlos",
        "+34622222222",
        canonical_target="+34622222222",
        aliases=["Carlos"],
        allowed=True,
    )
    return laura, mama, carlos


@pytest.mark.parametrize(
    ("phrase", "target", "message"),
    [
        ("mándale un whatsapp a mi novia que diga hola", "Laura", "hola"),
        ("manda un mensaje a Laura diciendo hola", "Laura", "hola"),
        ("dile a mi novia llego en diez minutos", "Laura", "llego en diez minutos"),
        ("dile a mi novia que llego en diez minutos", "Laura", "llego en diez minutos"),
        ("avísale a mi novia que llego tarde", "Laura", "llego tarde"),
        ("avisale a Laura que salgo ya", "Laura", "salgo ya"),
        ("escríbele a Laura que estoy saliendo", "Laura", "estoy saliendo"),
        ("ponle a Laura que voy para allá", "Laura", "voy para alla"),
        ("manda a Laura por WhatsApp que llego en 10", "Laura", "llego en 10"),
        ("envíale esto a mi novia: llego tarde", "Laura", "llego tarde"),
        ("a mi novia dile que salgo ya", "Laura", "salgo ya"),
        ("Laura, dile que voy tarde", "Laura", "voy tarde"),
        ("pásale a mamá que ya estoy llegando", "Mamá", "ya estoy llegando"),
        ("coméntale a Carlos que mañana no puedo", "Carlos", "manana no puedo"),
    ],
)
def test_natural_whatsapp_send_phrases_create_pending_action(tmp_path, phrase, target, message):
    targets, messages, pending = _managers(tmp_path)
    _seed_contacts(targets)

    result = route_openclaw_voice_intent(phrase, targets, messages, pending, session_id=phrase)

    assert result["handled"] is True
    assert result["success"] is True
    assert result["mode"] == "confirmation_required"
    assert "Confirmalo" in result["response"]
    action = pending.get_pending_actions()[0]
    assert action["action_type"] == "send_message"
    assert action["payload"]["display_target"] == target
    assert action["payload"]["message"] == message


@pytest.mark.parametrize(
    "phrase",
    [
        "dime mensajes nuevos de mi novia",
        "qué ha dicho mi novia",
        "qué me ha dicho Laura",
        "tengo mensajes nuevos de mamá",
    ],
)
def test_read_new_messages_uses_local_inbound_store(tmp_path, phrase):
    targets, messages, pending = _managers(tmp_path)
    laura, mama, _ = _seed_contacts(targets)
    target = mama if "mam" in phrase else laura
    messages.add_message(
        channel="whatsapp",
        target=target["canonical_target"],
        sender=target["canonical_target"],
        message="mensaje guardado",
    )

    result = route_openclaw_voice_intent(phrase, targets, messages, pending, session_id=phrase)

    assert result["handled"] is True
    assert result["mode"] == "safe"
    assert "mensaje guardado" in result["response"]
    assert messages.list_new_messages("whatsapp", target["canonical_target"]) == []


@pytest.mark.parametrize("phrase", ["Me ha llegado algun mensaje jarvis?", "Quiero saber si me ha llegado algo"])
def test_read_new_messages_without_contact_reads_all_local_inbound(tmp_path, phrase):
    targets, messages, pending = _managers(tmp_path)
    _seed_contacts(targets)
    messages.add_message(
        channel="whatsapp",
        target="+34722129717",
        display_target="Laura",
        sender="+34722129717",
        sender_name="Laura",
        message="ya estoy aqui",
    )

    result = route_openclaw_voice_intent(phrase, targets, messages, pending, session_id=phrase)

    assert result["handled"] is True
    assert result["mode"] == "safe"
    assert "ya estoy aqui" in result["response"]
    assert pending.get_pending_actions() == []


def test_read_new_messages_without_contact_does_not_create_send_draft(tmp_path):
    targets, messages, pending = _managers(tmp_path)
    _seed_contacts(targets)

    result = route_openclaw_voice_intent("me ha llegado algun mensaje jarvis", targets, messages, pending, session_id="read-all")

    assert result["handled"] is True
    assert result["mode"] == "safe"
    assert "No tienes mensajes recientes" in result["response"]
    assert pending_whatsapp_drafts == {}


def test_mi_pareja_matches_romantic_contact_with_heart_name(tmp_path):
    targets, messages, pending = _managers(tmp_path)
    targets.add_target(
        "whatsapp",
        "user",
        "Mi Niñaaa❤❤❤",
        "+34722129717",
        canonical_target="+34722129717",
        allowed=True,
        aliases=["Mi niña"],
    )

    result = route_openclaw_voice_intent("avísale a mi pareja que llego tarde", targets, messages, pending)

    assert result["handled"] is True
    assert result["mode"] == "confirmation_required"
    assert pending.get_pending_actions()[0]["payload"]["display_target"] == "Mi Niñaaa❤❤❤"


def test_missing_message_creates_short_draft_and_next_turn_completes(tmp_path):
    targets, messages, pending = _managers(tmp_path)
    _seed_contacts(targets)

    first = route_openclaw_voice_intent("mándale un whatsapp a mi novia", targets, messages, pending, session_id="s1")
    second = route_openclaw_voice_intent("que llego tarde", targets, messages, pending, session_id="s1")

    assert first["mode"] == "missing_message"
    assert "Que mensaje" in first["response"]
    assert second["mode"] == "confirmation_required"
    assert pending.get_pending_actions()[0]["payload"]["message"] == "llego tarde"


def test_missing_recipient_creates_short_draft_and_next_turn_completes(tmp_path):
    targets, messages, pending = _managers(tmp_path)
    _seed_contacts(targets)

    first = route_openclaw_voice_intent("manda que llego tarde", targets, messages, pending, session_id="s2")
    second = route_openclaw_voice_intent("a mi novia", targets, messages, pending, session_id="s2")

    assert first["mode"] == "missing_recipient"
    assert "A quien" in first["response"]
    assert second["mode"] == "confirmation_required"
    assert pending.get_pending_actions()[0]["payload"]["display_target"] == "Laura"
    assert pending.get_pending_actions()[0]["payload"]["message"] == "llego tarde"


def test_bare_send_word_does_not_create_sticky_whatsapp_draft(tmp_path):
    targets, messages, pending = _managers(tmp_path)
    _seed_contacts(targets)

    result = route_openclaw_voice_intent("manda", targets, messages, pending, session_id="noise")

    assert result["handled"] is False
    assert pending_whatsapp_drafts == {}
    assert pending.get_pending_actions() == []


def test_unknown_recipient_answer_clears_missing_recipient_draft(tmp_path):
    targets, messages, pending = _managers(tmp_path)
    _seed_contacts(targets)

    first = route_openclaw_voice_intent("manda que llego tarde", targets, messages, pending, session_id="s3")
    second = route_openclaw_voice_intent("Lucas", targets, messages, pending, session_id="s3")
    third = route_openclaw_voice_intent("hola jarvis", targets, messages, pending, session_id="s3")

    assert first["mode"] == "missing_recipient"
    assert second["mode"] == "not_found"
    assert third["handled"] is False
    assert pending_whatsapp_drafts == {}
    assert pending.get_pending_actions() == []


def test_duplicate_completed_send_reuses_existing_pending_action(tmp_path):
    targets, messages, pending = _managers(tmp_path)
    _seed_contacts(targets)

    first = route_openclaw_voice_intent("dile a Laura que hola", targets, messages, pending, session_id="s4")
    second = route_openclaw_voice_intent("dile a Laura que hola", targets, messages, pending, session_id="s5")

    actions = pending.get_pending_actions()
    assert len(actions) == 1
    assert first["pending_action"]["id"] == second["pending_action"]["id"] == actions[0]["id"]


def test_unknown_named_recipient_returns_useful_error(tmp_path):
    targets, messages, pending = _managers(tmp_path)

    result = route_openclaw_voice_intent("manda un mensaje a Laura diciendo hola", targets, messages, pending)

    assert result["handled"] is True
    assert result["success"] is False
    assert result["mode"] == "not_found"
    assert "Importa tus contactos" in result["response"]


def test_ambiguous_contact_asks_for_disambiguation(tmp_path):
    _, messages, pending = _managers(tmp_path)

    class AmbiguousTargets:
        def list_targets(self):
            return [
                {"id": "1", "channel": "whatsapp", "kind": "user", "display_name": "Laura casa", "canonical_target": "+341", "raw_target": "+341", "aliases": ["Laura"]},
                {"id": "2", "channel": "whatsapp", "kind": "user", "display_name": "Laura trabajo", "canonical_target": "+342", "raw_target": "+342", "aliases": ["Laura"]},
            ]

        def find_best_match(self, *_args, **_kwargs):
            return None

        def get_target(self, target_id):
            return next((target for target in self.list_targets() if target["id"] == target_id), None)

    targets = AmbiguousTargets()

    result = route_openclaw_voice_intent("dile a Laura que hola", targets, messages, pending)

    assert result["handled"] is True
    assert result["mode"] == "disambiguation_required"
    assert "Laura casa" in result["response"]
    assert "Laura trabajo" in result["response"]


def test_import_contacts_intent_is_safe(tmp_path):
    targets, messages, pending = _managers(tmp_path)

    result = route_openclaw_voice_intent("sincroniza contactos de whatsapp", targets, messages, pending)

    assert result["handled"] is True
    assert result["mode"] == "safe"


def test_semantic_parse_reports_missing_fields(tmp_path):
    targets, _, _ = _managers(tmp_path)
    _seed_contacts(targets)

    no_message = semantic_parse_whatsapp_intent("avísale a mi novia", targets)
    no_recipient = semantic_parse_whatsapp_intent("manda que llego tarde", targets)

    assert no_message["type"] == "send_whatsapp"
    assert "message" in no_message["missing"]
    assert no_recipient["type"] == "send_whatsapp"
    assert "recipient" in no_recipient["missing"]
