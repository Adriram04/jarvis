from datetime import datetime, timedelta, timezone

import pytest

from automation_manager import AutomationManager


def _workflow():
    return {
        "steps": [
            {
                "action_type": "check_status",
                "payload": {},
                "human_summary": "Check integration status.",
                "stop_on_error": True,
            }
        ]
    }


def test_daily_next_run_uses_madrid_timezone(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    now = datetime(2026, 6, 1, 6, 30, tzinfo=timezone.utc)

    next_run = manager.calculate_next_run({"type": "daily", "hour": 9, "minute": 0}, now=now)

    assert next_run == "2026-06-01T07:00:00+00:00"


def test_once_runs_only_once(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    automation = manager.create_automation(
        {
            "name": "One shot",
            "trigger": {"type": "once", "run_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()},
            "workflow": _workflow(),
        }
    )

    updated = manager.mark_run(automation["id"], result={"success": True, "status": "completed", "summary": "Done"})

    assert updated["enabled"] is False
    assert updated["next_run_at"] is None
    assert updated["run_count"] == 1
    assert updated["last_result_status"] == "completed"


def test_interval_next_run_is_calculated_from_last_run(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    last_run = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    next_run = manager.calculate_next_run(
        {"type": "interval", "minutes": 60},
        last_run_at=last_run.isoformat(),
        now=now,
    )

    assert next_run == "2026-06-01T11:00:00+00:00"


def test_due_automations_skip_running_items(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    automation = manager.create_automation(
        {
            "name": "Due once",
            "trigger": {"type": "once", "run_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()},
            "workflow": _workflow(),
        }
    )

    assert [item["id"] for item in manager.due_automations()] == [automation["id"]]

    claimed, state = manager.claim_automation_for_run(automation["id"])

    assert state == "claimed"
    assert claimed["running"] is True
    assert manager.due_automations() == []


def test_automations_for_event_matches_type_and_filters(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    automation = manager.create_automation(
        {
            "name": "Inbound messages",
            "trigger": {
                "type": "event",
                "event_type": "openclaw.inbound_message",
                "filters": {"incoming.channel": "whatsapp"},
            },
            "workflow": _workflow(),
        }
    )

    matches = manager.automations_for_event(
        "openclaw.inbound_message",
        {"incoming": {"channel": "whatsapp"}},
    )

    assert [item["id"] for item in matches] == [automation["id"]]
    assert manager.automations_for_event("openclaw.inbound_message", {"incoming": {"channel": "email"}}) == []


def test_claim_and_release_running_state(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    automation = manager.create_automation(
        {"name": "Manual", "trigger": {"type": "manual"}, "workflow": _workflow()}
    )

    _, first_state = manager.claim_automation_for_run(automation["id"])
    running, second_state = manager.claim_automation_for_run(automation["id"])

    assert first_state == "claimed"
    assert second_state == "already_running"
    assert running["running"] is True

    released = manager.release_automation_run(automation["id"])

    assert released["running"] is False
    assert released["running_since"] is None


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"name": "", "trigger": {"type": "manual"}, "workflow": _workflow()}, "name"),
        ({"name": "Bad", "trigger": {"type": "interval", "minutes": 0}, "workflow": _workflow()}, "minutes"),
        ({"name": "Bad", "trigger": {"type": "event"}, "workflow": _workflow()}, "event_type"),
        ({"name": "Bad", "trigger": {"type": "manual"}, "workflow": {"steps": []}}, "Workflow"),
        ({"name": "Bad", "trigger": {"type": "manual"}, "workflow": {"steps": [{"payload": {}}]}}, "action_type"),
    ],
)
def test_validation_rejects_invalid_payloads(tmp_path, payload, error):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    validation = manager.validate_automation_payload(payload)

    assert validation["valid"] is False
    assert any(error in item for item in validation["errors"])


# --------------------------------------------------------------- new spec model
def _actions():
    return [
        {"action_type": "summarize_day", "payload": {}, "human_summary": "Resumen.", "stop_on_error": False}
    ]


def test_spec_model_round_trips_description_conditions_actions_safety(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    automation = manager.create_automation(
        {
            "name": "Resumen diario",
            "description": "Lee la agenda cada manana.",
            "trigger": {"type": "schedule", "schedule": {"kind": "daily", "hour": 9, "minute": 0}},
            "conditions": [{"type": "has_calendar_events"}],
            "actions": _actions(),
            "safety": {"requires_confirmation": "always", "sensitive": True},
        }
    )

    assert automation["description"] == "Lee la agenda cada manana."
    assert automation["trigger"]["type"] == "schedule"
    assert automation["trigger"]["schedule"]["kind"] == "daily"
    assert automation["conditions"][0]["type"] == "has_calendar_events"
    assert automation["actions"][0]["action_type"] == "summarize_day"
    assert automation["safety"]["requires_confirmation"] == "always"
    # Backwards-compatible alias consumed by WorkflowManager.
    assert automation["workflow"]["steps"][0]["action_type"] == "summarize_day"


def test_event_name_trigger_matches_event(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    automation = manager.create_automation(
        {
            "name": "WhatsApp urgente",
            "trigger": {"type": "whatsapp.message_received", "filters": {"incoming.channel": "whatsapp"}},
            "actions": _actions(),
        }
    )
    assert automation["trigger"]["type"] == "whatsapp.message_received"

    matches = manager.automations_for_event("whatsapp.message_received", {"incoming": {"channel": "whatsapp"}})
    assert [item["id"] for item in matches] == [automation["id"]]
    assert manager.automations_for_event("whatsapp.message_received", {"incoming": {"channel": "email"}}) == []


def test_schedule_once_disables_after_run(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    automation = manager.create_automation(
        {
            "name": "One shot spec",
            "trigger": {"type": "schedule", "schedule": {"kind": "once", "run_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}},
            "actions": _actions(),
        }
    )
    updated = manager.mark_run(automation["id"], result={"success": True, "status": "completed"})
    assert updated["enabled"] is False
    assert updated["next_run_at"] is None


def test_weekly_next_run_lands_on_requested_weekday(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    # 2026-06-01 is a Monday (weekday 0). Ask for Wednesday (weekday 2) at 08:00 UTC.
    now = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
    next_run = manager.calculate_next_run(
        {"type": "schedule", "schedule": {"kind": "weekly", "weekday": 2, "hour": 8, "minute": 0, "timezone": "UTC"}},
        now=now,
    )
    parsed = datetime.fromisoformat(next_run)
    assert parsed.weekday() == 2


def test_invalid_safety_policy_falls_back_to_auto(tmp_path):
    manager = AutomationManager(tmp_path / "automations.json", seed_examples=False)
    automation = manager.create_automation(
        {
            "name": "Safety fallback",
            "trigger": {"type": "manual"},
            "actions": _actions(),
            "safety": {"requires_confirmation": "weird"},
        }
    )
    assert automation["safety"]["requires_confirmation"] == "auto"
