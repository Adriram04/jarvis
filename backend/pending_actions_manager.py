import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PendingActionsManager:
    """Stores OpenClaw actions waiting for explicit user confirmation."""

    def __init__(self, storage_path=None):
        base_dir = Path(__file__).resolve().parent
        self.storage_path = Path(storage_path) if storage_path else base_dir / "demo_state" / "pending_actions.json"
        self._lock = Lock()
        self._actions = []
        self._load()

    def create_pending_action(self, action_type, payload, human_summary):
        action = {
            "id": str(uuid.uuid4()),
            "action_type": str(action_type or "").strip(),
            "payload": deepcopy(payload or {}),
            "human_summary": str(human_summary or "").strip(),
            "status": "pending",
            "created_at": _now_iso(),
            "executed_at": None,
            "result": None,
        }
        with self._lock:
            self._actions.append(action)
            self._save()
        return deepcopy(action)

    def get_pending_actions(self):
        with self._lock:
            return deepcopy([a for a in self._actions if a.get("status") == "pending"])

    def get_action(self, action_id):
        with self._lock:
            action = self._find_action(action_id)
            return deepcopy(action) if action else None

    def confirm_action(self, action_id):
        with self._lock:
            action = self._find_action(action_id)
            if not action:
                return None
            if action.get("status") == "pending":
                action["status"] = "confirmed"
                self._save()
            return deepcopy(action)

    def cancel_action(self, action_id):
        with self._lock:
            action = self._find_action(action_id)
            if not action:
                return None
            if action.get("status") in {"pending", "confirmed"}:
                action["status"] = "cancelled"
                self._save()
            return deepcopy(action)

    def mark_executed(self, action_id, result):
        with self._lock:
            action = self._find_action(action_id)
            if not action:
                return None
            action["status"] = "executed"
            action["executed_at"] = _now_iso()
            action["result"] = deepcopy(result)
            self._save()
            return deepcopy(action)

    def _find_action(self, action_id):
        for action in self._actions:
            if action.get("id") == action_id:
                return action
        return None

    def _load(self):
        if not self.storage_path.exists():
            self._save()
            return
        try:
            loaded = json.loads(self.storage_path.read_text(encoding="utf-8"))
            self._actions = loaded if isinstance(loaded, list) else []
        except Exception:
            self._actions = []
            self._save()

    def _save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(self._actions, indent=2, ensure_ascii=False), encoding="utf-8")


pending_actions_manager = PendingActionsManager()


def create_pending_action(action_type, payload, human_summary):
    return pending_actions_manager.create_pending_action(action_type, payload, human_summary)


def get_pending_actions():
    return pending_actions_manager.get_pending_actions()


def get_action(action_id):
    return pending_actions_manager.get_action(action_id)


def confirm_action(action_id):
    return pending_actions_manager.confirm_action(action_id)


def cancel_action(action_id):
    return pending_actions_manager.cancel_action(action_id)


def mark_executed(action_id, result):
    return pending_actions_manager.mark_executed(action_id, result)

