from copy import deepcopy


def _warnings(result):
    warnings = result.get("warnings") if isinstance(result, dict) else []
    return warnings if isinstance(warnings, list) else []


class WorkflowManager:
    """Executes a workflow through Jarvis' existing OpenClaw safety path."""

    def __init__(self, execute_or_queue_action):
        self.execute_or_queue_action = execute_or_queue_action

    async def execute_workflow(self, workflow, automation=None):
        steps = self._steps(workflow)
        if not steps:
            return {
                "success": False,
                "status": "empty",
                "steps": [],
                "summary": "Workflow sin pasos.",
            }

        results = []
        context = {
            "automation": deepcopy(automation or {}),
            "previous_steps": [],
        }
        if isinstance(automation, dict):
            if automation.get("source"):
                context["source"] = automation.get("source")
            if automation.get("event_type"):
                context["event_type"] = automation.get("event_type")
            if automation.get("event_payload") is not None:
                context["event_payload"] = deepcopy(automation.get("event_payload"))

        had_error = False
        for index, step in enumerate(steps):
            action_type = str(step.get("action_type") or "").strip()
            payload = deepcopy(step.get("payload") or {})
            if not isinstance(payload, dict):
                payload = {}
            payload["_workflow_context"] = deepcopy(context)
            human_summary = step.get("human_summary") or None
            stop_on_error = bool(step.get("stop_on_error", True))

            if not action_type:
                result = {
                    "success": False,
                    "status": "invalid_step",
                    "summary": "Paso sin action_type.",
                    "step_index": index,
                }
            else:
                try:
                    result = await self.execute_or_queue_action(action_type, payload, human_summary)
                except Exception as exc:
                    result = {
                        "success": False,
                        "status": "exception",
                        "summary": str(exc),
                        "error": str(exc),
                    }

            step_result = {
                "index": index,
                "action_type": action_type,
                "human_summary": human_summary,
                "stop_on_error": stop_on_error,
                "result": result,
            }
            results.append(step_result)
            context["previous_steps"].append(deepcopy(step_result))

            if not result.get("success"):
                had_error = True

            if result.get("confirmation_required") or "confirmation_required" in _warnings(result):
                return {
                    "success": False,
                    "status": "waiting_for_confirmation",
                    "steps": results,
                    "context": context,
                    "pending_action": result.get("raw"),
                    "summary": result.get("summary") or "Workflow detenido por confirmacion pendiente.",
                    "automation": automation or {},
                }

            if not result.get("success") and stop_on_error:
                return {
                    "success": False,
                    "status": "failed",
                    "steps": results,
                    "context": context,
                    "summary": result.get("summary") or result.get("error") or "Workflow detenido por error.",
                    "automation": automation or {},
                }

        return {
            "success": not had_error,
            "status": "completed_with_errors" if had_error else "completed",
            "steps": results,
            "context": context,
            "summary": "Workflow completado con errores." if had_error else "Workflow completado.",
            "automation": automation or {},
        }

    def _steps(self, workflow):
        raw_steps = []
        if isinstance(workflow, list):
            raw_steps = workflow
        elif isinstance(workflow, dict):
            raw_steps = workflow.get("steps", [])

        normalized = []
        for step in raw_steps if isinstance(raw_steps, list) else []:
            if not isinstance(step, dict):
                continue
            normalized.append(
                {
                    "action_type": str(step.get("action_type") or "").strip(),
                    "payload": deepcopy(step.get("payload")) if isinstance(step.get("payload"), dict) else {},
                    "human_summary": str(step.get("human_summary") or "").strip(),
                    "stop_on_error": bool(step.get("stop_on_error", True)),
                }
            )
        return normalized
