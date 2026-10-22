from app.realtime.notify import route


def test_route_envelope_to_topic() -> None:
    r = route("sim_events", '{"event_type":"fault.started","run_id":3,"payload":{}}')
    assert r and r[0] == "sim" and r[1] == "fault.started" and r[3] == 3
    r = route("sim_events", '{"event_type":"review.posted","run_id":1}')
    assert r and r[0] == "feed"
    r = route("escalations", '{"type":"created","data":{"id":7},"run_id":1}')
    assert r == ("escalations", "created", {"id": 7}, 1)
    assert route("unknown", "{}") is None
    r = route("zones", "not json")
    assert r and r[0] == "zones"
