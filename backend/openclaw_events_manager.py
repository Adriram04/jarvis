import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


ALLOWED_EVENT_TYPES = {
    "inbound",
    "outbound",
    "error",
    "status",
    "rule_match",
    "dry_run",
    "automation.started",
    "automation.completed",
    "automation.failed",
    "automation.waiting_for_confirmation",
    "automation.skipped_already_running",
    "automation.skipped_conditions",
}

# Retention bounds to keep the local event log from growing without limit.
MAX_EVENTS = 1000
MAX_RAW_CHARS = 4000


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(value):
    return str(value or "").strip()


class OpenClawEventsManager:
    """Persists a small event log for OpenClaw activity inside Jarvis."""

    def __init__(self, storage_path=None):
        base_dir = Path(__file__).resolve().parent
        self.storage_path = Path(storage_path) if storage_path else base_dir / "demo_state" / "openclaw_events.json"
        self._lock = Lock()
        self._events = []
        self._load()

    def add_event(
        self,
        type,
        channel="whatsapp",
        kind="auto",
        target=None,
        display_target=None,
        message=None,
        success=True,
        error=None,
        raw=None,
    ):
        event_type = _clean(type).lower()
        if event_type not in ALLOWED_EVENT_TYPES:
            event_type = "status"

        event = {
            "id": str(uuid.uuid4()),
            "type": event_type,
            "channel": _clean(channel).lower() or "whatsapp",
            "kind": _clean(kind).lower() or "auto",
            "target": _clean(target),
            "display_target": _clean(display_target),
            "message": self._trim_message(message),
            "success": bool(success),
            "error": _clean(error) or None,
            "raw": self._trim_raw(raw),
            "created_at": _now_iso(),
        }

        with self._lock:
            self._events.append(event)
            self._save()
            return deepcopy(event)

    def list_events(self, limit=100, type=None, channel=None):
        event_type = _clean(type).lower()
        channel_filter = _clean(channel).lower()
        limit = max(0, int(limit or 100))

        with self._lock:
            events = list(reversed(self._events))
            if event_type:
                events = [event for event in events if event.get("type") == event_type]
            if channel_filter:
                events = [event for event in events if event.get("channel") == channel_filter]
            return deepcopy(events[:limit])

    def clear_events(self):
        with self._lock:
            self._events = []
            self._save()
        return True

    def _trim_message(self, message, max_length=500):
        text = _clean(message)
        return text[:max_length] + ("..." if len(text) > max_length else "")

    def _trim_raw(self, raw):
        """Keep ``raw`` payloads bounded so the event log cannot grow without
        limit. Small payloads are preserved; large ones are replaced by a
        truncated marker."""
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
            self._events = loaded if isinstance(loaded, list) else []
        except Exception:
            self._events = []
            self._save()

    def _save(self):
        if len(self._events) > MAX_EVENTS:
            self._events = self._events[-MAX_EVENTS:]
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(self._events, indent=2, ensure_ascii=False), encoding="utf-8")


openclaw_events_manager = OpenClawEventsManager()


def add_event(
    type,
    channel="whatsapp",
    kind="auto",
    target=None,
    display_target=None,
    message=None,
    success=True,
    error=None,
    raw=None,
):
    return openclaw_events_manager.add_event(
        type,
        channel=channel,
        kind=kind,
        target=target,
        display_target=display_target,
        message=message,
        success=success,
        error=error,
        raw=raw,
    )


def list_events(limit=100, type=None, channel=None):
    return openclaw_events_manager.list_events(limit=limit, type=type, channel=channel)


def clear_events():
    return openclaw_events_manager.clear_events()
