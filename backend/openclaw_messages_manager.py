import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Lock


# Retention bounds to keep the local message store from growing without limit.
MAX_MESSAGES = 1000
MAX_RAW_CHARS = 4000


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(value):
    return str(value or "").strip()


def _norm(value):
    return _clean(value).casefold()


def _parse_timestamp(value):
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000
        return datetime.fromtimestamp(numeric, tz=timezone.utc)

    text = _clean(value)
    if not text:
        return None
    if text.isdigit():
        numeric = float(text)
        if numeric > 10_000_000_000:
            numeric /= 1000
        return datetime.fromtimestamp(numeric, tz=timezone.utc)

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class OpenClawMessagesManager:
    """Stores inbound OpenClaw messages Jarvis has actually received."""

    def __init__(self, storage_path=None):
        base_dir = Path(__file__).resolve().parent
        self.storage_path = Path(storage_path) if storage_path else base_dir / "demo_state" / "openclaw_messages.json"
        self._lock = Lock()
        self._messages = []
        self._load()

    def add_message(
        self,
        channel="whatsapp",
        target=None,
        sender=None,
        message=None,
        message_id=None,
        timestamp=None,
        kind="auto",
        display_target=None,
        sender_name=None,
        conversation_id=None,
        raw=None,
        read=False,
    ):
        normalized = {
            "id": str(uuid.uuid4()),
            "channel": _clean(channel).lower() or "whatsapp",
            "kind": _clean(kind).lower() or "auto",
            "target": _clean(target),
            "display_target": _clean(display_target),
            "sender": _clean(sender),
            "sender_name": _clean(sender_name),
            "message": _clean(message),
            "message_id": _clean(message_id),
            "conversation_id": _clean(conversation_id),
            "timestamp": _clean(timestamp) or _now_iso(),
            "read": bool(read),
            "raw": self._trim_raw(raw),
            "created_at": _now_iso(),
        }

        with self._lock:
            duplicate = self._find_duplicate(normalized)
            if duplicate:
                duplicate.update({key: value for key, value in normalized.items() if key not in {"id", "created_at"} and value not in ("", None)})
                self._save()
                return deepcopy(duplicate)
            self._messages.append(normalized)
            self._save()
            return deepcopy(normalized)

    def list_messages(self, channel=None, target=None, unread_only=False, limit=50):
        channel_norm = _norm(channel)
        target_norm = _norm(target)
        limit = max(0, int(limit or 50))
        with self._lock:
            messages = list(reversed(self._messages))
            if channel_norm:
                messages = [item for item in messages if _norm(item.get("channel")) == channel_norm]
            if target_norm:
                messages = [
                    item for item in messages
                    if _norm(item.get("target")) == target_norm or _norm(item.get("sender")) == target_norm
                ]
            if unread_only:
                messages = [item for item in messages if not item.get("read")]
            return deepcopy(messages[:limit])

    def list_recent_messages(self, channel=None, target=None, minutes=5, limit=50, mark_read=False):
        channel_norm = _norm(channel)
        target_norm = _norm(target)
        limit = max(0, int(limit or 50))
        try:
            minutes = max(1, int(minutes or 5))
        except Exception:
            minutes = 5
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

        with self._lock:
            messages = list(reversed(self._messages))
            if channel_norm:
                messages = [item for item in messages if _norm(item.get("channel")) == channel_norm]
            if target_norm:
                messages = [
                    item for item in messages
                    if _norm(item.get("target")) == target_norm
                    or _norm(item.get("sender")) == target_norm
                    or _norm(item.get("conversation_id")) == target_norm
                ]
            messages = [
                item for item in messages
                if (_parse_timestamp(item.get("timestamp")) or _parse_timestamp(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
            ]
            selected = messages[:limit]
            if mark_read:
                ids = {message["id"] for message in selected}
                changed = False
                for message in self._messages:
                    if message.get("id") in ids and not message.get("read"):
                        message["read"] = True
                        changed = True
                if changed:
                    self._save()
            return deepcopy(selected)

    def list_new_messages(self, channel=None, target=None, limit=50, mark_read=False):
        messages = self.list_messages(channel=channel, target=target, unread_only=True, limit=limit)
        if mark_read:
            self.mark_read([message["id"] for message in messages])
        return messages

    def mark_read(self, message_ids=None, channel=None, target=None):
        ids = {str(item) for item in (message_ids or [])}
        channel_norm = _norm(channel)
        target_norm = _norm(target)
        changed = []
        with self._lock:
            for message in self._messages:
                id_match = not ids or message.get("id") in ids
                channel_match = not channel_norm or _norm(message.get("channel")) == channel_norm
                target_match = not target_norm or _norm(message.get("target")) == target_norm or _norm(message.get("sender")) == target_norm
                if id_match and channel_match and target_match and not message.get("read"):
                    message["read"] = True
                    changed.append(deepcopy(message))
            if changed:
                self._save()
        return changed

    def get_unread_count(self, channel=None, target=None):
        return len(self.list_messages(channel=channel, target=target, unread_only=True, limit=10_000))

    def clear_messages(self):
        with self._lock:
            self._messages = []
            self._save()
        return True

    def _find_duplicate(self, message):
        message_id = _norm(message.get("message_id"))
        if not message_id:
            return None
        for existing in self._messages:
            if _norm(existing.get("channel")) == _norm(message.get("channel")) and _norm(existing.get("message_id")) == message_id:
                return existing
        return None

    def _trim_raw(self, raw):
        """Keep ``raw`` payloads bounded so the message store cannot grow
        without limit. Small payloads are preserved; large ones are replaced
        by a truncated marker."""
        if not raw:
            return {}
        try:
            text = json.dumps(raw, ensure_ascii=False)
        except Exception:
            return {"_unserializable": True}
        if len(text) <= MAX_RAW_CHARS:
            return deepcopy(raw)
        return {"_truncated": True, "_size": len(text), "_preview": text[:MAX_RAW_CHARS]}

    def _load(self):
        if not self.storage_path.exists():
            self._save()
            return
        try:
            loaded = json.loads(self.storage_path.read_text(encoding="utf-8"))
            self._messages = loaded if isinstance(loaded, list) else []
        except Exception:
            self._messages = []
            self._save()

    def _save(self):
        if len(self._messages) > MAX_MESSAGES:
            self._messages = self._messages[-MAX_MESSAGES:]
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(self._messages, indent=2, ensure_ascii=False), encoding="utf-8")


openclaw_messages_manager = OpenClawMessagesManager()


def add_message(**kwargs):
    return openclaw_messages_manager.add_message(**kwargs)


def list_messages(channel=None, target=None, unread_only=False, limit=50):
    return openclaw_messages_manager.list_messages(channel=channel, target=target, unread_only=unread_only, limit=limit)


def list_new_messages(channel=None, target=None, limit=50, mark_read=False):
    return openclaw_messages_manager.list_new_messages(channel=channel, target=target, limit=limit, mark_read=mark_read)


def list_recent_messages(channel=None, target=None, minutes=5, limit=50, mark_read=False):
    return openclaw_messages_manager.list_recent_messages(
        channel=channel,
        target=target,
        minutes=minutes,
        limit=limit,
        mark_read=mark_read,
    )


def mark_read(message_ids=None, channel=None, target=None):
    return openclaw_messages_manager.mark_read(message_ids=message_ids, channel=channel, target=target)


def get_unread_count(channel=None, target=None):
    return openclaw_messages_manager.get_unread_count(channel=channel, target=target)


def clear_messages():
    return openclaw_messages_manager.clear_messages()
