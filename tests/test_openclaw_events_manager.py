from openclaw_events_manager import OpenClawEventsManager


def test_register_inbound_event(tmp_path):
    manager = OpenClawEventsManager(tmp_path / "events.json")

    event = manager.add_event(
        "inbound",
        channel="whatsapp",
        kind="user",
        target="+34625941034",
        display_target="Adrian",
        message="Hola",
        raw={"id": "msg-1"},
    )

    assert event["id"]
    assert event["type"] == "inbound"
    assert event["message"] == "Hola"
    assert manager.list_events()[0]["target"] == "+34625941034"


def test_register_outbound_event(tmp_path):
    manager = OpenClawEventsManager(tmp_path / "events.json")

    event = manager.add_event("outbound", target="+34625941034", display_target="Adrian", message="Enviado")

    assert event["type"] == "outbound"
    assert event["success"] is True


def test_filter_by_type(tmp_path):
    manager = OpenClawEventsManager(tmp_path / "events.json")
    manager.add_event("inbound", message="uno")
    manager.add_event("outbound", message="dos")

    events = manager.list_events(type="inbound")

    assert len(events) == 1
    assert events[0]["message"] == "uno"


def test_limits_results_most_recent_first(tmp_path):
    manager = OpenClawEventsManager(tmp_path / "events.json")
    manager.add_event("inbound", message="uno")
    manager.add_event("inbound", message="dos")
    manager.add_event("inbound", message="tres")

    events = manager.list_events(limit=2)

    assert [event["message"] for event in events] == ["tres", "dos"]
