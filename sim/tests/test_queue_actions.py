"""SCN-10: quarantine_head_message and purge_queue."""

from harness import act, applied, run_s, run_to_page, signal, ticks, world


def test_quarantining_the_poison_fixes_poison_message_and_loses_nothing():
    w, events, _, _ = run_to_page("poison_message", 1, after_s=0)
    poison, at = w.injector.fault.poison, w.engine.now_ms
    a = act(w, "quarantine_head_message", "jobs")
    run_s(w, 3)
    assert applied(events)[a] == at + 2000 and w.jobs.dlq == [poison]
    assert sum(t["bad_events"]["counts"]["order_lost"] for t in ticks(events)) == 0
    assert ticks(events)[-1]["hidden"]["fault"]["neutralized"] is True
    assert signal(ticks(events)[-1], "jobs.head_attempts") <= 2  # the next message is a healthy one
    depth = w.jobs.depth
    run_s(w, 30)  # restart backoff, then the backlog drains
    assert w.worker.status == "Up"
    drained = (depth - w.jobs.depth) / 25
    assert 24 <= drained <= 36  # about 30/s net (40/s minus 10/s still arriving)


def test_quarantining_a_healthy_order_loses_it():
    w, events, _, _ = run_to_page("pool_leak", 1, after_s=0)  # orders are backed up behind ledger
    head = w.jobs.waiting[0]
    act(w, "quarantine_head_message", "jobs")
    run_s(w, 3)
    assert w.jobs.dlq == [head] and not head.malformed and head.lost
    assert sum(t["bad_events"]["counts"]["order_lost"] for t in ticks(events)) == 1
    assert ticks(events)[-1]["hidden"]["fault"]["neutralized"] is False  # and pool_leak is untouched


def test_purge_deletes_every_queued_order_and_takes_the_poison_with_it():
    w, events, _, _ = run_to_page("poison_message", 2, after_s=0)
    at = w.engine.now_ms
    a = act(w, "purge_queue", "jobs")
    run_s(w, 3)
    queued = w.jobs.depth  # just before the purge applies, at the start of the next step
    run_s(w, 1)
    assert applied(events)[a] == at + 3000
    lost = sum(t["bad_events"]["counts"]["order_lost"] for t in ticks(events))
    assert lost >= queued - 1 and w.jobs.dlq == []  # every order but the malformed one, which isn't an order
    assert ticks(events)[-1]["hidden"]["fault"]["neutralized"] is True
    run_s(w, 30)
    assert w.worker.status == "Up" and w.jobs.depth < 20
