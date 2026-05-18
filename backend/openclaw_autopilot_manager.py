import json
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock


ALLOWED_MODES = {"draft_only", "ask_before_send", "auto_send_limited"}
SENSITIVE_TERMS = {
    "contraseña",
    "password",
    "token",
    "api key",
    "apikey",
    "credencial",
    "credential",
    "secreto",
    "secret",
    "dni",
    "tarjeta",
    "bank",
    "banco",
}


def _now():
    return datetime.now(timezone.utc)


def _now_iso():
    return _now().isoformat(timespec="seconds")


class OpenClawAutopilotManager:
    """Manages bounded Jarvis autopilot rules delivered through OpenClaw."""

    def __init__(self, storage_path=None):
        base_dir = Path(__file__).resolve().parent
        self.storage_path = Path(storage_path) if storage_path else base_dir / "demo_state" / "openclaw_autopilot_rules.json"
        self._lock = Lock()
        self._rules = []
        self._load()

    def create_rule(self, channel, target, mode, trigger, behavior):
        mode = mode if mode in ALLOWED_MODES else "ask_before_send"
        rule = {
            "id": str(uuid.uuid4()),
            "enabled": True,
            "channel": str(channel or "").strip().lower(),
            "target": str(target or "").strip(),
            "mode": mode,
            "trigger": self._normalize_trigger(trigger),
            "behavior": self._normalize_behavior(behavior),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "reply_log": [],
        }
        with self._lock:
            self._rules.append(rule)
            self._save()
        return self._public_rule(rule)

    def list_rules(self):
        with self._lock:
            return [self._public_rule(rule) for rule in self._rules]

    def get_rule(self, rule_id):
        with self._lock:
            rule = self._find_rule(rule_id)
            return self._public_rule(rule) if rule else None

    def enable_rule(self, rule_id):
        return self._set_enabled(rule_id, True)

    def disable_rule(self, rule_id):
        return self._set_enabled(rule_id, False)

    def delete_rule(self, rule_id):
        with self._lock:
            for index, rule in enumerate(self._rules):
                if rule.get("id") == rule_id:
                    removed = self._rules.pop(index)
                    self._save()
                    return self._public_rule(removed)
        return None

    def find_matching_rules(self, incoming_message):
        with self._lock:
            matches = [
                self._public_rule(rule)
                for rule in self._rules
                if rule.get("enabled") and self._matches_rule(rule, incoming_message or {})
            ]
        return matches

    def should_auto_reply(self, rule, incoming_message):
        stored_rule = self._coerce_rule(rule)
        if not stored_rule or not stored_rule.get("enabled"):
            return False
        if stored_rule.get("mode") != "auto_send_limited":
            return False
        if not self._matches_rule(stored_rule, incoming_message or {}):
            return False
        if self._contains_sensitive_topic(stored_rule, incoming_message or {}):
            return False
        return not self._is_rate_limited(stored_rule)

    def register_reply(self, rule_id):
        with self._lock:
            rule = self._find_rule(rule_id)
            if not rule:
                return None
            cutoff = _now() - timedelta(hours=1)
            reply_log = [
                item for item in rule.get("reply_log", [])
                if self._parse_time(item) >= cutoff
            ]
            reply_log.append(_now_iso())
            rule["reply_log"] = reply_log
            rule["updated_at"] = _now_iso()
            self._save()
            return self._public_rule(rule)

    def _set_enabled(self, rule_id, enabled):
        with self._lock:
            rule = self._find_rule(rule_id)
            if not rule:
                return None
            rule["enabled"] = bool(enabled)
            rule["updated_at"] = _now_iso()
            self._save()
            return self._public_rule(rule)

    def _matches_rule(self, rule, incoming_message):
        channel = str(incoming_message.get("channel", "")).lower()
        target = str(incoming_message.get("target", ""))
        if rule.get("channel") and rule.get("channel") != channel:
            return False
        if rule.get("target") and rule.get("target").lower() != target.lower():
            return False

        trigger = rule.get("trigger", {})
        trigger_type = trigger.get("type", "manual")
        message_text = str(incoming_message.get("message", "")).lower()
        sender = str(incoming_message.get("sender", "")).lower()

        if trigger_type == "all_messages":
            return True
        if trigger_type == "keywords":
            return any(str(keyword).lower() in message_text for keyword in trigger.get("keywords", []))
        if trigger_type == "sender":
            return bool(trigger.get("sender")) and str(trigger.get("sender")).lower() == sender
        return False

    def _contains_sensitive_topic(self, rule, incoming_message):
        message_text = str(incoming_message.get("message", "")).lower()
        behavior = rule.get("behavior", {})

        forbidden_topics = {str(topic).lower() for topic in behavior.get("forbidden_topics", [])}
        if any(topic and topic in message_text for topic in forbidden_topics):
            return True
        if any(term in message_text for term in SENSITIVE_TERMS):
            return True

        allowed_topics = [str(topic).lower() for topic in behavior.get("allowed_topics", []) if topic]
        if allowed_topics and not any(topic in message_text for topic in allowed_topics):
            return True
        return False

    def _is_rate_limited(self, rule):
        behavior = rule.get("behavior", {})
        limit = int(behavior.get("max_messages_per_hour", 5) or 5)
        cutoff = _now() - timedelta(hours=1)
        recent = [
            item for item in rule.get("reply_log", [])
            if self._parse_time(item) >= cutoff
        ]
        return len(recent) >= max(0, limit)

    def _normalize_trigger(self, trigger):
        trigger = deepcopy(trigger or {})
        trigger_type = trigger.get("type", "manual")
        if trigger_type not in {"all_messages", "keywords", "sender", "manual"}:
            trigger_type = "manual"
        return {
            "type": trigger_type,
            "keywords": list(trigger.get("keywords") or []),
            "sender": trigger.get("sender"),
        }

    def _normalize_behavior(self, behavior):
        behavior = deepcopy(behavior or {})
        return {
            "instruction": behavior.get("instruction", "Responder de forma breve, educada y natural."),
            "max_messages_per_hour": int(behavior.get("max_messages_per_hour", 5) or 5),
            "allowed_topics": list(behavior.get("allowed_topics") or []),
            "forbidden_topics": list(behavior.get("forbidden_topics") or ["datos personales", "contraseñas", "temas sensibles"]),
            "require_confirmation_for_first_reply": bool(behavior.get("require_confirmation_for_first_reply", True)),
        }

    def _coerce_rule(self, rule):
        if not rule:
            return None
        rule_id = rule.get("id") if isinstance(rule, dict) else rule
        stored = self._find_rule(rule_id)
        return stored or (rule if isinstance(rule, dict) else None)

    def _find_rule(self, rule_id):
        for rule in self._rules:
            if rule.get("id") == rule_id:
                return rule
        return None

    def _public_rule(self, rule):
        if not rule:
            return None
        public = deepcopy(rule)
        reply_log = public.get("reply_log", [])
        cutoff = _now() - timedelta(hours=1)
        public["reply_count_total"] = len(reply_log)
        public["reply_count_last_hour"] = len([
            item for item in reply_log
            if self._parse_time(item) >= cutoff
        ])
        public.pop("reply_log", None)
        return public

    def _parse_time(self, value):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return datetime.fromtimestamp(0, timezone.utc)

    def _load(self):
        if not self.storage_path.exists():
            self._save()
            return
        try:
            loaded = json.loads(self.storage_path.read_text(encoding="utf-8"))
            self._rules = loaded if isinstance(loaded, list) else []
        except Exception:
            self._rules = []
            self._save()

    def _save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(self._rules, indent=2, ensure_ascii=False), encoding="utf-8")


openclaw_autopilot_manager = OpenClawAutopilotManager()
