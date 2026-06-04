import automation_templates
from automation_manager import AutomationManager


def test_list_templates_returns_six_named_templates():
    templates = automation_templates.list_templates()
    ids = {item["id"] for item in templates}
    assert {
        "smart_startup",
        "daily_summary",
        "whatsapp_urgent",
        "work_mode",
        "tfg_defense_mode",
        "openwa_sync_contacts",
    }.issubset(ids)
    for item in templates:
        assert item["name"]
        assert isinstance(item["actions"], list) and item["actions"]
        assert "trigger" in item


def test_get_template_unknown_returns_none():
    assert automation_templates.get_template("nope") is None


def test_template_as_payload_strips_id_and_tags_template():
    payload = automation_templates.template_as_automation_payload("daily_summary")
    assert "id" not in payload
    assert payload["template_id"] == "daily_summary"


def test_template_can_be_created_as_automation(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    payload = automation_templates.template_as_automation_payload("whatsapp_urgent")
    automation = manager.create_automation(payload)
    assert automation["trigger"]["type"] == "whatsapp.message_received"
    assert automation["conditions"][0]["type"] == "message_contains"
    assert automation["actions"][0]["action_type"] == "notify"


def test_every_template_passes_validation(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    for template in automation_templates.list_templates():
        payload = automation_templates.template_as_automation_payload(template["id"])
        validation = manager.validate_automation_payload(payload)
        assert validation["valid"], (template["id"], validation["errors"])
