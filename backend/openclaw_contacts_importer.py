import csv
import io
import quopri
import re


PHONE_KEYS = ("phone", "number", "mobile", "tel")
NAME_KEYS = ("name", "display_name", "fn")


def normalize_phone(value, default_country_code="+34"):
    raw = str(value or "").strip()
    if not raw:
        return None
    phone = re.sub(r"[\s().-]+", "", raw)
    if phone.startswith("00"):
        phone = f"+{phone[2:]}"
    if phone.startswith("+"):
        return phone if re.fullmatch(r"\+\d{6,15}", phone) else None
    if phone.startswith("34"):
        candidate = f"+{phone}"
        return candidate if re.fullmatch(r"\+\d{6,15}", candidate) else None
    if re.fullmatch(r"[679]\d{8}", phone):
        return f"{default_country_code}{phone}"
    return None


def _decode(file_bytes):
    if isinstance(file_bytes, str):
        return file_bytes
    data = file_bytes or b""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _truthy(value):
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "si", "sí", "on", "favorite"}


def decode_contact_text(value, charset="utf-8"):
    text = str(value or "").strip()
    if not text:
        return ""
    if re.search(r"=(?:[0-9A-Fa-f]{2})", text):
        for encoding in (charset or "utf-8", "utf-8", "latin-1"):
            try:
                return quopri.decodestring(text).decode(encoding).strip()
            except Exception:
                continue
    return text


def _split_aliases(value):
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,;|]", str(value or ""))
    return [item.strip() for item in raw if item and item.strip()]


def _get(row, keys):
    normalized = {str(key or "").strip().lower(): value for key, value in (row or {}).items()}
    for key in keys:
        value = normalized.get(key)
        if value not in (None, ""):
            return value
    return ""


def _upsert_imported_contact(targets_manager, name, raw_phone, aliases=None, relationship="", favorite=False, source="contacts_import"):
    canonical_phone = normalize_phone(raw_phone)
    if not canonical_phone:
        return None, "skipped"

    display_name = decode_contact_text(name) or canonical_phone
    relationship = decode_contact_text(relationship)
    alias_values = [display_name, *[decode_contact_text(alias) for alias in _split_aliases(aliases)], relationship]
    existing = targets_manager.find_by_canonical_target("whatsapp", canonical_phone)
    target = targets_manager.upsert_contact(
        "whatsapp",
        display_name,
        canonical_phone,
        aliases=alias_values,
        relationship=relationship,
        favorite=favorite,
        source=source,
    )
    return target, "updated" if existing else "created"


def import_contacts_csv(file_bytes, targets_manager):
    text = _decode(file_bytes)
    summary = {"success": True, "created": 0, "updated": 0, "skipped": 0, "errors": []}
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return {**summary, "success": False, "errors": ["CSV sin cabecera."]}

    for index, row in enumerate(reader, start=2):
        try:
            name = _get(row, NAME_KEYS)
            phone = _get(row, PHONE_KEYS)
            aliases = _get(row, ("aliases", "alias"))
            relationship = _get(row, ("relationship", "relation", "relacion", "relación"))
            favorite = _truthy(_get(row, ("favorite", "favourite", "favorito")))
            _, status = _upsert_imported_contact(
                targets_manager,
                name,
                phone,
                aliases=aliases,
                relationship=relationship,
                favorite=favorite,
                source="contacts_import",
            )
            summary[status] += 1
        except Exception as exc:
            summary["skipped"] += 1
            summary["errors"].append(f"Linea {index}: {str(exc)[:160]}")
    return summary


def _unfold_vcf_lines(text):
    lines = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw_line.startswith((" ", "\t")) and lines:
            lines[-1] += raw_line[1:]
        elif raw_line:
            lines.append(raw_line)
    return lines


def _vcard_charset(line):
    head = line.split(":", 1)[0]
    match = re.search(r"(?:^|;)CHARSET=([^;:]+)", head, re.IGNORECASE)
    return match.group(1).strip() if match else "utf-8"


def _vcard_value(line):
    if ":" not in line:
        return ""
    head, value = line.split(":", 1)
    if "ENCODING=QUOTED-PRINTABLE" in head.upper() or re.search(r"=(?:[0-9A-Fa-f]{2})", value):
        return decode_contact_text(value, charset=_vcard_charset(line))
    return value.strip()


def import_contacts_vcf(file_bytes, targets_manager):
    text = _decode(file_bytes)
    summary = {"success": True, "created": 0, "updated": 0, "skipped": 0, "errors": []}
    current = {}

    def flush(card):
        if not card:
            return
        name = card.get("fn") or card.get("name") or card.get("tel")
        phones = card.get("phones") or []
        if not phones:
            summary["skipped"] += 1
            return
        imported = False
        for phone in phones:
            _, status = _upsert_imported_contact(
                targets_manager,
                name,
                phone,
                aliases=[name] if name else [],
                source="vcf_import",
            )
            if status == "skipped":
                continue
            summary[status] += 1
            imported = True
        if not imported:
            summary["skipped"] += 1

    for line in _unfold_vcf_lines(text):
        upper = line.upper()
        if upper == "BEGIN:VCARD":
            current = {"phones": []}
        elif upper == "END:VCARD":
            flush(current)
            current = {}
        elif upper.startswith("FN"):
            current["fn"] = _vcard_value(line)
        elif upper.startswith("N:") and not current.get("fn"):
            current["name"] = _vcard_value(line).replace(";", " ").strip()
        elif upper.startswith("TEL"):
            current.setdefault("phones", []).append(_vcard_value(line))

    flush(current)
    return summary
