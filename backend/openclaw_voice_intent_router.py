import json
import os
import re
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone


SEND_PATTERNS = [
    re.compile(r"^(?:mandale|manda|enviale|envia)\s+(?:un\s+)?(?:whatsapp|mensaje)\s+a\s+(?P<recipient>.+?)\s+(?:que\s+diga|diciendo)\s+(?P<message>.+)$", re.IGNORECASE),
    re.compile(r"^escribele\s+a\s+(?P<recipient>.+?)\s+que\s+(?P<message>.+)$", re.IGNORECASE),
]

READ_PATTERNS = [
    re.compile(r"^(?:dime|lee|leeme|muestrame)\s+(?:los\s+)?(?:nuevos\s+)?mensajes\s+(?:nuevos\s+)?de\s+(?P<recipient>.+)$", re.IGNORECASE),
    re.compile(r"^(?:hay|tengo)\s+mensajes\s+nuevos\s+de\s+(?P<recipient>.+)$", re.IGNORECASE),
    re.compile(r"^que\s+(?:me\s+)?ha\s+dicho\s+(?P<recipient>.+)$", re.IGNORECASE),
]

LIST_ALLOWED_PATTERNS = [
    re.compile(r"^(?:a\s+quien|a\s+que\s+contactos|a\s+que\s+personas|a\s+que\s+grupos)\s+(?:puedes|puedo)\s+(?:mandar|enviar|escribir)(?:le|les)?\s+(?:whatsapps?|mensajes)(?:\s+por\s+whatsapp)?$", re.IGNORECASE),
    re.compile(r"^(?:lista|dime|muestrame)\s+(?:la\s+)?(?:allowlist|lista\s+permitida|contactos\s+permitidos|destinatarios\s+permitidos)(?:\s+de\s+whatsapp)?$", re.IGNORECASE),
    re.compile(r"^(?:quien|quienes|que\s+contactos|que\s+grupos)\s+(?:estan|tienes)\s+(?:en\s+)?(?:la\s+)?allowlist(?:\s+de\s+whatsapp)?$", re.IGNORECASE),
]

ALLOWLIST_PATTERNS = [
    re.compile(r"^(?P<action>permite|autoriza|anade|añade|agrega|mete)\s+(?:a\s+)?(?P<recipient>.+?)\s+(?:a|en)\s+(?:la\s+)?(?:allowlist|lista\s+permitida)(?:\s+de\s+whatsapp)?$", re.IGNORECASE),
    re.compile(r"^(?P<action>quita|elimina|saca|bloquea|restringe)\s+(?:a\s+)?(?P<recipient>.+?)\s+(?:de\s+)?(?:la\s+)?(?:allowlist|lista\s+permitida)(?:\s+de\s+whatsapp)?$", re.IGNORECASE),
]

IMPORT_PATTERNS = [
    re.compile(r"^(?:importa|actualiza|sincroniza)\s+(?:mis\s+)?(?:contactos|agenda)(?:\s+de\s+whatsapp)?$", re.IGNORECASE),
    re.compile(r"^(?:actualiza|sincroniza)\s+la\s+agenda\s+de\s+whatsapp$", re.IGNORECASE),
]

PREFIXES = (
    "oye jarvis",
    "jarvis",
    "por favor",
    "puedes",
    "podrias",
    "quiero que",
    "hazme el favor de",
)

SEND_MARKERS = (
    "whatsapp",
    "escrib",
    "dile",
    "di le",
    "avisa",
    "avisale",
    "manda",
    "mandale",
    "envia",
    "enviale",
    "pasale",
    "comenta",
    "comentale",
    "cuenta",
    "cuentale",
    "ponle",
)

READ_MARKERS = (
    "mensajes nuevos",
    "nuevos mensajes",
    "que ha dicho",
    "que me ha dicho",
    "ha dicho",
)

READ_ALL_MARKERS = (
    "me han enviado algun mensaje",
    "me han mandado algun mensaje",
    "me han escrito",
    "me ha escrito alguien",
    "me ha llegado algun mensaje",
    "me ha llegado un mensaje",
    "me ha llegado algo",
    "ha llegado algun mensaje",
    "ha llegado algo",
    "tengo algun mensaje",
    "tengo mensajes",
    "quiero saber si me ha llegado algo",
)

CONNECTORS_BEFORE_TARGET = (
    "a",
    "para",
)

MESSAGE_LEADERS = (
    "que diga",
    "diciendo",
    "que le diga",
    "dile que",
    "dile",
    "avisale que",
    "avisale",
    "avisa que",
    "avisa",
    "escribele que",
    "escribele",
    "ponle que",
    "ponle",
    "pasale que",
    "pasale",
    "comentale que",
    "comentale",
    "cuentale que",
    "cuentale",
    "que",
)

pending_whatsapp_drafts = {}
DEFAULT_DRAFT_TIMEOUT_SECONDS = 45
DEFAULT_RECENT_MESSAGE_WINDOW_MINUTES = 5


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _strip_accents(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_spoken_text(text: str) -> str:
    text = _strip_accents(text).casefold()
    text = text.replace("¿", " ").replace("?", " ").replace("¡", " ").replace("!", " ")
    text = re.sub(r"[\"'`´“”‘’]", " ", text)
    text = re.sub(r"[;()\[\]{}]", " ", text)
    text = re.sub(r"\s*:\s*", ": ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")

    changed = True
    while changed:
        changed = False
        for prefix in PREFIXES:
            if text == prefix:
                text = ""
                changed = True
            elif text.startswith(f"{prefix} "):
                text = text[len(prefix):].strip()
                changed = True
    return re.sub(r"\s+", " ", text).strip(" .")


def _normalize(text):
    return normalize_spoken_text(text).strip(" ?!.,")


def _clean_spoken_recipient(value):
    text = str(value or "").strip(" ?!.,:")
    lowered = _normalize(text)
    for prefix in ("mi ", "la ", "el "):
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def _target_key(target):
    return (target or {}).get("id") or (target or {}).get("canonical_target") or (target or {}).get("raw_target") or (target or {}).get("display_name")


def _target_label(target):
    return (target or {}).get("display_name") or (target or {}).get("canonical_target") or (target or {}).get("raw_target") or "contacto"


def _target_canonical(target):
    return (target or {}).get("canonical_target") or (target or {}).get("raw_target") or (target or {}).get("target")


def _target_is_allowed(target):
    return bool((target or {}).get("allowed"))


def _target_not_allowed_response(target, intent=None):
    label = _target_label(target)
    return _result(
        True,
        False,
        f"Tengo a {label} en la agenda, pero no esta en la allowlist de WhatsApp de Jarvis.",
        mode="not_allowed",
        data={"target": target, "intent": intent or {}},
        target=target,
    )


def _allowed_targets(targets_manager):
    if hasattr(targets_manager, "list_allowed_targets"):
        return targets_manager.list_allowed_targets(channel="whatsapp")
    return [
        target for target in targets_manager.list_targets()
        if normalize_spoken_text(target.get("channel")) == "whatsapp" and target.get("allowed")
    ]


def _allowed_target_ids(targets_manager):
    values = set()
    for target in _allowed_targets(targets_manager):
        for value in (
            target.get("canonical_target"),
            target.get("raw_target"),
            target.get("display_name"),
            target.get("id"),
        ):
            clean = str(value or "").strip()
            if clean:
                values.add(clean)
                values.add(normalize_spoken_text(clean))
    return values


def _message_matches_allowed_target(message, allowed_values):
    if not allowed_values:
        return False
    for value in (
        message.get("target"),
        message.get("sender"),
        message.get("conversation_id"),
        message.get("display_target"),
        message.get("sender_name"),
    ):
        clean = str(value or "").strip()
        if clean and (clean in allowed_values or normalize_spoken_text(clean) in allowed_values):
            return True
    return False


def _message_sender_label(message):
    return (
        message.get("display_target")
        or message.get("sender_name")
        or message.get("sender")
        or message.get("target")
        or "WhatsApp"
    )


def _recent_window_minutes():
    try:
        return max(1, int(os.getenv("JARVIS_WHATSAPP_RECENT_MESSAGE_MINUTES", DEFAULT_RECENT_MESSAGE_WINDOW_MINUTES)))
    except Exception:
        return DEFAULT_RECENT_MESSAGE_WINDOW_MINUTES


def _list_allowed_targets_response(targets_manager):
    allowed = _allowed_targets(targets_manager)
    if not allowed:
        return _result(
            True,
            True,
            "No tienes contactos ni grupos en la allowlist de WhatsApp de Jarvis.",
            mode="safe",
            data={"targets": []},
            targets=[],
        )

    people = [_target_label(target) for target in allowed if normalize_spoken_text(target.get("kind")) != "group"]
    groups = [_target_label(target) for target in allowed if normalize_spoken_text(target.get("kind")) == "group"]
    chunks = []
    if people:
        chunks.append("Personas: " + ", ".join(people[:20]))
    if groups:
        chunks.append("Grupos: " + ", ".join(groups[:20]))
    hidden = max(0, len(allowed) - 40)
    suffix = f" Y {hidden} mas." if hidden else ""
    return _result(
        True,
        True,
        f"Puedo enviar WhatsApp a {len(allowed)} destino(s) permitidos. {' '.join(chunks)}.{suffix}",
        mode="safe",
        data={"targets": allowed},
        targets=allowed,
    )


def _add_label(labels, label, target, source):
    label = str(label or "").strip()
    label_norm = normalize_spoken_text(label).strip(" ,.:")
    if not label_norm:
        return
    labels.append({
        "label": label,
        "label_norm": label_norm,
        "target": deepcopy(target),
        "source": source,
        "score": len(label_norm),
    })


def build_target_candidates(targets_manager) -> list[dict]:
    candidates = []
    for target in targets_manager.list_targets():
        if normalize_spoken_text(target.get("channel")) != "whatsapp":
            continue

        raw_aliases = list(target.get("aliases") or [])
        relationship = target.get("relationship")
        for label, source in (
            (target.get("display_name"), "display_name"),
            (relationship, "relationship"),
            (target.get("canonical_target"), "canonical_target"),
            (target.get("raw_target"), "raw_target"),
        ):
            _add_label(candidates, label, target, source)

        for alias in raw_aliases:
            _add_label(candidates, alias, target, "alias")
            _add_label(candidates, f"mi {alias}", target, "alias")

        if relationship:
            _add_label(candidates, f"mi {relationship}", target, "relationship")

        for alias in _semantic_extra_aliases(target, candidates):
            _add_label(candidates, alias, target, "semantic")

    deduped = {}
    for candidate in candidates:
        key = (_target_key(candidate["target"]), candidate["label_norm"])
        current = deduped.get(key)
        if not current or candidate["score"] > current["score"]:
            deduped[key] = candidate

    return sorted(
        deduped.values(),
        key=lambda item: (
            len(item["label_norm"]),
            bool(item["target"].get("favorite")),
            bool(item["target"].get("relationship")),
            item["source"] == "display_name",
        ),
        reverse=True,
    )


def _find_label_span(text_norm, label_norm):
    if not text_norm or not label_norm:
        return None
    pattern = re.compile(rf"(?<![\w+]){re.escape(label_norm)}(?![\w])")
    match = pattern.search(text_norm)
    if match:
        return match.span()
    if label_norm.startswith("+") and label_norm in text_norm:
        start = text_norm.index(label_norm)
        return start, start + len(label_norm)
    return None


def find_target_mentions(text, targets_manager) -> list:
    text_norm = normalize_spoken_text(text)
    matches = []
    for candidate in build_target_candidates(targets_manager):
        span = _find_label_span(text_norm, candidate["label_norm"])
        if not span:
            continue
        target = candidate["target"]
        score = len(candidate["label_norm"]) * 10
        if target.get("favorite"):
            score += 5
        if target.get("relationship"):
            score += 3
        if candidate.get("source") == "display_name":
            score += 2
        matches.append({
            **candidate,
            "start": span[0],
            "end": span[1],
            "score": score,
            "exact": text_norm == candidate["label_norm"],
        })

    best_by_target = {}
    for match in matches:
        key = _target_key(match["target"])
        current = best_by_target.get(key)
        if not current or (
            match["score"],
            len(match["label_norm"]),
            -match["start"],
        ) > (
            current["score"],
            len(current["label_norm"]),
            -current["start"],
        ):
            best_by_target[key] = match

    return sorted(
        best_by_target.values(),
        key=lambda item: (
            item["score"],
            len(item["label_norm"]),
            bool(item["target"].get("favorite")),
            bool(item["target"].get("relationship")),
            item["source"] == "display_name",
        ),
        reverse=True,
    )


def looks_like_whatsapp_send_request(text: str) -> bool:
    text_norm = normalize_spoken_text(text)
    if not text_norm:
        return False
    if any(marker in text_norm for marker in SEND_MARKERS):
        return True
    if "mensaje" in text_norm and re.search(r"\b(?:manda|mandale|envia|enviale|escribe|escribele|dile|avisale|pasale|ponle|comentale)\b", text_norm):
        return True
    if re.search(r"^a\s+.+\s+dile\b", text_norm):
        return True
    if re.search(r"^.+,?\s+dile\b", text_norm):
        return True
    return False


def _strip_message_noise(message):
    message = normalize_spoken_text(message).strip(" ,.:")
    message = re.sub(r"^(?:que\s+)?(?:diga|le diga)\s+", "", message).strip()
    message = re.sub(r"^(?:por\s+whatsapp|whatsapp)\s+", "", message).strip()
    return message.strip(" ,.:")


def _message_from_fragment(fragment):
    fragment = normalize_spoken_text(fragment).strip(" ,.:")
    if not fragment:
        return None
    if fragment.startswith("por whatsapp "):
        fragment = fragment[len("por whatsapp "):].strip()
    if fragment == "por whatsapp":
        return None
    for leader in MESSAGE_LEADERS:
        prefix = f"{leader} "
        if fragment.startswith(prefix):
            return _strip_message_noise(fragment[len(prefix):])
    return _strip_message_noise(fragment)


def extract_message_after_target(text, target_label) -> str | None:
    text_norm = normalize_spoken_text(text)
    label_norm = normalize_spoken_text(target_label).strip(" ,.:")

    if ":" in text_norm:
        after_colon = _strip_message_noise(text_norm.split(":", 1)[1])
        if after_colon:
            return after_colon

    span = _find_label_span(text_norm, label_norm)
    if span:
        before = text_norm[:span[0]].strip(" ,.:")
        after = text_norm[span[1]:].strip(" ,.:")
        message = _message_from_fragment(after)
        if message:
            return message

        for connector in CONNECTORS_BEFORE_TARGET:
            marker = f"{connector} {label_norm}"
            marker_index = text_norm.find(marker)
            if marker_index >= 0:
                message = _message_from_fragment(text_norm[marker_index + len(marker):])
                if message:
                    return message

        if before.endswith("dile") or before.endswith("avisale") or before.endswith("escribele"):
            message = _message_from_fragment(after)
            if message:
                return message

    for pattern in (
        r"\bque diga\s+(.+)$",
        r"\bdiciendo\s+(.+)$",
        r"\bque le diga\s+(.+)$",
        r"\bdile que\s+(.+)$",
        r"\bavisale que\s+(.+)$",
        r"\bescribele que\s+(.+)$",
        r"\bponle que\s+(.+)$",
        r"\bpasale que\s+(.+)$",
        r"\bcomentale que\s+(.+)$",
        r"\bcuentale que\s+(.+)$",
    ):
        match = re.search(pattern, text_norm)
        if match:
            return _strip_message_noise(match.group(1))

    return None


def _is_import_intent(text_norm):
    return any(pattern.match(text_norm) for pattern in IMPORT_PATTERNS)


def _is_list_allowed_intent(text_norm):
    return any(pattern.match(text_norm) for pattern in LIST_ALLOWED_PATTERNS)


def _parse_allowlist_update_intent(text_norm, targets_manager):
    for pattern in ALLOWLIST_PATTERNS:
        match = pattern.match(text_norm)
        if not match:
            continue
        recipient = _clean_spoken_recipient(match.group("recipient"))
        target = targets_manager.find_best_match("whatsapp", recipient)
        action = normalize_spoken_text(match.group("action"))
        allowed = action in {"permite", "autoriza", "anade", "añade", "agrega", "mete"}
        return {
            "type": "update_whatsapp_allowlist",
            "recipient": recipient,
            "target": target,
            "allowed": allowed,
            "confidence": 0.95 if target else 0.65,
            "missing": [] if target else ["recipient"],
        }
    return None


def _is_read_intent(text_norm):
    return any(marker in text_norm for marker in READ_MARKERS)


def _is_read_all_intent(text_norm):
    return any(marker in text_norm for marker in READ_ALL_MARKERS)


def _semantic_extra_aliases(target, candidates):
    labels = [
        target.get("display_name"),
        target.get("relationship"),
        *list(target.get("aliases") or []),
    ]
    normalized = " ".join(normalize_spoken_text(label) for label in labels if label)
    has_romantic_hint = any(token in normalized for token in ("novia", "novio", "pareja", "mi nina", "mi nino", "ninaaa"))
    has_heart = any(symbol in " ".join(str(label or "") for label in labels) for symbol in ("❤", "❤️", "💕", "💖", "♥"))
    if has_romantic_hint or has_heart:
        return ["pareja", "mi pareja", "novia", "mi novia"]
    return []


def _top_targets_are_ambiguous(matches):
    if len(matches) < 2:
        return False
    top = matches[0]
    ambiguous = [
        match for match in matches
        if match["score"] == top["score"] and _target_key(match["target"]) != _target_key(top["target"])
    ]
    return bool(ambiguous)


def _ambiguous_targets(matches):
    top_score = matches[0]["score"] if matches else None
    seen = set()
    targets = []
    for match in matches:
        if match["score"] != top_score:
            continue
        key = _target_key(match["target"])
        if key in seen:
            continue
        seen.add(key)
        targets.append(match["target"])
    return targets


def _regex_parse_whatsapp_intent(text, targets_manager):
    normalized = _normalize(text)
    for pattern in IMPORT_PATTERNS:
        if pattern.match(normalized):
            return {"type": "import_contacts", "confidence": 1.0, "missing": []}

    if _is_list_allowed_intent(normalized):
        return {"type": "list_allowed_whatsapp_targets", "confidence": 1.0, "missing": []}

    allowlist_intent = _parse_allowlist_update_intent(normalized, targets_manager)
    if allowlist_intent:
        return allowlist_intent

    for pattern in SEND_PATTERNS:
        match = pattern.match(normalized)
        if match:
            recipient = _clean_spoken_recipient(match.group("recipient"))
            target = targets_manager.find_best_match("whatsapp", recipient)
            return {
                "type": "send_whatsapp",
                "recipient": recipient,
                "message": str(match.group("message") or "").strip(),
                "target": target,
                "confidence": 0.95 if target else 0.65,
                "missing": [] if target else ["recipient"],
            }

    for pattern in READ_PATTERNS:
        match = pattern.match(normalized)
        if match:
            recipient = _clean_spoken_recipient(match.group("recipient"))
            target = targets_manager.find_best_match("whatsapp", recipient)
            return {
                "type": "read_new_whatsapp",
                "recipient": recipient,
                "target": target,
                "confidence": 0.95 if target else 0.65,
                "missing": [] if target else ["recipient"],
            }
    return None


def semantic_parse_whatsapp_intent(text, targets_manager) -> dict:
    text_norm = normalize_spoken_text(text)
    if not text_norm:
        return {"type": None, "recipient": None, "message": None, "target": None, "confidence": 0.0, "missing": []}

    if _is_import_intent(text_norm):
        return {"type": "import_contacts", "recipient": None, "message": None, "target": None, "confidence": 0.95, "missing": []}

    if _is_list_allowed_intent(text_norm):
        return {"type": "list_allowed_whatsapp_targets", "recipient": None, "message": None, "target": None, "confidence": 0.98, "missing": []}

    allowlist_intent = _parse_allowlist_update_intent(text_norm, targets_manager)
    if allowlist_intent:
        return allowlist_intent

    matches = find_target_mentions(text_norm, targets_manager)
    target_match = matches[0] if matches else None
    ambiguous = _top_targets_are_ambiguous(matches)

    if _is_read_all_intent(text_norm) and not target_match:
        return {
            "type": "read_new_whatsapp",
            "recipient": None,
            "message": None,
            "target": None,
            "confidence": 0.9,
            "missing": [],
            "read_all": True,
            "matches": [],
        }

    if _is_read_intent(text_norm):
        missing = []
        if ambiguous:
            missing.append("disambiguation")
        elif not target_match:
            missing.append("recipient")
        return {
            "type": "read_new_whatsapp",
            "recipient": target_match.get("label") if target_match else None,
            "message": None,
            "target": target_match.get("target") if target_match and not ambiguous else None,
            "confidence": 0.9 if target_match and not ambiguous else 0.55,
            "missing": missing,
            "matches": matches,
        }

    send_like = looks_like_whatsapp_send_request(text_norm)
    if not send_like:
        return {"type": None, "recipient": None, "message": None, "target": None, "confidence": 0.0, "missing": []}

    recipient = target_match.get("label") if target_match else None
    target = target_match.get("target") if target_match and not ambiguous else None
    message = None
    if target_match:
        message = extract_message_after_target(text_norm, target_match["label_norm"])
    if not message:
        message = _extract_message_without_target(text_norm)

    missing = []
    if ambiguous:
        missing.append("disambiguation")
    elif not target:
        missing.append("recipient")
    if not message:
        missing.append("message")

    confidence = 0.4
    if target:
        confidence += 0.3
    if message:
        confidence += 0.25
    if "whatsapp" in text_norm or "mensaje" in text_norm:
        confidence += 0.05
    if not missing:
        confidence = max(confidence, 0.85)

    return {
        "type": "send_whatsapp",
        "recipient": recipient,
        "message": message,
        "target": target,
        "confidence": min(confidence, 0.98),
        "missing": missing,
        "matches": matches,
    }


def _extract_message_without_target(text_norm):
    if ":" in text_norm:
        message = _strip_message_noise(text_norm.split(":", 1)[1])
        if message:
            return message
    for pattern in (
        r"\bque diga\s+(.+)$",
        r"\bdiciendo\s+(.+)$",
        r"\bque le diga\s+(.+)$",
        r"\bque\s+(.+)$",
    ):
        match = re.search(pattern, text_norm)
        if match:
            return _strip_message_noise(match.group(1))
    return None


def llm_extract_whatsapp_intent(text, targets_manager) -> dict:
    if os.getenv("JARVIS_WHATSAPP_LLM_INTENT_EXTRACTOR", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return {"type": None, "confidence": 0.0, "missing": []}

    # Intentionally conservative: this hook only extracts JSON when a local app
    # wires a model helper in-process. It never calls OpenClaw and never creates
    # pending actions.
    extractor = globals().get("_llm_intent_extractor")
    if not callable(extractor):
        return {"type": None, "confidence": 0.0, "missing": ["llm_unavailable"]}

    aliases = [candidate["label"] for candidate in build_target_candidates(targets_manager)]
    prompt = (
        "Extrae si el usuario quiere enviar o leer WhatsApp. Devuelve solo JSON con: "
        "intent, recipient_text, message_text, confidence, missing_fields. "
        "No inventes destinatarios. Usa solo el texto del usuario.\n"
        f"Aliases disponibles: {json.dumps(aliases, ensure_ascii=False)}\n"
        f"Texto: {text}"
    )
    try:
        raw = extractor(prompt)
        parsed = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except Exception:
        return {"type": None, "confidence": 0.0, "missing": ["llm_error"]}

    intent = str(parsed.get("intent") or "").strip().lower()
    intent_type = {
        "send": "send_whatsapp",
        "send_whatsapp": "send_whatsapp",
        "read": "read_new_whatsapp",
        "read_new_whatsapp": "read_new_whatsapp",
        "import_contacts": "import_contacts",
        "list_allowed": "list_allowed_whatsapp_targets",
        "list_allowed_whatsapp_targets": "list_allowed_whatsapp_targets",
        "update_allowlist": "update_whatsapp_allowlist",
        "update_whatsapp_allowlist": "update_whatsapp_allowlist",
    }.get(intent)
    recipient = parsed.get("recipient_text")
    target = None
    if recipient:
        target = targets_manager.find_best_match("whatsapp", recipient)
    missing = list(parsed.get("missing_fields") or [])
    if recipient and not target and "recipient" not in missing:
        missing.append("recipient")
    return {
        "type": intent_type,
        "recipient": recipient,
        "message": parsed.get("message_text"),
        "target": target,
        "confidence": float(parsed.get("confidence") or 0.0),
        "missing": missing,
    }


def parse_openclaw_voice_intent(text):
    return _regex_parse_whatsapp_intent(text, _EmptyTargetsManager())


class _EmptyTargetsManager:
    def list_targets(self):
        return []

    def find_best_match(self, *_args, **_kwargs):
        return None


def _result(handled, success=False, response="", mode=None, data=None, **extra):
    payload = {
        "handled": bool(handled),
        "success": bool(success),
        "response": response,
        "mode": mode,
        "data": data or {},
    }
    if response:
        payload["message"] = response
    payload.update(extra)
    return payload


def _draft_key(session_id):
    return str(session_id or "default")


def _draft_timeout_seconds():
    try:
        return max(5, int(os.getenv("JARVIS_WHATSAPP_DRAFT_TIMEOUT_SECONDS", DEFAULT_DRAFT_TIMEOUT_SECONDS)))
    except Exception:
        return DEFAULT_DRAFT_TIMEOUT_SECONDS


def _draft_is_expired(draft):
    created_at = (draft or {}).get("created_at")
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(str(created_at))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return (datetime.now(timezone.utc) - created).total_seconds() > _draft_timeout_seconds()


def _get_draft(session_id):
    draft = pending_whatsapp_drafts.get(_draft_key(session_id))
    if not draft:
        return None
    if _draft_is_expired(draft):
        _clear_draft(session_id)
        return None
    return draft


def _save_draft(session_id, **fields):
    draft = {
        "recipient": None,
        "target_id": None,
        "message": None,
        "created_at": _now_iso(),
    }
    draft.update(fields)
    pending_whatsapp_drafts[_draft_key(session_id)] = draft
    return draft


def _clear_draft(session_id):
    pending_whatsapp_drafts.pop(_draft_key(session_id), None)


def _looks_like_standalone_recipient_answer(text_norm):
    text_norm = normalize_spoken_text(text_norm)
    if not text_norm:
        return False
    if looks_like_whatsapp_send_request(text_norm) or _is_read_intent(text_norm) or _is_read_all_intent(text_norm):
        return False
    if _message_from_fragment(text_norm) != _strip_message_noise(text_norm):
        return False
    words = text_norm.split()
    return 1 <= len(words) <= 5


def _find_existing_pending_send(pending_actions_manager, canonical_target, message):
    if not pending_actions_manager:
        return None
    for action in pending_actions_manager.get_pending_actions():
        if action.get("action_type") not in {"send_message", "send_whatsapp_message", "send_channel_message"}:
            continue
        payload = action.get("payload") or {}
        if normalize_spoken_text(payload.get("channel")) != "whatsapp":
            continue
        pending_target = payload.get("canonical_target") or payload.get("target")
        if str(pending_target or "").strip() == str(canonical_target or "").strip() and str(payload.get("message") or "").strip() == str(message or "").strip():
            return action
    return None


def _complete_existing_draft(text, targets_manager, messages_manager, pending_actions_manager, session_id):
    draft = _get_draft(session_id)
    if not draft:
        return None

    text_norm = normalize_spoken_text(text)
    if text_norm in {"nadie", "a nadie", "no", "cancelar", "cancela", "olvidalo"}:
        _clear_draft(session_id)
        return _result(True, True, "Vale, cancelo el borrador de WhatsApp.", mode="safe")

    target = targets_manager.get_target(draft.get("target_id")) if draft.get("target_id") else None
    message = draft.get("message")

    if not target:
        matches = find_target_mentions(text_norm, targets_manager)
        if _top_targets_are_ambiguous(matches):
            return _ambiguous_response(matches, session_id, draft=draft)
        if matches:
            target = matches[0]["target"]
            draft["target_id"] = target.get("id")
            draft["recipient"] = matches[0]["label"]
        elif draft.get("message") and _looks_like_standalone_recipient_answer(text_norm):
            _clear_draft(session_id)
            return _result(
                True,
                False,
                "No tengo guardado ese contacto. Importa tus contactos o crealo en la agenda de WhatsApp de Jarvis.",
                mode="not_found",
                data={"recipient": text_norm, "draft": draft},
            )
        else:
            pending_whatsapp_drafts[_draft_key(session_id)] = draft
            return None

    if not message:
        if target:
            message = extract_message_after_target(text_norm, target.get("display_name") or draft.get("recipient") or "")
        if not message:
            message = _message_from_fragment(text_norm) or _strip_message_noise(text_norm)
        draft["message"] = message

    if target and message:
        _clear_draft(session_id)
        return _create_pending_send(target, message, pending_actions_manager, {"type": "send_whatsapp", "draft_completed": True})

    pending_whatsapp_drafts[_draft_key(session_id)] = draft
    if not target:
        return _result(True, False, "¿A quien quieres que le mande el WhatsApp?", mode="missing_recipient", data={"draft": draft})
    return _result(True, False, f"¿Que mensaje quieres que le mande a {_target_label(target)}?", mode="missing_message", data={"draft": draft, "target": target})


def _ambiguous_response(matches, session_id, draft=None):
    targets = _ambiguous_targets(matches)
    names = ", ".join(_target_label(target) for target in targets)
    if draft is not None:
        pending_whatsapp_drafts[_draft_key(session_id)] = draft
    return _result(
        True,
        False,
        f"He encontrado varios contactos parecidos: {names}. ¿A cual te refieres?",
        mode="disambiguation_required",
        data={"matches": targets, "draft": draft or {}},
    )


def _create_pending_send(target, message, pending_actions_manager, intent):
    canonical_target = target.get("canonical_target") or target.get("raw_target")
    display_target = target.get("display_name") or intent.get("recipient") or canonical_target
    if not canonical_target:
        return _result(
            True,
            False,
            f"El contacto {display_target} no tiene un numero o target canonico guardado.",
            mode="not_found",
            data={"target": target, "intent": intent},
        )
    if not _target_is_allowed(target):
        return _target_not_allowed_response(target, intent)

    payload = {
        "channel": "whatsapp",
        "kind": target.get("kind", "user"),
        "target": canonical_target,
        "canonical_target": canonical_target,
        "display_target": display_target,
        "target_id": target.get("id"),
        "message": message,
    }
    pending = _find_existing_pending_send(pending_actions_manager, canonical_target, message)
    if not pending:
        pending = pending_actions_manager.create_pending_action(
            "send_message",
            payload,
            f"Enviar WhatsApp a {display_target}: {message}",
        )
    response = f"He preparado el WhatsApp para {display_target}: '{message}'. Confirmalo para enviarlo."
    return _result(
        True,
        True,
        response,
        mode="confirmation_required",
        data={"pending_action": pending, "target": target, "intent": intent},
        pending_action=pending,
        target=target,
    )


def _handle_missing_send_fields(intent, session_id):
    target = intent.get("target")
    message = intent.get("message")
    missing = set(intent.get("missing") or [])

    if "disambiguation" in missing:
        return _ambiguous_response(intent.get("matches") or [], session_id, draft={
            "recipient": intent.get("recipient"),
            "message": message,
            "created_at": _now_iso(),
        })

    if "recipient" in missing:
        if intent.get("recipient"):
            _clear_draft(session_id)
            return _result(
                True,
                False,
                "No tengo guardado ese contacto. Importa tus contactos o crealo en la agenda de WhatsApp de Jarvis.",
                mode="not_found",
                data={"recipient": intent.get("recipient"), "intent": intent},
            )
        _save_draft(session_id, message=message, created_at=_now_iso())
        return _result(True, False, "¿A quien quieres que le mande el WhatsApp?", mode="missing_recipient", data={"intent": intent})

    if "message" in missing and target:
        _save_draft(
            session_id,
            recipient=intent.get("recipient") or _target_label(target),
            target_id=target.get("id"),
            message=None,
            created_at=_now_iso(),
        )
        return _result(True, False, f"¿Que mensaje quieres que le mande a {_target_label(target)}?", mode="missing_message", data={"intent": intent, "target": target})

    return None


def _read_new_messages(intent, messages_manager, targets_manager):
    minutes = _recent_window_minutes()
    target = intent.get("target")
    if intent.get("read_all") and not target:
        allowed_values = _allowed_target_ids(targets_manager)
        messages = messages_manager.list_recent_messages("whatsapp", None, minutes=minutes, limit=100, mark_read=True)
        messages = [message for message in messages if _message_matches_allowed_target(message, allowed_values)][:20]
        if not messages:
            return _result(
                True,
                True,
                f"No tienes mensajes recientes de la allowlist de WhatsApp en los ultimos {minutes} minutos.",
                mode="safe",
                data={"messages": [], "intent": intent},
                messages=[],
            )
        snippets = []
        for item in reversed(messages):
            sender = _message_sender_label(item)
            body = item.get("message")
            if body:
                snippets.append(f"{sender}: {body}")
        joined = " ".join(snippets[:5])
        return _result(
            True,
            True,
            f"Tienes {len(messages)} mensaje(s) reciente(s) de WhatsApp en los ultimos {minutes} minutos: {joined}",
            mode="safe",
            data={"messages": messages, "intent": intent},
            messages=messages,
        )

    if not target:
        return _result(True, False, "¿De quien quieres que lea los mensajes nuevos?", mode="missing_recipient", data={"intent": intent})

    if not _target_is_allowed(target):
        return _target_not_allowed_response(target, intent)

    canonical_target = _target_canonical(target)
    display_target = target.get("display_name") or intent.get("recipient") or canonical_target
    messages = messages_manager.list_recent_messages("whatsapp", canonical_target, minutes=minutes, limit=20, mark_read=True)
    if not messages:
        return _result(
            True,
            True,
            f"No tienes mensajes recientes de {display_target} en los ultimos {minutes} minutos.",
            mode="safe",
            data={"target": target, "messages": [], "intent": intent},
            target=target,
            messages=[],
        )

    snippets = [item.get("message") for item in reversed(messages) if item.get("message")]
    joined = " ".join(snippets[:5])
    return _result(
        True,
        True,
        f"Tienes {len(messages)} mensaje(s) reciente(s) de {display_target}: {joined}",
        mode="safe",
        data={"target": target, "messages": messages, "intent": intent},
        target=target,
        messages=messages,
    )


def _resolve_regex_intent(intent, targets_manager):
    if not intent or not intent.get("recipient") or intent.get("target"):
        return intent
    target = targets_manager.find_best_match("whatsapp", intent.get("recipient"))
    intent["target"] = target
    intent["confidence"] = 0.95 if target else intent.get("confidence", 0.65)
    intent["missing"] = [] if target else ["recipient"]
    return intent


def route_openclaw_voice_intent(text, targets_manager, messages_manager, pending_actions_manager, session_id="default"):
    text_norm = normalize_spoken_text(text)
    completed = _complete_existing_draft(text_norm, targets_manager, messages_manager, pending_actions_manager, session_id)
    if completed:
        return completed

    intent = _resolve_regex_intent(_regex_parse_whatsapp_intent(text_norm, targets_manager), targets_manager)
    if not intent:
        intent = semantic_parse_whatsapp_intent(text_norm, targets_manager)

    if (not intent or not intent.get("type") or intent.get("confidence", 0.0) < 0.85) and os.getenv("JARVIS_WHATSAPP_LLM_INTENT_EXTRACTOR", "").strip().lower() in {"1", "true", "yes", "on"}:
        llm_intent = llm_extract_whatsapp_intent(text, targets_manager)
        if llm_intent.get("type") and llm_intent.get("confidence", 0.0) >= (intent or {}).get("confidence", 0.0):
            intent = llm_intent

    if not intent or not intent.get("type"):
        return _result(False)

    if intent["type"] == "list_allowed_whatsapp_targets":
        return _list_allowed_targets_response(targets_manager)

    if intent["type"] == "update_whatsapp_allowlist":
        target = intent.get("target")
        if not target and intent.get("recipient"):
            target = targets_manager.find_best_match("whatsapp", intent.get("recipient"))
        if not target:
            return _result(
                True,
                False,
                "No encuentro ese contacto o grupo en la agenda local de WhatsApp de Jarvis.",
                mode="not_found",
                data={"recipient": intent.get("recipient"), "intent": intent},
            )
        updated = targets_manager.mark_allowed(target.get("id"), bool(intent.get("allowed", True)))
        if not updated:
            return _result(True, False, "No he podido actualizar la allowlist de WhatsApp.", mode="not_found", data={"target": target, "intent": intent})
        action = "marcado como permitido en" if updated.get("allowed") else "quitado de"
        return _result(
            True,
            True,
            f"He {action} la allowlist de WhatsApp de Jarvis a {_target_label(updated)}.",
            mode="safe",
            data={"target": updated, "intent": intent},
            target=updated,
        )

    if intent["type"] == "import_contacts":
        return _result(
            True,
            True,
            "Para importar contactos de WhatsApp, sube un CSV o VCF en el dashboard OpenClaw. OpenClaw no expone la agenda completa automaticamente.",
            mode="safe",
            data={"intent": intent},
        )

    if intent["type"] == "read_new_whatsapp":
        if "disambiguation" in set(intent.get("missing") or []):
            return _ambiguous_response(intent.get("matches") or [], session_id)
        if not intent.get("target") and intent.get("recipient"):
            intent["target"] = targets_manager.find_best_match("whatsapp", intent.get("recipient"))
        if not intent.get("target") and not intent.get("read_all"):
            return _result(True, False, "¿De quien quieres que lea los mensajes nuevos?", mode="missing_recipient", data={"intent": intent})
        return _read_new_messages(intent, messages_manager, targets_manager)

    if intent["type"] == "send_whatsapp":
        if not intent.get("target") and not intent.get("recipient") and not intent.get("message"):
            return _result(False)

        if not intent.get("target") and intent.get("recipient"):
            intent["target"] = targets_manager.find_best_match("whatsapp", intent.get("recipient"))
            if intent["target"]:
                missing = [item for item in intent.get("missing", []) if item != "recipient"]
                intent["missing"] = missing

        missing_response = _handle_missing_send_fields(intent, session_id)
        if missing_response:
            return missing_response

        if not intent.get("target"):
            return _result(
                True,
                False,
                "No tengo guardado ese contacto. Importa tus contactos o crealo en la agenda de WhatsApp de Jarvis.",
                mode="not_found",
                data={"recipient": intent.get("recipient"), "intent": intent},
            )
        return _create_pending_send(intent["target"], intent.get("message"), pending_actions_manager, intent)

    return _result(False)
