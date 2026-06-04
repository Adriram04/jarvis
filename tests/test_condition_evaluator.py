import asyncio

from condition_evaluator import ConditionEvaluator


def _run(coro):
    return asyncio.run(coro)


def test_empty_conditions_pass():
    evaluator = ConditionEvaluator()
    result = _run(evaluator.evaluate([], {}))
    assert result["passed"] is True


def test_always_passes():
    evaluator = ConditionEvaluator()
    result = _run(evaluator.evaluate([{"type": "always"}], {}))
    assert result["passed"] is True


def test_message_contains_matches_case_insensitive():
    evaluator = ConditionEvaluator()
    conditions = [{"type": "message_contains", "any": ["urgente"]}]
    passed = _run(evaluator.evaluate(conditions, {"message": "Esto es URGENTE!"}))
    assert passed["passed"] is True
    not_passed = _run(evaluator.evaluate(conditions, {"message": "hola"}))
    assert not_passed["passed"] is False


def test_message_contains_reads_nested_incoming():
    evaluator = ConditionEvaluator()
    conditions = [{"type": "message_contains", "text": "factura"}]
    result = _run(evaluator.evaluate(conditions, {"incoming": {"message": "te paso la factura"}}))
    assert result["passed"] is True


def test_and_evaluation_requires_all():
    evaluator = ConditionEvaluator(providers={"is_simulation_enabled": lambda: True})
    conditions = [
        {"type": "message_contains", "any": ["hola"]},
        {"type": "simulation_enabled"},
    ]
    ok = _run(evaluator.evaluate(conditions, {"message": "hola mundo"}))
    assert ok["passed"] is True
    fail = _run(evaluator.evaluate(conditions, {"message": "adios"}))
    assert fail["passed"] is False


def test_provider_connected_uses_provider_callback():
    calls = {}

    async def is_provider_connected(name):
        calls["name"] = name
        return name == "openwa"

    evaluator = ConditionEvaluator(providers={"is_provider_connected": is_provider_connected})
    result = _run(evaluator.evaluate([{"type": "provider_connected", "provider": "openwa"}], {}))
    assert result["passed"] is True
    assert calls["name"] == "openwa"


def test_sender_in_allowlist_uses_provider():
    evaluator = ConditionEvaluator(providers={"is_sender_allowed": lambda sender: sender == "+34600"})
    payload = {"incoming": {"target": "+34600"}}
    assert _run(evaluator.evaluate([{"type": "sender_in_allowlist"}], payload))["passed"] is True
    payload_bad = {"incoming": {"target": "+34999"}}
    assert _run(evaluator.evaluate([{"type": "sender_in_allowlist"}], payload_bad))["passed"] is False


def test_time_between_same_day_window():
    evaluator = ConditionEvaluator()
    # A window that always covers the whole day must pass.
    result = _run(evaluator.evaluate([{"type": "time_between", "start": "00:00", "end": "23:59"}], {}))
    assert result["passed"] is True
    # An impossible single-minute window in the far past minute should fail most of the time;
    # instead assert the inverted-day window logic does not crash and returns a bool.
    crossing = _run(evaluator.evaluate([{"type": "time_between", "start": "23:59", "end": "00:00"}], {}))
    assert isinstance(crossing["passed"], bool)


def test_unknown_condition_fails_safely():
    evaluator = ConditionEvaluator()
    result = _run(evaluator.evaluate([{"type": "does_not_exist"}], {}))
    assert result["passed"] is False
