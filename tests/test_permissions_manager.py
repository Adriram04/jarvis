from permissions_manager import PermissionsManager


def test_safe_actions():
    manager = PermissionsManager()

    assert manager.classify("read_conversation") == "safe"
    assert manager.classify("search_email") == "safe"
    assert manager.requires_confirmation("draft_email") is False


def test_confirmation_required_actions():
    manager = PermissionsManager()

    assert manager.classify("send_message") == "confirmation_required"
    assert manager.classify("create_calendar_event") == "confirmation_required"
    assert manager.requires_confirmation("publish_social_post") is True


def test_forbidden_actions():
    manager = PermissionsManager()

    assert manager.classify("mass_message") == "forbidden"
    assert manager.is_forbidden("auto_reply_everywhere") is True
    assert "blocked" in manager.explain("execute_shell")


def test_unknown_actions_are_conservative():
    manager = PermissionsManager()

    assert manager.classify("new_external_mutation") == "confirmation_required"


def test_autopilot_sensitive_requires_confirmation():
    manager = PermissionsManager()

    assert manager.classify("create_autopilot_rule") == "confirmation_required"
    assert manager.classify("enable_autopilot_rule") == "confirmation_required"

