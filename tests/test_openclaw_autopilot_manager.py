from openclaw_autopilot_manager import OpenClawAutopilotManager


def _behavior(**overrides):
    data = {
        "instruction": "Responder breve.",
        "max_messages_per_hour": 2,
        "allowed_topics": ["reunión", "demo"],
        "forbidden_topics": ["contraseñas"],
        "require_confirmation_for_first_reply": True,
    }
    data.update(overrides)
    return data


def test_create_and_list_rule(tmp_path):
    manager = OpenClawAutopilotManager(tmp_path / "rules.json")

    rule = manager.create_rule(
        "whatsapp",
        "Grupo TFG",
        "ask_before_send",
        {"type": "keywords", "keywords": ["reunión"]},
        _behavior(),
    )

    assert rule["id"]
    assert rule["enabled"] is True
    assert manager.list_rules()[0]["target"] == "Grupo TFG"


def test_enable_disable_delete_rule(tmp_path):
    manager = OpenClawAutopilotManager(tmp_path / "rules.json")
    rule = manager.create_rule("whatsapp", "Grupo TFG", "draft_only", {"type": "all_messages"}, _behavior())

    assert manager.disable_rule(rule["id"])["enabled"] is False
    assert manager.enable_rule(rule["id"])["enabled"] is True
    assert manager.delete_rule(rule["id"])["id"] == rule["id"]
    assert manager.list_rules() == []


def test_find_matching_rule_by_incoming_message(tmp_path):
    manager = OpenClawAutopilotManager(tmp_path / "rules.json")
    manager.create_rule(
        "whatsapp",
        "Grupo TFG",
        "ask_before_send",
        {"type": "keywords", "keywords": ["reunión"]},
        _behavior(),
    )

    matches = manager.find_matching_rules({
        "channel": "whatsapp",
        "target": "Grupo TFG",
        "sender": "Carlos",
        "message": "¿Cuándo es la reunión?",
    })

    assert len(matches) == 1


def test_respects_hourly_limit(tmp_path):
    manager = OpenClawAutopilotManager(tmp_path / "rules.json")
    rule = manager.create_rule(
        "whatsapp",
        "Grupo TFG",
        "auto_send_limited",
        {"type": "keywords", "keywords": ["reunión"]},
        _behavior(max_messages_per_hour=1),
    )
    incoming = {"channel": "whatsapp", "target": "Grupo TFG", "message": "reunión demo"}

    assert manager.should_auto_reply(rule, incoming) is True
    manager.register_reply(rule["id"])
    assert manager.should_auto_reply(rule, incoming) is False


def test_blocks_forbidden_topics(tmp_path):
    manager = OpenClawAutopilotManager(tmp_path / "rules.json")
    rule = manager.create_rule(
        "whatsapp",
        "Grupo TFG",
        "auto_send_limited",
        {"type": "all_messages"},
        _behavior(),
    )

    assert manager.should_auto_reply(rule, {
        "channel": "whatsapp",
        "target": "Grupo TFG",
        "message": "pásame las contraseñas",
    }) is False


def test_matches_by_canonical_target_and_kind(tmp_path):
    manager = OpenClawAutopilotManager(tmp_path / "rules.json")
    manager.create_rule(
        "whatsapp",
        "120363000000000000@g.us",
        "ask_before_send",
        {"type": "keywords", "keywords": ["reunion"]},
        _behavior(allowed_topics=[]),
        kind="group",
        display_target="Grupo TFG",
        target_id="target-1",
    )

    matches = manager.find_matching_rules({
        "channel": "whatsapp",
        "kind": "group",
        "target": "120363000000000000@g.us",
        "display_target": "Nombre visible distinto",
        "message": "reunión mañana",
    })

    assert len(matches) == 1
    assert matches[0]["display_target"] == "Grupo TFG"
    assert matches[0]["target_id"] == "target-1"


def test_does_not_match_only_by_display_name(tmp_path):
    manager = OpenClawAutopilotManager(tmp_path / "rules.json")
    manager.create_rule(
        "whatsapp",
        "canonical-a",
        "ask_before_send",
        {"type": "all_messages"},
        _behavior(allowed_topics=[]),
        kind="group",
        display_target="Grupo TFG",
    )

    matches = manager.find_matching_rules({
        "channel": "whatsapp",
        "kind": "group",
        "target": "canonical-b",
        "display_target": "Grupo TFG",
        "message": "hola",
    })

    assert matches == []


def test_keywords_are_accent_insensitive(tmp_path):
    manager = OpenClawAutopilotManager(tmp_path / "rules.json")
    manager.create_rule(
        "whatsapp",
        "canonical-a",
        "ask_before_send",
        {"type": "keywords", "keywords": ["reunion"]},
        _behavior(allowed_topics=[]),
    )

    matches = manager.find_matching_rules({
        "channel": "whatsapp",
        "target": "canonical-a",
        "message": "¿Hay reunión hoy?",
    })

    assert len(matches) == 1


def test_draft_only_never_auto_replies(tmp_path):
    manager = OpenClawAutopilotManager(tmp_path / "rules.json")
    rule = manager.create_rule(
        "whatsapp",
        "canonical-a",
        "draft_only",
        {"type": "all_messages"},
        _behavior(allowed_topics=[]),
    )

    assert manager.should_auto_reply(rule, {"channel": "whatsapp", "target": "canonical-a", "message": "hola"}) is False


def test_ask_before_send_never_auto_replies(tmp_path):
    manager = OpenClawAutopilotManager(tmp_path / "rules.json")
    rule = manager.create_rule(
        "whatsapp",
        "canonical-a",
        "ask_before_send",
        {"type": "all_messages"},
        _behavior(allowed_topics=[]),
    )

    assert manager.should_auto_reply(rule, {"channel": "whatsapp", "target": "canonical-a", "message": "hola"}) is False
