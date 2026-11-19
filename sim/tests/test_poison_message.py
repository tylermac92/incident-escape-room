"""SCN-05: poison_message (TDD §7.4)."""

import math

import pytest

from harness import PACK, holds, run_s, run_to_page, signal, ticks, world

CELLS = PACK.scenarios["poison_message"]["signature"]["cells"]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_pages_orders_backlog_high_and_shows_its_signature(seed):
    w, events, rule, t0 = run_to_page("poison_message", seed)
    assert rule == "orders_backlog_high" and ticks(events)[t0]["sim_time_ms"] > w.injector.onset_ms
    assert [c["text"] for c in CELLS if not holds(c, ticks(events)[-1])] == []


def test_the_consumer_crash_loops_on_the_same_message():
    w, events = world("poison_message", 4)
    onset_s = math.ceil(w.injector.onset_ms / 1000)
    run_s(w, onset_s + 1)
    poison = w.injector.fault.poison
    depth0 = w.jobs.depth
    attempts = []
    for _ in range(60):
        run_s(w, 1)
        attempts.append(poison.attempts)
    assert w.jobs.waiting[0] is poison and w.worker.status == "Crash-looping"
    assert attempts[-1] - attempts[0] in (11, 12)  # one delivery every 5 s
    assert 9 <= (w.jobs.depth - depth0) / 60 <= 11  # every new order piles up behind it
    assert signal(ticks(events)[-1], "worker.completed_rps") == 0


def test_holds_once_the_malformed_message_has_left_jobs():
    w, events, _, _ = run_to_page("poison_message", 1, after_s=0)
    assert ticks(events)[-1]["hidden"]["fault"]["neutralized"] is False
    w.jobs.waiting.remove(w.injector.fault.poison)  # what quarantine_head_message does (SCN-10)
    run_s(w, 1)
    assert ticks(events)[-1]["hidden"]["fault"]["neutralized"] is True
