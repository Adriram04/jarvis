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
ALLOWED_TRIGGER_TYPES = {"manual", "once", "daily", "interval", "event"}


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


def _workflow_steps(workflow):
    if isinstance(workflow, list):
        return workflow
    if isinstance(workflow, dict):
        steps = workflow.get("steps")
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


class AutomationManager:
    """Stores scheduled Jarvis automations and computes their next run."""

    def __init__(self, storage_path=None, seed_examples=True):
        base_dir = Path(__file__).resolve().parent
        self.storage_path = Path(storage_path) if storage_path else base_dir / "demo_state" / "automations.json"
        self._lock = Lock()
        self._automations = []
        self._load(seed_examples=seed_examples)

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
                "trigger": data.get("trigger") or {},
                "workflow": data.get("workflow") or {"steps": []},
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
                if self._trigger_type(trigger) != "event":
                    continue
                if str(trigger.get("event_type") or "").strip() != event_type:
                    continue
                if not self._event_filters_match(trigger.get("filters") or {}, payload):
                    continue
                matches.append(deepcopy(automation))
        return matches

    def validate_automation_payload(self, data):
        data = data or {}
        errors = []

        if not str(data.get("name") or "").strip():
            errors.append("Automation name is required.")

        trigger = data.get("trigger") or {}
        if not isinstance(trigger, dict):
            errors.append("Trigger must be an object.")
            trigger = {}

        trigger_type = str(trigger.get("type") or "manual").strip().lower()
        if trigger_type not in ALLOWED_TRIGGER_TYPES:
            errors.append(f"Unsupported trigger type: {trigger_type}.")

        if trigger_type == "once" and not _parse_datetime(trigger.get("run_at")):
            errors.append("Trigger once requires a valid run_at datetime.")

        if trigger_type == "daily":
            hour = trigger.get("hour", 9)
            minute = trigger.get("minute", 0)
            if not _is_int(hour) or not 0 <= int(hour) <= 23:
                errors.append("Trigger daily requires hour between 0 and 23.")
            if not _is_int(minute) or not 0 <= int(minute) <= 59:
                errors.append("Trigger daily requires minute between 0 and 59.")

        if trigger_type == "interval":
            minutes = trigger.get("minutes", 60)
            if not _is_int(minutes) or int(minutes) < 1:
                errors.append("Trigger interval requires minutes >= 1.")

        if trigger_type == "event":
            if not str(trigger.get("event_type") or "").strip():
                errors.append("Trigger event requires event_type.")
            if trigger.get("filters") is not None and not isinstance(trigger.get("filters"), dict):
                errors.append("Trigger event filters must be an object.")

        steps = _workflow_steps(data.get("workflow"))
        if not steps:
            errors.append("Workflow must include at least one step.")
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"Workflow step {index + 1} must be an object.")
                continue
            if not str(step.get("action_type") or "").strip():
                errors.append(f"Workflow step {index + 1} requires action_type.")
            if step.get("payload") is not None and not isinstance(step.get("payload"), dict):
                errors.append(f"Workflow step {index + 1} payload must be an object.")

        return {"valid": not errors, "errors": errors}

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
                if self._trigger_type(automation.get("trigger")) == "once":
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

    def calculate_next_run(self, trigger, last_run_at=None, enabled=True, now=None):
        if not enabled:
            return None

        now = now or _now()
        trigger = trigger or {}
        trigger_type = self._trigger_type(trigger)

        if trigger_type == "manual":
            return None

        if trigger_type == "event":
            return None

        if trigger_type == "once":
            if last_run_at:
                return None
            run_at = _parse_datetime(trigger.get("run_at"))
            return _iso(run_at) if run_at else None

        if trigger_type == "daily":
            hour = _clean_int(trigger.get("hour"), default=9, minimum=0, maximum=23)
            minute = _clean_int(trigger.get("minute"), default=0, minimum=0, maximum=59)
            tz = _timezone(trigger.get("timezone") or DEFAULT_DAILY_TIMEZONE)
            local_now = now.astimezone(tz)
            last_run = _parse_datetime(last_run_at)
            last_local = last_run.astimezone(tz) if last_run else None
            candidate_date = local_now.date()
            if last_local and last_local.date() > candidate_date:
                candidate_date = last_local.date()
            candidate = datetime.combine(candidate_date, datetime_time(hour, minute), tzinfo=tz)
            if last_local and candidate <= last_local:
                candidate = candidate + timedelta(days=1)
            while candidate <= local_now:
                candidate = candidate + timedelta(days=1)
            return _iso(candidate)

        if trigger_type == "interval":
            minutes = _clean_int(trigger.get("minutes"), default=60, minimum=1)
            base = _parse_datetime(last_run_at) or now
            candidate = base + timedelta(minutes=minutes)
            return _iso(candidate)

        return None

    def _normalize_automation(self, automation, recompute_next=False):
        now_iso = _iso(_now())
        automation = deepcopy(automation or {})
        automation["id"] = str(automation.get("id") or uuid.uuid4())
        automation["name"] = str(automation.get("name") or "Automatizacion sin nombre").strip()
        automation["trigger"] = self._normalize_trigger(automation.get("trigger"))
        automation["workflow"] = self._normalize_workflow(automation.get("workflow"))
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
        trigger_type = self._trigger_type(trigger)
        normalized = {"type": trigger_type}
        if trigger_type == "once":
            normalized["run_at"] = _iso(_parse_datetime(trigger.get("run_at"))) if trigger.get("run_at") else None
        elif trigger_type == "daily":
            normalized["hour"] = _clean_int(trigger.get("hour"), default=9, minimum=0, maximum=23)
            normalized["minute"] = _clean_int(trigger.get("minute"), default=0, minimum=0, maximum=59)
            normalized["timezone"] = str(trigger.get("timezone") or DEFAULT_DAILY_TIMEZONE).strip() or DEFAULT_DAILY_TIMEZONE
        elif trigger_type == "interval":
            normalized["minutes"] = _clean_int(trigger.get("minutes"), default=60, minimum=1)
        elif trigger_type == "event":
            normalized["event_type"] = str(trigger.get("event_type") or "").strip()
            normalized["filters"] = deepcopy(trigger.get("filters")) if isinstance(trigger.get("filters"), dict) else {}
        return normalized

    def _normalize_workflow(self, workflow):
        if isinstance(workflow, list):
            steps = workflow
        elif isinstance(workflow, dict):
            steps = workflow.get("steps") or []
        else:
            steps = []

        normalized_steps = []
        for step in steps:
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
        return {"steps": normalized_steps}

    def _trigger_type(self, trigger):
        trigger_type = str((trigger or {}).get("type") or "manual").strip().lower()
        if trigger_type not in ALLOWED_TRIGGER_TYPES:
            return "manual"
        return trigger_type

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
        now_iso = _iso(_now())
        examples = [
            {
                "id": str(uuid.uuid4()),
                "name": "Resumen diario del calendario",
                "trigger": {"type": "daily", "hour": 9, "minute": 0, "timezone": DEFAULT_DAILY_TIMEZONE},
                "workflow": {
                    "steps": [
                        {
                            "action_type": "list_calendar_events",
                            "payload": {"max_results": 10},
                            "human_summary": "Consultar los proximos eventos del calendario.",
                            "stop_on_error": True,
                        }
                    ]
                },
                "enabled": True,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Workflow manual calendario",
                "trigger": {"type": "manual"},
                "workflow": {
                    "steps": [
                        {
                            "action_type": "list_calendar_events",
                            "payload": {"max_results": 5},
                            "human_summary": "Listar los proximos eventos del calendario.",
                            "stop_on_error": True,
                        }
                    ]
                },
                "enabled": False,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Responder a mensaje inbound de OpenClaw",
                "trigger": {"type": "event", "event_type": "openclaw.inbound_message", "filters": {}},
                "workflow": {
                    "steps": [
                        {
                            "action_type": "draft_content",
                            "payload": {"content": "Preparar respuesta segura al mensaje inbound."},
                            "human_summary": "Crear borrador seguro para revisar antes de responder.",
                            "stop_on_error": True,
                        }
                    ]
                },
                "enabled": False,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Alerta ante deepfake sospechado",
                "trigger": {"type": "event", "event_type": "camera.deepfake_suspected", "filters": {}},
                "workflow": {
                    "steps": [
                        {
                            "action_type": "draft_content",
                            "payload": {"content": "Posible deepfake detectado. Revisar manualmente antes de continuar."},
                            "human_summary": "Preparar aviso interno sin ejecutar acciones sensibles.",
                            "stop_on_error": True,
                        },
                    ]
                },
                "enabled": False,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Comprobacion de estado cada 60 minutos",
                "trigger": {"type": "interval", "minutes": 60},
                "workflow": {
                    "steps": [
                        {
                            "action_type": "check_status",
                            "payload": {},
                            "human_summary": "Comprobar el estado del gateway de integraciones.",
                            "stop_on_error": False,
                        }
                    ]
                },
                "enabled": False,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        ]
        return [self._normalize_automation(item, recompute_next=True) for item in examples]
