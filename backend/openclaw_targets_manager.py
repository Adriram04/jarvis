import json
import quopri
import re
import unicodedata
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


ALLOWED_KINDS = {"user", "group", "auto"}


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(value):
    return str(value or "").strip()


def _decode_contact_text(value):
    text = _clean(value)
    if not text:
        return ""
    if re.search(r"=(?:[0-9A-Fa-f]{2})", text):
        for encoding in ("utf-8", "latin-1"):
            try:
                return quopri.decodestring(text).decode(encoding).strip()
            except Exception:
                continue
    return text


def _norm(value):
    normalized = unicodedata.normalize("NFKD", _decode_contact_text(value))
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return without_accents.casefold()


class OpenClawTargetsManager:
    """Stores canonical OpenClaw targets known by Jarvis."""

    def __init__(self, storage_path=None):
        base_dir = Path(__file__).resolve().parent
        self.storage_path = Path(storage_path) if storage_path else base_dir / "demo_state" / "openclaw_targets.json"
        self._lock = Lock()
        self._targets = []
        self._load()

    def list_targets(self):
        with self._lock:
            return deepcopy(self._targets)

    def list_allowed_targets(self, channel=None, kind=None):
        channel_norm = _norm(channel)
        kind_norm = _norm(kind)
        with self._lock:
            targets = [
                target for target in self._targets
                if target.get("allowed")
                and (not channel_norm or _norm(target.get("channel")) == channel_norm)
                and (not kind_norm or _norm(target.get("kind")) == kind_norm)
            ]
            return deepcopy(sorted(targets, key=lambda item: (
                _norm(item.get("kind")) != "user",
                _norm(item.get("display_name")),
                _norm(item.get("canonical_target") or item.get("raw_target")),
            )))

    def get_target(self, target_id):
        with self._lock:
            target = self._find_target(target_id)
            return deepcopy(target) if target else None

    def add_target(
        self,
        channel,
        kind,
        display_name,
        raw_target,
        canonical_target=None,
        resolved=False,
        allowed=False,
        raw_openclaw=None,
        aliases=None,
        favorite=False,
        relationship="",
        source="manual",
    ):
        normalized = self._normalize_target(
            channel=channel,
            kind=kind,
            display_name=display_name,
            raw_target=raw_target,
            canonical_target=canonical_target,
            resolved=resolved,
            allowed=allowed,
            raw_openclaw=raw_openclaw,
            aliases=aliases,
            favorite=favorite,
            relationship=relationship,
            source=source,
        )

        with self._lock:
            duplicate = self._find_duplicate(normalized)
            if duplicate:
                self._merge_target(duplicate, normalized)
                self._save()
                return deepcopy(duplicate)

            target = {
                "id": str(uuid.uuid4()),
                **normalized,
                "created_at": _now_iso(),
            }
            self._targets.append(target)
            self._save()
            return deepcopy(target)

    def update_target(self, target_id, **fields):
        with self._lock:
            target = self._find_target(target_id)
            if not target:
                return None

            allowed_fields = {
                "channel",
                "kind",
                "display_name",
                "raw_target",
                "canonical_target",
                "resolved",
                "allowed",
                "last_checked_at",
                "raw_openclaw",
                "aliases",
                "favorite",
                "relationship",
                "source",
            }
            for key, value in fields.items():
                if key not in allowed_fields:
                    continue
                if key in {"channel", "raw_target", "canonical_target"}:
                    target[key] = _clean(value)
                elif key == "display_name":
                    target[key] = _decode_contact_text(value)
                elif key == "kind":
                    target[key] = self._normalize_kind(value)
                elif key in {"resolved", "allowed"}:
                    target[key] = bool(value)
                elif key == "favorite":
                    target[key] = bool(value)
                elif key == "aliases":
                    target[key] = self._normalize_aliases(value)
                elif key == "raw_openclaw":
                    target[key] = deepcopy(value or {})
                elif key == "relationship":
                    target[key] = _decode_contact_text(value)
                elif key == "source":
                    target[key] = _clean(value)
                else:
                    target[key] = _clean(value) or _now_iso()

            if "last_checked_at" not in fields:
                target["last_checked_at"] = _now_iso()
            self._save()
            return deepcopy(target)

    def delete_target(self, target_id):
        with self._lock:
            for index, target in enumerate(self._targets):
                if target.get("id") == target_id:
                    removed = self._targets.pop(index)
                    self._save()
                    return deepcopy(removed)
        return None

    def mark_allowed(self, target_id, allowed=True):
        return self.update_target(target_id, allowed=bool(allowed))

    def add_alias(self, target_id, alias):
        alias = _decode_contact_text(alias)
        if not alias:
            return self.get_target(target_id)
        with self._lock:
            target = self._find_target(target_id)
            if not target:
                return None
            aliases = self._normalize_aliases(target.get("aliases"))
            if _norm(alias) not in {_norm(item) for item in aliases}:
                aliases.append(alias)
            target["aliases"] = aliases
            target["last_checked_at"] = _now_iso()
            self._save()
            return deepcopy(target)

    def remove_alias(self, target_id, alias):
        alias_norm = _norm(alias)
        with self._lock:
            target = self._find_target(target_id)
            if not target:
                return None
            target["aliases"] = [item for item in self._normalize_aliases(target.get("aliases")) if _norm(item) != alias_norm]
            target["last_checked_at"] = _now_iso()
            self._save()
            return deepcopy(target)

    def find_by_display_name(self, channel, display_name):
        channel_norm = _norm(channel)
        display_norm = _norm(display_name)
        with self._lock:
            for target in self._targets:
                if _norm(target.get("channel")) == channel_norm and _norm(target.get("display_name")) == display_norm:
                    return deepcopy(target)
        return None

    def find_by_canonical_target(self, channel, canonical_target):
        channel_norm = _norm(channel)
        canonical_norm = _norm(canonical_target)
        with self._lock:
            for target in self._targets:
                if _norm(target.get("channel")) == channel_norm and _norm(target.get("canonical_target")) == canonical_norm:
                    return deepcopy(target)
        return None

    def find_by_alias(self, channel, alias):
        channel_norm = _norm(channel)
        alias_norm = _norm(alias)
        with self._lock:
            for target in self._targets:
                if _norm(target.get("channel")) != channel_norm:
                    continue
                aliases = self._normalize_aliases(target.get("aliases"))
                if any(_norm(item) == alias_norm for item in aliases):
                    return deepcopy(target)
        return None

    def find_best_match(self, channel, query, kind=None):
        channel_norm = _norm(channel)
        query_norm = _norm(query)
        kind_norm = _norm(kind)
        if not query_norm:
            return None

        with self._lock:
            candidates = [
                target for target in self._targets
                if _norm(target.get("channel")) == channel_norm
                and (not kind_norm or _norm(target.get("kind")) in {kind_norm, "auto"})
            ]
            for target in candidates:
                values = [
                    target.get("display_name"),
                    target.get("raw_target"),
                    target.get("canonical_target"),
                    target.get("relationship"),
                    *self._normalize_aliases(target.get("aliases")),
                ]
                if any(_norm(value) == query_norm for value in values):
                    return deepcopy(target)

            for target in candidates:
                values = [
                    target.get("display_name"),
                    target.get("raw_target"),
                    target.get("relationship"),
                    *self._normalize_aliases(target.get("aliases")),
                ]
                if any(query_norm in _norm(value) or _norm(value) in query_norm for value in values if _norm(value)):
                    return deepcopy(target)
        return None

    def upsert_contact(
        self,
        channel,
        display_name,
        phone,
        aliases=None,
        relationship="",
        favorite=False,
        source="manual",
    ):
        canonical_target = _clean(phone)
        alias_values = self._normalize_aliases([
            display_name,
            *self._normalize_aliases(aliases),
            relationship,
        ])
        existing = self.find_by_canonical_target(channel, canonical_target)
        if existing:
            return self.update_target(
                existing["id"],
                display_name=display_name or existing.get("display_name"),
                raw_target=phone or existing.get("raw_target"),
                canonical_target=canonical_target,
                aliases=self._merge_alias_lists(existing.get("aliases"), alias_values),
                relationship=relationship or existing.get("relationship"),
                favorite=bool(existing.get("favorite") or favorite),
                allowed=True,
                source=source or existing.get("source", "manual"),
            )
        return self.add_target(
            channel,
            "user",
            display_name,
            phone,
            canonical_target=canonical_target,
            resolved=False,
            allowed=True,
            aliases=alias_values,
            relationship=relationship,
            favorite=favorite,
            source=source,
        )

    def upsert_from_inbound(self, incoming_message):
        incoming_message = incoming_message or {}
        channel = incoming_message.get("channel") or "whatsapp"
        kind = self._normalize_kind(incoming_message.get("kind"))
        canonical_target = (
            incoming_message.get("target")
            or incoming_message.get("conversation_id")
            or incoming_message.get("sender")
        )
        if not canonical_target:
            return None

        if kind == "auto" and (str(canonical_target).endswith("@g.us") or incoming_message.get("conversation_id")):
            kind = "group"

        display_name = (
            incoming_message.get("display_target")
            or incoming_message.get("sender_name")
            or incoming_message.get("sender")
            or canonical_target
        )
        aliases = self._normalize_aliases([
            display_name,
            incoming_message.get("sender_name"),
            incoming_message.get("display_target"),
        ])

        existing = self.find_by_canonical_target(channel, canonical_target)
        if existing:
            return self.update_target(
                existing["id"],
                kind=kind or existing.get("kind", "auto"),
                display_name=display_name or existing.get("display_name"),
                raw_target=existing.get("raw_target") or canonical_target,
                canonical_target=canonical_target,
                aliases=self._merge_alias_lists(existing.get("aliases"), aliases),
                source=existing.get("source") or "inbound",
                raw_openclaw=incoming_message,
            )

        return self.add_target(
            channel,
            kind,
            display_name,
            canonical_target,
            canonical_target=canonical_target,
            resolved=False,
            allowed=False,
            aliases=aliases,
            source="inbound",
            raw_openclaw=incoming_message,
        )

    def _normalize_target(
        self,
        channel,
        kind,
        display_name,
        raw_target,
        canonical_target=None,
        resolved=False,
        allowed=False,
        raw_openclaw=None,
        aliases=None,
        favorite=False,
        relationship="",
        source="manual",
    ):
        normalized_aliases = self._normalize_aliases(aliases)
        return {
            "channel": _clean(channel).lower() or "whatsapp",
            "kind": self._normalize_kind(kind),
            "display_name": _decode_contact_text(display_name) or _clean(raw_target) or _clean(canonical_target),
            "raw_target": _clean(raw_target) or _clean(display_name) or _clean(canonical_target),
            "canonical_target": _clean(canonical_target),
            "resolved": bool(resolved),
            "allowed": bool(allowed),
            "aliases": normalized_aliases,
            "favorite": bool(favorite),
            "relationship": _decode_contact_text(relationship),
            "source": _clean(source) or "manual",
            "last_checked_at": _now_iso(),
            "raw_openclaw": deepcopy(raw_openclaw or {}),
        }

    def _normalize_kind(self, kind):
        normalized = _clean(kind).lower() or "auto"
        return normalized if normalized in ALLOWED_KINDS else "auto"

    def _find_target(self, target_id):
        for target in self._targets:
            if target.get("id") == target_id:
                return target
        return None

    def _find_duplicate(self, new_target):
        channel = _norm(new_target.get("channel"))
        kind = _norm(new_target.get("kind"))
        comparable_keys = ("display_name", "raw_target", "canonical_target", "relationship")
        new_aliases = {_norm(alias) for alias in self._normalize_aliases(new_target.get("aliases"))}

        for existing in self._targets:
            if _norm(existing.get("channel")) != channel:
                continue
            new_canonical = _norm(new_target.get("canonical_target"))
            existing_canonical = _norm(existing.get("canonical_target"))
            if new_canonical and existing_canonical and new_canonical == existing_canonical:
                return existing
            if _norm(existing.get("kind")) != kind:
                continue
            existing_aliases = {_norm(alias) for alias in self._normalize_aliases(existing.get("aliases"))}
            if new_aliases and existing_aliases and new_aliases.intersection(existing_aliases):
                return existing
            for key in comparable_keys:
                new_value = _norm(new_target.get(key))
                existing_value = _norm(existing.get(key))
                if new_value and existing_value and new_value == existing_value:
                    return existing
        return None

    def _merge_target(self, existing, incoming):
        for key in ("display_name", "raw_target", "canonical_target"):
            if incoming.get(key) and not existing.get(key):
                existing[key] = incoming[key]
        if incoming.get("canonical_target"):
            existing["canonical_target"] = incoming["canonical_target"]
        existing["resolved"] = bool(existing.get("resolved") or incoming.get("resolved"))
        existing["allowed"] = bool(existing.get("allowed") or incoming.get("allowed"))
        if incoming.get("raw_openclaw"):
            existing["raw_openclaw"] = deepcopy(incoming["raw_openclaw"])
        aliases = self._normalize_aliases(existing.get("aliases"))
        alias_norms = {_norm(alias) for alias in aliases}
        for alias in self._normalize_aliases(incoming.get("aliases")):
            if _norm(alias) not in alias_norms:
                aliases.append(alias)
        existing["aliases"] = aliases
        existing["favorite"] = bool(existing.get("favorite") or incoming.get("favorite"))
        if incoming.get("relationship") and not existing.get("relationship"):
            existing["relationship"] = incoming["relationship"]
        if incoming.get("source") and existing.get("source") in {None, "", "manual"}:
            existing["source"] = incoming["source"]
        existing["last_checked_at"] = _now_iso()

    def _merge_alias_lists(self, first, second):
        return self._normalize_aliases([*self._normalize_aliases(first), *self._normalize_aliases(second)])

    def _normalize_aliases(self, aliases):
        if aliases is None:
            return []
        if isinstance(aliases, str):
            raw_aliases = [item.strip() for item in aliases.split(",")]
        else:
            raw_aliases = list(aliases or [])
        seen = set()
        normalized = []
        for alias in raw_aliases:
            clean_alias = _decode_contact_text(alias)
            alias_norm = _norm(clean_alias)
            if clean_alias and alias_norm not in seen:
                normalized.append(clean_alias)
                seen.add(alias_norm)
        return normalized

    def _normalize_loaded_target(self, target):
        if not isinstance(target, dict):
            return None
        normalized = dict(target)
        normalized.setdefault("aliases", [])
        normalized.setdefault("favorite", False)
        normalized.setdefault("relationship", "")
        normalized.setdefault("source", "manual")
        normalized["display_name"] = _decode_contact_text(normalized.get("display_name"))
        normalized["aliases"] = self._normalize_aliases(normalized.get("aliases"))
        normalized["favorite"] = bool(normalized.get("favorite"))
        normalized["relationship"] = _decode_contact_text(normalized.get("relationship"))
        normalized["source"] = _clean(normalized.get("source")) or "manual"
        normalized.setdefault("canonical_target", "")
        normalized.setdefault("raw_openclaw", {})
        normalized.setdefault("last_checked_at", _now_iso())
        return normalized

    def _load(self):
        if not self.storage_path.exists():
            self._save()
            return
        try:
            loaded = json.loads(self.storage_path.read_text(encoding="utf-8"))
            normalized_targets = [
                target for target in (self._normalize_loaded_target(item) for item in loaded)
                if target
            ] if isinstance(loaded, list) else []
            self._targets = normalized_targets
            if isinstance(loaded, list) and normalized_targets != loaded:
                self._save()
        except Exception:
            self._targets = []
            self._save()

    def _save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(self._targets, indent=2, ensure_ascii=False), encoding="utf-8")


openclaw_targets_manager = OpenClawTargetsManager()


def list_targets():
    return openclaw_targets_manager.list_targets()


def list_allowed_targets(channel=None, kind=None):
    return openclaw_targets_manager.list_allowed_targets(channel=channel, kind=kind)


def get_target(target_id):
    return openclaw_targets_manager.get_target(target_id)


def add_target(
    channel,
    kind,
    display_name,
    raw_target,
    canonical_target=None,
    resolved=False,
    allowed=False,
    raw_openclaw=None,
    aliases=None,
    favorite=False,
    relationship="",
    source="manual",
):
    return openclaw_targets_manager.add_target(
        channel,
        kind,
        display_name,
        raw_target,
        canonical_target=canonical_target,
        resolved=resolved,
        allowed=allowed,
        raw_openclaw=raw_openclaw,
        aliases=aliases,
        favorite=favorite,
        relationship=relationship,
        source=source,
    )


def update_target(target_id, **fields):
    return openclaw_targets_manager.update_target(target_id, **fields)


def delete_target(target_id):
    return openclaw_targets_manager.delete_target(target_id)


def mark_allowed(target_id, allowed=True):
    return openclaw_targets_manager.mark_allowed(target_id, allowed)


def add_alias(target_id, alias):
    return openclaw_targets_manager.add_alias(target_id, alias)


def remove_alias(target_id, alias):
    return openclaw_targets_manager.remove_alias(target_id, alias)


def find_by_display_name(channel, display_name):
    return openclaw_targets_manager.find_by_display_name(channel, display_name)


def find_by_canonical_target(channel, canonical_target):
    return openclaw_targets_manager.find_by_canonical_target(channel, canonical_target)


def find_by_alias(channel, alias):
    return openclaw_targets_manager.find_by_alias(channel, alias)


def find_best_match(channel, query, kind=None):
    return openclaw_targets_manager.find_best_match(channel, query, kind=kind)


def upsert_contact(channel, display_name, phone, aliases=None, relationship="", favorite=False, source="manual"):
    return openclaw_targets_manager.upsert_contact(
        channel,
        display_name,
        phone,
        aliases=aliases,
        relationship=relationship,
        favorite=favorite,
        source=source,
    )


def upsert_from_inbound(incoming_message):
    return openclaw_targets_manager.upsert_from_inbound(incoming_message)
