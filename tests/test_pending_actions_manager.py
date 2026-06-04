from pending_actions_manager import PendingActionsManager


def test_create_pending_action(tmp_path):
    manager = PendingActionsManager(tmp_path / "pending.json")

    action = manager.create_pending_action(
        "send_message",
        {"channel": "whatsapp", "target": "Grupo TFG"},
        "Enviar mensaje a Grupo TFG",
    )

    assert action["id"]
    assert action["status"] == "pending"
    assert manager.get_pending_actions()[0]["id"] == action["id"]


def test_confirm_action(tmp_path):
    manager = PendingActionsManager(tmp_path / "pending.json")
    action = manager.create_pending_action("send_message", {"channel": "whatsapp", "target": "+34600111222", "message": "Hola"}, "Enviar WhatsApp")

    confirmed = manager.confirm_action(action["id"])

    assert confirmed["status"] == "confirmed"
    assert manager.get_action(action["id"])["status"] == "confirmed"


def test_cancel_action(tmp_path):
    manager = PendingActionsManager(tmp_path / "pending.json")
    action = manager.create_pending_action("send_message", {}, "Enviar WhatsApp")

    cancelled = manager.cancel_action(action["id"])

    assert cancelled["status"] == "cancelled"
    assert manager.get_pending_actions() == []


def test_mark_executed(tmp_path):
    manager = PendingActionsManager(tmp_path / "pending.json")
    action = manager.create_pending_action("run_workflow", {}, "Ejecutar workflow")

    executed = manager.mark_executed(action["id"], {"success": True})

    assert executed["status"] == "executed"
    assert executed["executed_at"] is not None
    assert executed["result"]["success"] is True

def test_persistence(tmp_path):
    storage = tmp_path / "pending.json"
    manager = PendingActionsManager(storage)
    action = manager.create_pending_action("send_message", {"message": "hola"}, "Enviar mensaje")

    reloaded = PendingActionsManager(storage)

    assert reloaded.get_action(action["id"])["payload"]["message"] == "hola"

