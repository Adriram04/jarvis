"""Evaluates automation conditions before the actions run.

Conditions are AND-evaluated. An empty list (or a single ``always``) always
passes. Providers are injected so this module stays decoupled from server.py and
easy to unit test: each provider is a callable that may return a value or an
awaitable.
"""

import inspect
from datetime import datetime


def _as_text(value):
    return str(value or "").strip()


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _first_str(*candidates):
    for candidate in candidates:
        text = _as_text(candidate)
        if text:
            return text
    return ""


def _extract_message(context):
    """Pull the inbound message text out of an event payload (best effort)."""
    if not isinstance(context, dict):
        return ""
    incoming = context.get("incoming") if isinstance(context.get("incoming"), dict) else {}
    stored = context.get("stored_message") if isinstance(context.get("stored_message"), dict) else {}
    message = context.get("message")
    message_text = message.get("message") if isinstance(message, dict) else message
    return _first_str(
        context.get("text"),
        message_text,
        incoming.get("message"),
        stored.get("message"),
        incoming.get("text"),
    )


def _extract_sender(context):
    if not isinstance(context, dict):
        return ""
    incoming = context.get("incoming") if isinstance(context.get("incoming"), dict) else {}
    target = context.get("target") if isinstance(context.get("target"), dict) else {}
    return _first_str(
        context.get("sender"),
        incoming.get("target"),
        incoming.get("display_target"),
        incoming.get("canonical_target"),
        target.get("id"),
        target.get("canonical"),
        target.get("display_name"),
    )


class ConditionEvaluator:
    """AND-evaluates a list of automation conditions against an event context."""

    def __init__(self, providers=None):
        self.providers = providers or {}

    async def evaluate(self, conditions, context=None):
        context = context or {}
        conditions = conditions if isinstance(conditions, list) else []
        if not conditions:
            return {"passed": True, "results": [], "summary": "Sin condiciones (always)."}

        results = []
        passed = True
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            condition_type = _as_text(condition.get("type")).lower()
            try:
                ok, detail = await self._evaluate_one(condition_type, condition, context)
            except Exception as exc:  # never let a condition crash the run
                ok, detail = False, f"error: {exc}"
            results.append({"type": condition_type, "passed": bool(ok), "detail": detail})
            if not ok:
                passed = False

        failed = [item["type"] for item in results if not item["passed"]]
        summary = "Condiciones cumplidas." if passed else f"Condiciones no cumplidas: {', '.join(failed)}."
        return {"passed": passed, "results": results, "summary": summary}

    # ----------------------------------------------------------- single check
    async def _evaluate_one(self, condition_type, condition, context):
        if condition_type in {"", "always"}:
            return True, "always"

        if condition_type == "message_contains":
            needles = condition.get("any") or condition.get("text") or condition.get("value")
            if isinstance(needles, str):
                needles = [needles]
            needles = [_as_text(n).lower() for n in (needles or []) if _as_text(n)]
            haystack = _extract_message(context).lower()
            if not needles:
                return False, "message_contains sin texto configurado"
            matched = next((n for n in needles if n in haystack), None)
            return bool(matched), f"match='{matched}'" if matched else "sin coincidencia"

        if condition_type == "sender_in_allowlist":
            sender = _extract_sender(context)
            provider = self.providers.get("is_sender_allowed")
            if not provider:
                return False, "proveedor allowlist no disponible"
            allowed = await _maybe_await(provider(sender))
            return bool(allowed), f"sender='{sender}' allowed={bool(allowed)}"

        if condition_type == "provider_connected":
            name = _as_text(condition.get("provider") or condition.get("name") or "openwa").lower()
            provider = self.providers.get("is_provider_connected")
            if not provider:
                return False, "proveedor de estado no disponible"
            connected = await _maybe_await(provider(name))
            return bool(connected), f"provider='{name}' connected={bool(connected)}"

        if condition_type == "time_between":
            return self._time_between(condition)

        if condition_type == "has_calendar_events":
            provider = self.providers.get("has_calendar_events")
            if not provider:
                return False, "proveedor de calendario no disponible"
            has_events = await _maybe_await(provider(condition))
            return bool(has_events), f"has_calendar_events={bool(has_events)}"

        if condition_type == "project_active":
            provider = self.providers.get("is_project_active")
            if not provider:
                return False, "proveedor de proyectos no disponible"
            active = await _maybe_await(provider(condition.get("project") or condition.get("name")))
            return bool(active), f"project_active={bool(active)}"

        if condition_type == "simulation_enabled":
            provider = self.providers.get("is_simulation_enabled")
            if not provider:
                return False, "proveedor de simulacion no disponible"
            enabled = await _maybe_await(provider())
            return bool(enabled), f"simulation_enabled={bool(enabled)}"

        return False, f"condicion desconocida: {condition_type}"

    def _time_between(self, condition):
        start = _as_text(condition.get("start") or "00:00")
        end = _as_text(condition.get("end") or "23:59")
        tz_name = _as_text(condition.get("timezone"))
        now = datetime.now()
        if tz_name:
            try:
                from zoneinfo import ZoneInfo

                now = datetime.now(ZoneInfo(tz_name))
            except Exception:
                now = datetime.now()
        current = now.hour * 60 + now.minute

        def _to_minutes(value, fallback):
            try:
                hh, mm = value.split(":")
                return int(hh) * 60 + int(mm)
            except Exception:
                return fallback

        start_minutes = _to_minutes(start, 0)
        end_minutes = _to_minutes(end, 24 * 60 - 1)
        if start_minutes <= end_minutes:
            ok = start_minutes <= current <= end_minutes
        else:  # window crosses midnight (e.g. 22:00 -> 06:00)
            ok = current >= start_minutes or current <= end_minutes
        return ok, f"now={now.strftime('%H:%M')} window={start}-{end} ok={ok}"
