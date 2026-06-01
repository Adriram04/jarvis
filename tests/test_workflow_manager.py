import asyncio

from workflow_manager import WorkflowManager


def test_workflow_accepts_list_and_injects_context():
    calls = []

    async def execute(action_type, payload, human_summary):
        calls.append((action_type, payload, human_summary))
        return {"success": True, "summary": f"ran {action_type}"}

    manager = WorkflowManager(execute)
    result = asyncio.run(
        manager.execute_workflow(
            [
                {"action_type": "first", "payload": {"value": 1}, "human_summary": "First"},
                {"action_type": "second", "payload": {}, "human_summary": "Second"},
            ],
            automation={"id": "auto-1", "source": "manual"},
        )
    )

    assert result["success"] is True
    assert result["status"] == "completed"
    assert calls[0][1]["_workflow_context"]["automation"]["id"] == "auto-1"
    assert calls[1][1]["_workflow_context"]["previous_steps"][0]["action_type"] == "first"


def test_workflow_stops_on_confirmation_required():
    async def execute(action_type, payload, human_summary):
        return {
            "success": False,
            "summary": "Needs confirmation.",
            "warnings": ["confirmation_required"],
            "raw": {"id": "pending-1"},
        }

    manager = WorkflowManager(execute)
    result = asyncio.run(
        manager.execute_workflow(
            {"steps": [{"action_type": "send_message", "payload": {}, "stop_on_error": True}]}
        )
    )

    assert result["status"] == "waiting_for_confirmation"
    assert result["pending_action"]["id"] == "pending-1"
    assert len(result["steps"]) == 1


def test_workflow_continues_when_stop_on_error_is_false():
    calls = []

    async def execute(action_type, payload, human_summary):
        calls.append(action_type)
        if action_type == "may_fail":
            return {"success": False, "summary": "Recoverable error."}
        return {"success": True, "summary": "OK"}

    manager = WorkflowManager(execute)
    result = asyncio.run(
        manager.execute_workflow(
            {
                "steps": [
                    {"action_type": "may_fail", "payload": {}, "stop_on_error": False},
                    {"action_type": "still_runs", "payload": {}, "stop_on_error": True},
                ]
            }
        )
    )

    assert calls == ["may_fail", "still_runs"]
    assert result["success"] is False
    assert result["status"] == "completed_with_errors"
