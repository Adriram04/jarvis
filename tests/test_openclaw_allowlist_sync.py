import json

from openclaw_allowlist_sync import (
    apply_openclaw_whatsapp_allowlist,
    collect_allowed_whatsapp_targets,
    normalize_openclaw_phone,
    sync_openclaw_whatsapp_allowlist,
)
from openclaw_targets_manager import OpenClawTargetsManager


def test_normalize_openclaw_phone_matches_whatsapp_allowfrom_style():
    assert normalize_openclaw_phone("+34 722 129 717") == "34722129717"
    assert normalize_openclaw_phone("120363000000000000@g.us") is None


def test_collect_allowed_targets_splits_people_and_groups(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")
    manager.add_target(
        "whatsapp",
        "user",
        "Lucas",
        "+34722129717",
        canonical_target="+34722129717",
        allowed=True,
    )
    manager.add_target(
        "whatsapp",
        "group",
        "Grupo TFG",
        "120363000000000000@g.us",
        canonical_target="120363000000000000@g.us",
        allowed=True,
    )
    manager.add_target("whatsapp", "user", "Restringido", "+34611111111", canonical_target="+34611111111", allowed=False)

    collected = collect_allowed_whatsapp_targets(manager)

    assert collected["direct_numbers"] == ["34722129717"]
    assert collected["group_targets"] == ["120363000000000000@g.us"]
    assert collected["allowed_count"] == 2


def test_apply_config_enables_plugin_and_silences_openclaw_replies():
    targets = {
        "direct_numbers": ["34722129717"],
        "group_targets": ["120363000000000000@g.us"],
        "skipped": [],
        "allowed_count": 2,
    }

    patched = apply_openclaw_whatsapp_allowlist({"channels": {"whatsapp": {"selfChatMode": True}}}, targets)

    whatsapp = patched["channels"]["whatsapp"]
    assert whatsapp["dmPolicy"] == "allowlist"
    assert whatsapp["allowFrom"] == ["34722129717"]
    assert whatsapp["groupAllowFrom"] == ["120363000000000000@g.us"]
    assert whatsapp["groups"]["120363000000000000@g.us"]["requireMention"] is False
    plugin_entry = patched["plugins"]["entries"]["jarvis-whatsapp-forwarder"]
    assert plugin_entry["enabled"] is True
    assert plugin_entry["config"]["blockOpenClawReplies"] is True
    assert plugin_entry["hooks"]["allowConversationAccess"] is True


def test_sync_writes_openclaw_config_with_backup(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")
    manager.add_target(
        "whatsapp",
        "user",
        "Lucas",
        "+34722129717",
        canonical_target="+34722129717",
        allowed=True,
    )
    config_path = tmp_path / "openclaw.json"
    config_path.write_text(json.dumps({"channels": {"whatsapp": {"allowFrom": ["34600000000"]}}}), encoding="utf-8")

    result = sync_openclaw_whatsapp_allowlist(manager, config_path=config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    assert result["success"] is True
    assert result["changed"] is True
    assert result["backup_path"]
    assert saved["channels"]["whatsapp"]["allowFrom"] == ["34722129717"]
