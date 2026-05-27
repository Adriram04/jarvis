from openclaw_messages_manager import OpenClawMessagesManager


def test_add_and_list_new_inbound_message(tmp_path):
    manager = OpenClawMessagesManager(tmp_path / "messages.json")

    message = manager.add_message(
        channel="whatsapp",
        target="+34722129717",
        sender="+34722129717",
        message="hola",
        message_id="msg-1",
    )

    assert message["read"] is False
    assert manager.list_new_messages("whatsapp", "+34722129717")[0]["message"] == "hola"


def test_list_new_marks_read(tmp_path):
    manager = OpenClawMessagesManager(tmp_path / "messages.json")
    manager.add_message(channel="whatsapp", target="+34722129717", sender="+34722129717", message="hola")

    messages = manager.list_new_messages("whatsapp", "+34722129717", mark_read=True)

    assert len(messages) == 1
    assert manager.list_new_messages("whatsapp", "+34722129717") == []
    assert manager.get_unread_count("whatsapp", "+34722129717") == 0


def test_deduplicates_by_message_id(tmp_path):
    manager = OpenClawMessagesManager(tmp_path / "messages.json")
    first = manager.add_message(channel="whatsapp", target="+1", message="uno", message_id="same")
    second = manager.add_message(channel="whatsapp", target="+1", message="dos", message_id="same")

    assert first["id"] == second["id"]
    assert manager.list_messages(channel="whatsapp", target="+1")[0]["message"] == "dos"


def test_unread_count_filters_target(tmp_path):
    manager = OpenClawMessagesManager(tmp_path / "messages.json")
    manager.add_message(channel="whatsapp", target="+1", message="uno")
    manager.add_message(channel="whatsapp", target="+2", message="dos")

    assert manager.get_unread_count("whatsapp") == 2
    assert manager.get_unread_count("whatsapp", "+1") == 1
