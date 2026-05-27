from openclaw_targets_manager import OpenClawTargetsManager


def test_create_and_list_target(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")

    target = manager.add_target(
        channel="whatsapp",
        kind="group",
        display_name="Grupo TFG",
        raw_target="Grupo TFG",
    )

    assert target["id"]
    assert target["channel"] == "whatsapp"
    assert target["kind"] == "group"
    assert target["resolved"] is False
    assert manager.list_targets()[0]["display_name"] == "Grupo TFG"
    assert target["aliases"] == []
    assert target["favorite"] is False


def test_avoids_duplicates_by_channel_kind_and_names(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")

    first = manager.add_target("whatsapp", "user", "Adrian", "+34625941034")
    second = manager.add_target("whatsapp", "user", "Adrian", "+34625941034", canonical_target="+34625941034", resolved=True)

    targets = manager.list_targets()
    assert len(targets) == 1
    assert second["id"] == first["id"]
    assert targets[0]["canonical_target"] == "+34625941034"
    assert targets[0]["resolved"] is True


def test_update_mark_allowed_and_find(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")
    target = manager.add_target("whatsapp", "auto", "Carlos", "Carlos")

    updated = manager.update_target(target["id"], canonical_target="34600000000", resolved=True)
    allowed = manager.mark_allowed(target["id"])

    assert updated["canonical_target"] == "34600000000"
    assert allowed["allowed"] is True
    assert manager.find_by_display_name("whatsapp", "carlos")["id"] == target["id"]
    assert manager.find_by_canonical_target("whatsapp", "34600000000")["id"] == target["id"]


def test_aliases_relationship_and_best_match(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")
    target = manager.add_target(
        "whatsapp",
        "user",
        "Laura",
        "+34722129717",
        canonical_target="+34722129717",
        aliases=["mi novia", "Laura"],
        favorite=True,
        relationship="novia",
    )

    manager.add_alias(target["id"], "cariño")
    manager.add_alias(target["id"], "mi novia")
    updated = manager.remove_alias(target["id"], "Laura")

    assert updated["favorite"] is True
    assert "cariño" in updated["aliases"]
    assert "Laura" not in updated["aliases"]
    assert manager.find_by_alias("whatsapp", "mi novia")["id"] == target["id"]
    assert manager.find_best_match("whatsapp", "novia")["canonical_target"] == "+34722129717"


def test_whatsapp_can_send_with_canonical_without_resolved(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")
    target = manager.add_target(
        "whatsapp",
        "user",
        "Laura",
        "+34722129717",
        canonical_target="+34722129717",
        resolved=False,
    )

    assert target["resolved"] is False
    assert manager.find_best_match("whatsapp", "Laura")["canonical_target"] == "+34722129717"


def test_upsert_contact_and_inbound_source(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")

    target = manager.upsert_contact(
        "whatsapp",
        "Laura",
        "+34722129717",
        aliases=["mi novia"],
        relationship="novia",
        favorite=True,
        source="contacts_import",
    )
    inbound = manager.upsert_from_inbound({
        "channel": "whatsapp",
        "kind": "user",
        "target": "+34722129717",
        "display_target": "Laura",
        "sender_name": "Laura",
    })

    assert inbound["id"] == target["id"]
    assert manager.find_best_match("whatsapp", "MI NÓVIA")["id"] == target["id"]
    assert len(manager.list_targets()) == 1


def test_delete_target(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")
    target = manager.add_target("whatsapp", "group", "Grupo TFG", "Grupo TFG")

    deleted = manager.delete_target(target["id"])

    assert deleted["id"] == target["id"]
    assert manager.get_target(target["id"]) is None
    assert manager.list_targets() == []
