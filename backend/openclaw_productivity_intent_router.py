import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


PRODUCTIVITY_DRAFTS = {}
DEFAULT_DRAFT_TIMEOUT_SECONDS = 60
LOCAL_TIMEZONE = ZoneInfo("Europe/Madrid")


def _strip_accents(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_spoken_text(text):
    text = _strip_accents(text).casefold()
    text = text.replace("¿", " ").replace("?", " ").replace("¡", " ").replace("!", " ")
    text = re.sub(r"[\"'`´“”‘’]", " ", text)
    text = re.sub(r"[;()\[\]{}]", " ", text)
    text = re.sub(r"\s*:\s*", ": ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    for prefix in ("oye jarvis", "jarvis", "por favor", "puedes", "podrias", "quiero que"):
        if text == prefix:
            return ""
        if text.startswith(f"{prefix} "):
            text = text[len(prefix):].strip()
    return re.sub(r"\s+", " ", text).strip(" .")


def _result(handled, success, response, mode=None, data=None, pending_action=None):
    return {
        "handled": bool(handled),
        "success": bool(success),
        "response": response,
        "mode": mode,
        "data": data or {},
        "pending_action": pending_action,
    }


def _now():
    return datetime.now(LOCAL_TIMEZONE)


def _expire_draft(key):
    draft = PRODUCTIVITY_DRAFTS.get(key)
    if not draft:
        return None
    if (_now() - draft["created_at"]).total_seconds() > DEFAULT_DRAFT_TIMEOUT_SECONDS:
        PRODUCTIVITY_DRAFTS.pop(key, None)
        return None
    return draft


def _set_draft(key, draft):
    PRODUCTIVITY_DRAFTS[key] = {**draft, "created_at": _now()}


def _clear_draft(key):
    PRODUCTIVITY_DRAFTS.pop(key, None)


def _extract_after_markers(text, markers):
    for marker in markers:
        index = text.find(marker)
        if index >= 0:
            value = text[index + len(marker):].strip(" .,:")
            if value:
                return value
    return ""


def _parse_time(text):
    match = re.search(r"\ba\s+las\s+(\d{1,2})(?::(\d{2}))?\b", text)
    if not match:
        match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(?:h|horas)\b", text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    tail = text[match.end(): match.end() + 16]
    if "media" in tail:
        minute = 30
    elif "cuarto" in tail:
        minute = 15

    if "tarde" in text and 1 <= hour <= 11:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _parse_date(text):
    base = _now()
    if "pasado manana" in text:
        return base + timedelta(days=2)
    if "manana" in text:
        return base + timedelta(days=1)
    if "hoy" in text:
        return base

    weekday_names = {
        "lunes": 0,
        "martes": 1,
        "miercoles": 2,
        "jueves": 3,
        "viernes": 4,
        "sabado": 5,
        "domingo": 6,
    }
    for name, weekday in weekday_names.items():
        if name in text:
            days = (weekday - base.weekday()) % 7
            if days == 0:
                days = 7
            return base + timedelta(days=days)
    return None


def _calendar_payload_from_text(text):
    normalized = normalize_spoken_text(text)
    title = _extract_after_markers(
        normalized,
        (
            "tarea de",
            "evento de",
            "reunion de",
            "recordatorio de",
            "para",
            "que diga",
            "llamada con",
        ),
    )
    if not title:
        trailing = re.search(r"\bde\s+(.+)$", normalized)
        if trailing:
            title = trailing.group(1).strip(" .,:")
    if not title:
        title = re.sub(r"\b(crea|anade|agrega|pon|apunta|programa)\b", "", normalized).strip()
        title = re.sub(r"\b(una|un|el|la|en|mi|calendario|agenda|tarea|evento|reunion|recordatorio)\b", " ", title)
        title = re.sub(r"\s+", " ", title).strip(" .,:")
    title = re.sub(r"\b(pasado manana|manana|hoy|lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b", " ", title)
    title = re.sub(r"\ba\s+las\s+\d{1,2}(?::\d{2})?(?:\s+y\s+(?:media|cuarto))?", " ", title)
    title = re.sub(r"\b\d{1,2}(?::\d{2})?\s*(?:h|horas)\b", " ", title)
    title = re.sub(r"^\s*(?:de|para)\s+", "", title)
    title = re.sub(r"\s+", " ", title).strip(" .,:")

    date_part = _parse_date(normalized)
    time_part = _parse_time(normalized)
    if not date_part or not time_part:
        return None, "missing_datetime"

    hour, minute = time_part
    start = date_part.replace(hour=hour, minute=minute, second=0, microsecond=0)
    duration_minutes = 30 if "tarea" in normalized or "recordatorio" in normalized else 60
    end = start + timedelta(minutes=duration_minutes)
    return {
        "provider": "calendar",
        "title": title or "Tarea",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "time_zone": "Europe/Madrid",
        "natural_language": text,
        "source": "jarvis_voice",
    }, None


def _calendar_pending_response(text, pending_manager):
    payload, missing = _calendar_payload_from_text(text)
    if missing == "missing_datetime":
        _set_draft("calendar", {"text": text})
        return _result(
            True,
            True,
            "Claro. Dime fecha y hora para ponerlo en el calendario.",
            mode="missing_datetime",
        )

    pending = pending_manager.create_pending_action(
        "create_calendar_event",
        payload,
        f"Crear evento en calendario: {payload['title']} ({payload['start']})",
    )
    return _result(
        True,
        True,
        f"He preparado la tarea de calendario \"{payload['title']}\" para {payload['start']}. Confírmalo para crearla.",
        mode="confirmation_required",
        data={"pending_action": pending, "payload": payload},
        pending_action=pending,
    )


def _linkedin_content(text):
    normalized = normalize_spoken_text(text)
    return _extract_after_markers(
        normalized,
        (
            "en linkedin que diga",
            "en linkedin diciendo",
            "linkedin que diga",
            "linkedin diciendo",
            "publica",
            "postea",
            "sube",
            "pon",
            ":",
        ),
    )


def _linkedin_pending_response(text, pending_manager):
    normalized = normalize_spoken_text(text)
    content = _linkedin_content(text)
    if not content:
        _set_draft("linkedin", {"text": text})
        return _result(
            True,
            True,
            "De acuerdo. Dime el texto que quieres publicar en LinkedIn.",
            mode="missing_content",
        )

    action_type = "publish_social_post"
    if "programa" in normalized or "agenda" in normalized:
        action_type = "schedule_social_post"
    elif "prepara" in normalized or "redacta" in normalized:
        action_type = "prepare_social_post"

    payload = {
        "platform": "linkedin",
        "content": content,
        "visibility": "PUBLIC",
        "natural_language": text,
        "source": "jarvis_voice",
    }

    if action_type == "prepare_social_post":
        return _result(
            True,
            True,
            f"Borrador para LinkedIn: {content}",
            mode="safe",
            data={"payload": payload},
        )

    pending = pending_manager.create_pending_action(
        action_type,
        payload,
        f"Publicar en LinkedIn: {content}",
    )
    return _result(
        True,
        True,
        f"He preparado la publicación de LinkedIn: \"{content}\". Confírmalo para publicarla.",
        mode="confirmation_required",
        data={"pending_action": pending, "payload": payload},
        pending_action=pending,
    )


def route_openclaw_productivity_voice_intent(transcript, pending_manager, session_id="audio_loop"):
    normalized = normalize_spoken_text(transcript)
    if not normalized:
        return _result(False, False, "", mode="ignored")

    linkedin_draft = _expire_draft("linkedin")
    if linkedin_draft and "linkedin" not in normalized:
        text = f"{linkedin_draft.get('text', '')} que diga {transcript}"
        _clear_draft("linkedin")
        return _linkedin_pending_response(text, pending_manager)

    calendar_draft = _expire_draft("calendar")
    if calendar_draft and not any(word in normalized for word in ("whatsapp", "linkedin")):
        text = f"{calendar_draft.get('text', '')} {transcript}"
        _clear_draft("calendar")
        return _calendar_pending_response(text, pending_manager)

    if "linkedin" in normalized and any(word in normalized for word in ("publica", "postea", "sube", "pon", "prepara", "redacta", "programa")):
        return _linkedin_pending_response(transcript, pending_manager)

    calendar_words = ("calendario", "agenda", "evento", "reunion", "recordatorio", "tarea")
    calendar_actions = ("crea", "anade", "agrega", "pon", "apunta", "programa")
    if any(word in normalized for word in calendar_words) and any(word in normalized for word in calendar_actions):
        return _calendar_pending_response(transcript, pending_manager)

    return _result(False, False, "", mode="ignored")
