from sim.api import Response
from sim.bad_events import WEIGHTS, BadEvents
from sim.jobs import Message


def counted(responses):
    bad = BadEvents()
    bad.step(0, responses)
    return {c: n for c, n in bad.take().items() if n}


def test_synchronous_requests():
    assert counted([
        Response("read", 0, 1000, "timeout"),
        Response("read", 0, 2001),  # slow
        Response("read", 0, 2000),  # not slow
        Response("receipt_export", 0, 100, "pool_timeout"),
        Response("receipt_export", 0, 2500),  # slow exports are not a category
    ]) == {"read_failed": 1, "read_slow": 1, "receipt_unavailable": 1}


def test_orders_rejected_while_api_is_down():
    assert counted([Response("order", 0, 0, "unavailable"), Response("order", 0, 15)]) == {"order_rejected": 1}


def test_order_delayed_is_counted_once_at_breach():
    bad = BadEvents()
    late, on_time, lost = Message(placed_ms=1050), Message(placed_ms=1050), Message(placed_ms=1050)
    for m in (late, on_time, lost):
        bad.track(m)
    on_time.done_ms = 31_050  # exactly at the target
    bad.lost([lost])
    per_step = {}
    for n in range(400):
        bad.step(n * 100, [])
        per_step[n * 100] = bad.take()["order_delayed"]
    assert {t: c for t, c in per_step.items() if c} == {31_000: 1}  # breach at 31 050
    late.done_ms = 40_000
    bad.step(40_000, [])
    assert bad.take()["order_delayed"] == 0


def test_order_completed_after_breach_in_the_same_step_is_delayed():
    bad = BadEvents()
    msg = Message(placed_ms=0)
    bad.track(msg)
    msg.done_ms = 30_050  # worker finished it later in the step that holds the breach
    bad.step(30_000, [])
    assert bad.take()["order_delayed"] == 1


def test_order_lost_is_weighted_3():
    bad = BadEvents()
    bad.lost([Message(0), Message(0)])
    assert bad.take()["order_lost"] == 2 and WEIGHTS["order_lost"] == 3
    assert {w for c, w in WEIGHTS.items() if c != "order_lost"} == {1}


def test_take_resets_each_second():
    bad = BadEvents()
    bad.step(0, [Response("read", 0, 10, "queue_full")])
    assert bad.take()["read_failed"] == 1 and bad.take()["read_failed"] == 0
