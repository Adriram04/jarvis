from datetime import datetime, timezone


def _first(payload, *keys):
    for key in keys:
        value = _dig(payload, key)
        if value not in (None, ""):
            return value
    return None


def _dig(payload, key):
    current = payload
    for part in str(key).split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _clean(value):
    return str(value or "").strip()


def _normalize_kind(value):
    kind = _clean(value).lower() or "auto"
    return kind if kind in {"user", "group", "auto"} else "auto"


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_openclaw_inbound(payload: dict) -> dict:
    """Map variable OpenClaw inbound event payloads to Jarvis' stable shape."""

    payload = payload or {}
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    message_obj = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    message_text_value = payload.get("message") if not isinstance(payload.get("message"), dict) else None
    chat = payload.get("chat") if isinstance(payload.get("chat"), dict) else {}
    sender_obj = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}

    merged = {
        **payload,
        "event": event,
        "message_obj": message_obj,
        "message_text_value": message_text_value,
        "chat": chat,
        "sender_obj": sender_obj,
    }

    channel = _clean(_first(merged, "channel", "event.channel")) or "whatsapp"
    kind = _normalize_kind(_first(merged, "kind", "target_kind", "conversation.kind", "chat.kind", "event.kind"))

    target = _first(
        merged,
        "canonical_target",
        "target",
        "conversation_id",
        "conversation.id",
        "chat.id",
        "message_obj.chat_id",
        "message_obj.from",
        "event.target",
    )
    display_target = _first(
        merged,
        "display_target",
        "displayTarget",
        "conversation_name",
        "conversation.name",
        "chat.name",
        "chat.title",
        "target_name",
        "event.display_target",
    )
    sender = _first(merged, "sender_id", "sender.id", "sender_obj.id", "from", "message_obj.sender", "message_obj.from")
    sender_name = _first(merged, "sender_name", "sender.name", "sender_obj.name", "push_name", "message_obj.sender_name")
    message_text = _first(merged, "text", "body", "content", "message_text", "message_text_value", "message_obj.text", "message_obj.body")
    message_id = _first(merged, "message_id", "id", "message_obj.id", "event.message_id")
    conversation_id = _first(merged, "conversation_id", "thread_id", "chat.id", "conversation.id", "event.conversation_id")
    timestamp = _first(merged, "timestamp", "created_at", "message_obj.timestamp", "event.timestamp") or _now_iso()

    if not target:
        target = conversation_id or sender
    if not display_target:
        display_target = _first(merged, "raw_target", "target") or target

    return {
        "channel": channel,
        "kind": kind,
        "target": _clean(target),
        "display_target": _clean(display_target),
        "sender": _clean(sender),
        "sender_name": _clean(sender_name),
        "message": _clean(message_text),
        "message_id": _clean(message_id),
        "conversation_id": _clean(conversation_id),
        "timestamp": _clean(timestamp),
    }
