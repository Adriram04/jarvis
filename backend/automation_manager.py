import json
import uuid
from copy import deepcopy
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from threading import Lock

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python fallback for unusual runtimes.
    ZoneInfo = None


DEFAULT_DAILY_TIMEZONE = "Europe/Madrid"

# Schedule kinds (time based triggers) handled by the scheduler loop.
SCHEDULE_KINDS = {"daily", "weekly", "once", "interval"}

# Trigger.type values accepted as canonical event names. Event triggers can use
# any dotted name, but these are the first-class ones surfaced in the UI.
KNOWN_EVENT_TRIGGERS = {
    "system.startup",
    "whatsapp.message_received",
    "openwa.connected",
    "calendar.event_upcoming",
    "printer.finished",
    "pending_action.created",
    "openclaw.inbound_message",
}

# Safety confirmation policies for the whole automation.
SAFETY_POLICIES = {"auto", "always", "never"}

# Condition types understood by the ConditionEvaluator.
KNOWN_CONDITION_TYPES = {
    "always",
    "message_contains",
    "sender_in_allowlist",
    "provider_connected",
    "time_between",
    "has_calendar_events",
    "project_active",
    "simulation_enabled",
}


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _clean_int(value, default=0, minimum=None, maximum=None):
    try:
        number = int(value)
    except Exception:
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _is_int(value):
    try:
        if isinstance(value, bool):
            return False
        int(value)
        return True
    except Exception:
        return False


def _timezone(name=None):
    if ZoneInfo:
        try:
            return ZoneInfo(str(name or DEFAULT_DAILY_TIMEZONE))
        except Exception:
            return ZoneInfo(DEFAULT_DAILY_TIMEZONE)
    return datetime.now().astimezone().tzinfo or timezone.utc


def _action_steps(source):
    """Extract a list of step dicts from either an ``actions`` list or a legacy
    ``workflow`` object/list."""
    if isinstance(source, list):
        return source
    if isinstance(source, dict):
        steps = source.get("steps")
        return steps if isinstance(steps, list) else []
    return []


def _nested_value(payload, key):
    current = payload
    for part in str(key or "").split("."):
        if isinstance(current, dict) and part in current:
            current = current.get(part)
        else:
            return None
    return current


def _result_field(result, key):
    if not isinstance(result, dict):
        return None
    if result.get(key) is not None:
        return result.get(key)
    nested = result.get("result")
    if isinstance(nested, dict):
        return nested.get(key)
    return None


def _classify_trigger(trigger):
    """Return ``(category, detail)`` where category is one of ``manual``,
    ``schedule`` or ``event``.

    Accepts both the new spec model (``{"type": "schedule", "schedule": {...}}``
    and event-name types such as ``{"type": "whatsapp.message_received"}``) and
    the legacy model (``{"type": "daily"}``, ``{"type": "event", "event_type": ...}``).
    """
    raw = str((trigger or {}).get("type") or "manual").strip().lower()
    if raw == "manual":
        return "manual", None
    if raw == "schedule":
        kind = str((trigger.get("schedule") or {}).get("kind") or "daily").strip().lower()
        return "schedule", kind if kind in SCHEDULE_KINDS else "daily"
    if raw in SCHEDULE_KINDS:  # legacy: daily/once/interval/weekly at top level
        return "schedule", raw
    if raw == "event":  # legacy generic event with event_type field
        return "event", str(trigger.get("event_type") or "").strip()
    # Event-name trigger, e.g. whatsapp.message_received / camera.deepfake_suspected
    return "event", raw


def _schedule_params(trigger):
    """Where schedule parameters live: nested under ``schedule`` for the new model
    or at the top level for the legacy model."""
    if str((trigger or {}).get("type") or "").strip().lower() == "schedule":
        nested = trigger.get("schedule")
        return nested if isinstance(nested, dict) else {}
    return trigger or {}


class AutomationManager:
    """Stores Jarvis automations (event -> conditions -> actions) and computes
    the next run for time based triggers."""

    def __init__(self, storage_path=None, seed_examples=True):
        base_dir = Path(__file__).resolve().parent
        self.storage_path = Path(storage_path) if storage_path else base_dir / "demo_state" / "automations.json"
        self._lock = Lock()
        self._automations = []
        self._load(seed_examples=seed_examples)

    # ------------------------------------------------------------------ reads
    def list_automations(self):
        with self._lock:
            return deepcopy(sorted(self._automations, key=lambda item: item.get("created_at") or ""))

    def get_automation(self, automation_id):
        automation_id = str(automation_id or "").strip()
        with self._lock:
            for automation in self._automations:
                if automation.get("id") == automation_id:
                    return deepcopy(automation)
        return None

    # ----------------------------------------------------------------- writes
    def create_automation(self, data):
        data = data or {}
        validation = self.validate_automation_payload(data)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))

        now_iso = _iso(_now())
        automation = self._normalize_automation(
            {
                "id": str(uuid.uuid4()),
                "name": data.get("name"),
                "description": data.get("description"),
                "trigger": data.get("trigger") or {},
                "conditions": data.get("conditions"),
                "actions": data.get("actions"),
                "workflow": data.get("workflow"),
                "safety": data.get("safety"),
                "enabled": bool(data.get("enabled", True)),
                "created_at": now_iso,
                "updated_at": now_iso,
                "last_run_at": data.get("last_run_at"),
                "next_run_at": data.get("next_run_at"),
                "run_count": data.get("run_count", 0),
            },
            recompute_next=True,
        )
        with self._lock:
            self._automations.append(automation)
            self._save()
        return deepcopy(automation)

    def update_automation(self, automation_id, data):
        automation_id = str(automation_id or "").strip()
        data = data or {}
        with self._lock:
            for index, current in enumerate(self._automations):
                if current.get("id") != automation_id:
                    continue
                updated = {**current, **data, "id": current.get("id"), "updated_at": _iso(_now())}
                validation = self.validate_automation_payload(updated)
                if not validation["valid"]:
                    raise ValueError("; ".join(validation["errors"]))
                should_recompute = any(key in data for key in ("trigger", "enabled", "last_run_at", "next_run_at"))
                self._automations[index] = self._normalize_automation(updated, recompute_next=should_recompute)
                self._save()
                return deepcopy(self._automations[index])
        return None

    def delete_automation(self, automation_id):
        automation_id = str(automation_id or "").strip()
        with self._lock:
            for index, automation in enumerate(self._automations):
                if automation.get("id") == automation_id:
                    removed = self._automations.pop(index)
                    self._save()
                    return deepcopy(removed)
        return None

    # -------------------------------------------------------------- selection
    def due_automations(self, now=None):
        now = now or _now()
        due = []
        with self._lock:
            for automation in self._automations:
                if not automation.get("enabled"):
                    continue
                if automation.get("running"):
                    continue
                next_run = _parse_datetime(automation.get("next_run_at"))
                if next_run and next_run <= now:
                    due.append(deepcopy(automation))
        return due

    def automations_for_event(self, event_type, payload=None):
        event_type = str(event_type or "").strip()
        payload = payload or {}
        matches = []
        with self._lock:
            for automation in self._automations:
                trigger = automation.get("trigger") or {}
                if not automation.get("enabled"):
                    continue
                category, detail = _classify_trigger(trigger)
                if category != "event":
                    continue
                if str(detail or "").strip() != event_type:
                    continue
                if not self._event_filters_match(trigger.get("filters") or {}, payload):
                    continue
                matches.append(deepcopy(automation))
        return matches

    # -------------------------------------------------------------- validation
    def validate_automation_payload(self, data):
        data = data or {}
        errors = []

        if not str(data.get("name") or "").strip():
            errors.append("Automation name is required.")

        trigger = data.get("trigger") or {}
        if not isinstance(trigger, dict):
            errors.append("Trigger must be an object.")
            trigger = {}

        category, detail = _classify_trigger(trigger)
        params = _schedule_params(trigger)

        if category == "schedule":
            kind = detail
            if kind == "once" and not _parse_datetime(params.get("run_at")):
                errors.append("Trigger once requires a valid run_at datetime.")
            if kind in {"daily", "weekly"}:
                hour = params.get("hour", 9)
                minute = params.get("minute", 0)
                if not _is_int(hour) or not 0 <= int(hour) <= 23:
                    errors.append("Trigger schedule requires hour between 0 and 23.")
                if not _is_int(minute) or not 0 <= int(minute) <= 59:
                    errors.append("Trigger schedule requires minute between 0 and 59.")
            if kind == "weekly":
                weekday = params.get("weekday", 0)
                if not _is_int(weekday) or not 0 <= int(weekday) <= 6:
                    errors.append("Trigger weekly requires weekday between 0 (Mon) and 6 (Sun).")
            if kind == "interval":
                minutes = params.get("minutes", 60)
                if not _is_int(minutes) or int(minutes) < 1:
                    errors.append("Trigger interval requires minutes >= 1.")
        elif category == "event":
            if not str(detail or "").strip():
                errors.append("Trigger event requires event_type.")
            if trigger.get("filters") is not None and not isinstance(trigger.get("filters"), dict):
                errors.append("Trigger event filters must be an object.")

        # Conditions (optional, AND-evaluated). Empty == always.
        conditions = data.get("conditions")
        if conditions is not None:
            if not isinstance(conditions, list):
                errors.append("Conditions must be a list.")
            else:
                for index, condition in enumerate(conditions):
                    if not isinstance(condition, dict):
                        errors.append(f"Condition {index + 1} must be an object.")
                        continue
                    if not str(condition.get("type") or "").strip():
                        errors.append(f"Condition {index + 1} requires a type.")

        # Actions (aka workflow steps).
        steps = data.get("actions")
        if steps is None:
            steps = _action_steps(data.get("workflow"))
        if not isinstance(steps, list) or not steps:
            errors.append("Workflow (actions) requires at least one action.")
            steps = steps if isinstance(steps, list) else []
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"Action {index + 1} must be an object.")
                continue
            if not str(step.get("action_type") or "").strip():
                errors.append(f"Action {index + 1} requires action_type.")
            if step.get("payload") is not None and not isinstance(step.get("payload"), dict):
                errors.append(f"Action {index + 1} payload must be an object.")

        safety = data.get("safety")
        if safety is not None and not isinstance(safety, dict):
            errors.append("Safety must be an object.")

        return {"valid": not errors, "errors": errors}

    # --------------------------------------------------------------- run state
    def claim_automation_for_run(self, automation_id):
        automation_id = str(automation_id or "").strip()
        with self._lock:
            for automation in self._automations:
                if automation.get("id") != automation_id:
                    continue
                if automation.get("running"):
                    return deepcopy(automation), "already_running"
                automation["running"] = True
                automation["running_since"] = _iso(_now())
                automation["updated_at"] = _iso(_now())
                self._save()
                return deepcopy(automation), "claimed"
        return None, "not_found"

    def release_automation_run(self, automation_id):
        automation_id = str(automation_id or "").strip()
        with self._lock:
            for automation in self._automations:
                if automation.get("id") != automation_id:
                    continue
                automation["running"] = False
                automation["running_since"] = None
                automation["updated_at"] = _iso(_now())
                self._save()
                return deepcopy(automation)
        return None

    async def execute_automation(self, automation_id, workflow_manager, source="manual"):
        automation, claim_state = self.claim_automation_for_run(automation_id)
        if claim_state == "not_found":
            return {
                "success": False,
                "status": "not_found",
                "error": "Automation not found.",
                "automation_id": automation_id,
            }
        if claim_state == "already_running":
            return {
                "success": False,
                "status": "skipped_already_running",
                "automation": automation,
                "automation_id": automation_id,
            }

        try:
            result = await workflow_manager.execute_workflow(
                automation.get("workflow") or {},
                automation={**automation, "source": source},
            )
            updated = self.mark_run(automation_id, result=result)
            return {
                "success": bool(result.get("success")),
                "status": result.get("status"),
                "automation": updated,
                "result": result,
            }
        finally:
            self.release_automation_run(automation_id)

    def mark_run(self, automation_id, result=None, ran_at=None):
        automation_id = str(automation_id or "").strip()
        ran_at_dt = _parse_datetime(ran_at) if ran_at else _now()
        ran_at_dt = ran_at_dt or _now()
        with self._lock:
            for index, automation in enumerate(self._automations):
                if automation.get("id") != automation_id:
                    continue
                automation["last_run_at"] = _iso(ran_at_dt)
                automation["updated_at"] = _iso(_now())
                automation["running"] = False
                automation["running_since"] = None
                automation["run_count"] = _clean_int(automation.get("run_count"), default=0, minimum=0) + 1
                status = _result_field(result, "status")
                summary = _result_field(result, "summary")
                error = _result_field(result, "error")
                success = _result_field(result, "success")
                if not status:
                    status = "completed" if success else "failed"
                automation["last_result_status"] = str(status or "").strip() or None
                automation["last_result_summary"] = str(summary or error or "").strip() or None
                automation["last_error"] = str(error or summary or "").strip() if success is False and status != "waiting_for_confirmation" else None
                category, kind = _classify_trigger(automation.get("trigger"))
                if category == "schedule" and kind == "once":
                    automation["enabled"] = False
                    automation["next_run_at"] = None
                else:
                    automation["next_run_at"] = self.calculate_next_run(
                        automation.get("trigger") or {},
                        last_run_at=automation.get("last_run_at"),
                        enabled=automation.get("enabled"),
                    )
                automation["last_result"] = deepcopy(result or {})
                self._automations[index] = automation
                self._save()
                return deepcopy(automation)
        return None

    # ---------------------------------------------------------------- schedule
    def calculate_next_run(self, trigger, last_run_at=None, enabled=True, now=None):
        if not enabled:
            return None

        now = now or _now()
        trigger = trigger or {}
        category, kind = _classify_trigger(trigger)

        if category in {"manual", "event"}:
            return None

        params = _schedule_params(trigger)

        if kind == "once":
            if last_run_at:
                return None
            run_at = _parse_datetime(params.get("run_at"))
            return _iso(run_at) if run_at else None

        if kind == "interval":
            minutes = _clean_int(params.get("minutes"), default=60, minimum=1)
            base = _parse_datetime(last_run_at) or now
            return _iso(base + timedelta(minutes=minutes))

        if kind in {"daily", "weekly"}:
            hour = _clean_int(params.get("hour"), default=9, minimum=0, maximum=23)
            minute = _clean_int(params.get("minute"), default=0, minimum=0, maximum=59)
            tz = _timezone(params.get("timezone") or DEFAULT_DAILY_TIMEZONE)
            local_now = now.astimezone(tz)
            last_run = _parse_datetime(last_run_at)
            last_local = last_run.astimezone(tz) if last_run else None

            candidate_date = local_now.date()
            if last_local and last_local.date() > candidate_date:
                candidate_date = last_local.date()
            candidate = datetime.combine(candidate_date, datetime_time(hour, minute), tzinfo=tz)

            if kind == "weekly":
                target_weekday = _clean_int(params.get("weekday"), default=0, minimum=0, maximum=6)
                days_ahead = (target_weekday - candidate.weekday()) % 7
                candidate = candidate + timedelta(days=days_ahead)
                while candidate <= local_now or (last_local and candidate <= last_local):
                    candidate = candidate + timedelta(days=7)
                return _iso(candidate)

            if last_local and candidate <= last_local:
                candidate = candidate + timedelta(days=1)
            while candidate <= local_now:
                candidate = candidate + timedelta(days=1)
            return _iso(candidate)

        return None

    # -------------------------------------------------------------- normalize
    def _normalize_automation(self, automation, recompute_next=False):
        now_iso = _iso(_now())
        automation = deepcopy(automation or {})
        automation["id"] = str(automation.get("id") or uuid.uuid4())
        automation["name"] = str(automation.get("name") or "Automatizacion sin nombre").strip()
        automation["description"] = str(automation.get("description") or "").strip()
        automation["trigger"] = self._normalize_trigger(automation.get("trigger"))
        automation["conditions"] = self._normalize_conditions(automation.get("conditions"))
        actions = self._normalize_actions(
            automation.get("actions") if automation.get("actions") is not None else automation.get("workflow")
        )
        automation["actions"] = actions
        # Backwards/forwards-compatible alias consumed by WorkflowManager.
        automation["workflow"] = {"steps": deepcopy(actions)}
        automation["safety"] = self._normalize_safety(automation.get("safety"))
        automation["enabled"] = bool(automation.get("enabled", True))
        automation["created_at"] = automation.get("created_at") or now_iso
        automation["updated_at"] = automation.get("updated_at") or now_iso
        automation["last_run_at"] = automation.get("last_run_at") or None
        automation["running"] = bool(automation.get("running", False))
        automation["running_since"] = automation.get("running_since") or None
        automation["run_count"] = _clean_int(automation.get("run_count"), default=0, minimum=0)
        automation["last_result_status"] = automation.get("last_result_status") or None
        automation["last_result_summary"] = automation.get("last_result_summary") or None
        automation["last_error"] = automation.get("last_error") or None
        automation["last_result"] = deepcopy(automation.get("last_result") or {})
        if recompute_next or "next_run_at" not in automation:
            automation["next_run_at"] = self.calculate_next_run(
                automation["trigger"],
                last_run_at=automation.get("last_run_at"),
                enabled=automation.get("enabled"),
            )
        return automation

    def _normalize_trigger(self, trigger):
        trigger = dict(trigger or {})
        category, detail = _classify_trigger(trigger)

        if category == "manual":
            return {"type": "manual"}

        if category == "schedule":
            kind = detail
            params = _schedule_params(trigger)
            schedule = {"kind": kind}
            if kind == "once":
                schedule["run_at"] = _iso(_parse_datetime(params.get("run_at"))) if params.get("run_at") else None
            elif kind == "interval":
                schedule["minutes"] = _clean_int(params.get("minutes"), default=60, minimum=1)
            elif kind in {"daily", "weekly"}:
                schedule["hour"] = _clean_int(params.get("hour"), default=9, minimum=0, maximum=23)
                schedule["minute"] = _clean_int(params.get("minute"), default=0, minimum=0, maximum=59)
                schedule["timezone"] = str(params.get("timezone") or DEFAULT_DAILY_TIMEZONE).strip() or DEFAULT_DAILY_TIMEZONE
                if kind == "weekly":
                    schedule["weekday"] = _clean_int(params.get("weekday"), default=0, minimum=0, maximum=6)
            return {"type": "schedule", "schedule": schedule}

        # Event trigger: the canonical name lives directly in ``type``.
        event_type = str(detail or "").strip() or "event"
        return {
            "type": event_type,
            "filters": deepcopy(trigger.get("filters")) if isinstance(trigger.get("filters"), dict) else {},
        }

    def _normalize_conditions(self, conditions):
        if not isinstance(conditions, list):
            return []
        normalized = []
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            condition_type = str(condition.get("type") or "").strip()
            if not condition_type:
                continue
            entry = {"type": condition_type}
            for key, value in condition.items():
                if key == "type":
                    continue
                entry[key] = deepcopy(value)
            normalized.append(entry)
        return normalized

    def _normalize_actions(self, source):
        normalized_steps = []
        for step in _action_steps(source):
            if not isinstance(step, dict):
                continue
            action_type = str(step.get("action_type") or "").strip()
            if not action_type:
                continue
            normalized_steps.append(
                {
                    "action_type": action_type,
                    "payload": deepcopy(step.get("payload")) if isinstance(step.get("payload"), dict) else {},
                    "human_summary": str(step.get("human_summary") or "").strip(),
                    "stop_on_error": bool(step.get("stop_on_error", True)),
                }
            )
        return normalized_steps

    def _normalize_safety(self, safety):
        safety = safety if isinstance(safety, dict) else {}
        policy = str(safety.get("requires_confirmation") or "auto").strip().lower()
        if policy not in SAFETY_POLICIES:
            policy = "auto"
        return {
            "requires_confirmation": policy,
            "sensitive": bool(safety.get("sensitive", False)),
        }

    def _event_filters_match(self, filters, payload):
        if not filters:
            return True
        if not isinstance(payload, dict):
            return False
        for key, expected in filters.items():
            actual = _nested_value(payload, key)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif isinstance(expected, dict):
                if not isinstance(actual, dict):
                    return False
                for nested_key, nested_expected in expected.items():
                    if actual.get(nested_key) != nested_expected:
                        return False
            elif actual != expected:
                return False
        return True

    # ------------------------------------------------------------- persistence
    def _load(self, seed_examples=True):
        if not self.storage_path.exists():
            self._automations = self._default_automations() if seed_examples else []
            self._save()
            return

        try:
            loaded = json.loads(self.storage_path.read_text(encoding="utf-8"))
            items = loaded if isinstance(loaded, list) else loaded.get("automations", [])
            self._automations = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                automation = self._normalize_automation(item, recompute_next=not item.get("next_run_at"))
                automation["running"] = False
                automation["running_since"] = None
                self._automations.append(automation)
            self._save()
        except Exception:
            self._automations = self._default_automations() if seed_examples else []
            self._save()

    def _save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps(self._automations, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _default_automations(self):
        try:
            from automation_templates import seed_automations
        except Exception:
            return []
        return [self._normalize_automation(item, recompute_next=True) for item in seed_automations()]
