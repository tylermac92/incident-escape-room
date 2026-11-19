import math
import random
from collections import Counter

import pytest

from sim.api import Api, Call
from sim.ledger import HOLD_MEAN_MS, POOL_SIZE, QUEUE_CAP, Ledger
from sim.rng import stream
from sim.traffic import RATES, Traffic


def call(kind="read", at=0, caller="api", attempt=1, timeout=1000):
    return Call(caller, kind, attempt, at, at + timeout)


def run(ledger, calls_at, steps):
    done = []
    for n in range(steps):
        now = n * 100
        ledger.step(now, [c for c in calls_at if now <= c.start_ms < now + 100])
        done += ledger.completed
        ledger.completed.clear()
    return done


def test_lease_and_release(monkeypatch):
    monkeypatch.setitem(HOLD_MEAN_MS, "read", 1000)  # long holds, so none frees within the first step
    ledger = Ledger(stream(1, "latency"))
    calls = [call(at=5 * i, timeout=10**6) for i in range(POOL_SIZE + 2)]
    ledger.step(0, calls)
    assert ledger.in_use(99) == POOL_SIZE and len(ledger.queue) == 2  # 10 leased, 2 waiting
    assert ledger.pool_used == pytest.approx(sum(100 - 5 * i for i in range(POOL_SIZE)) / 100)  # time-weighted
    done = run(ledger, [], 60)
    assert len(done) == len(calls) and all(c.reason is None for c in done)
    assert ledger.in_use(6000) == 0 and not ledger.queue
    # A connection is held from start to done; waiting requests start exactly when one frees.
    first_free = min(c.done_ms for c in calls[:POOL_SIZE])
    assert calls[POOL_SIZE].done_ms > first_free


def test_queue_overflow_is_rejected_at_arrival():
    ledger = Ledger(stream(1, "latency"))
    ledger.busy_until = [math.inf] * POOL_SIZE  # every connection leaked
    calls = [call(at=0) for _ in range(QUEUE_CAP + 5)]
    ledger.step(0, calls)
    rejected = ledger.completed
    assert len(ledger.queue) == QUEUE_CAP
    assert [(c.reason, c.done_ms) for c in rejected] == [("queue_full", 0)] * 5
    assert rejected == calls[QUEUE_CAP:]  # FIFO: the latest arrivals are the ones rejected


def test_pool_wait_counts_from_arrival():
    ledger = Ledger(stream(1, "latency"))
    ledger.busy_until = [math.inf] * POOL_SIZE
    calls = [call(at=50), call(at=70)]
    done = run(ledger, calls, 30)
    assert [(c.reason, c.done_ms) for c in done] == [("pool_timeout", 2050), ("pool_timeout", 2070)]


def test_pool_wait_ends_when_a_connection_frees():
    ledger = Ledger(stream(1, "latency"))
    ledger.busy_until = [math.inf] * (POOL_SIZE - 1) + [1500.0]
    waiting = call(at=0, timeout=5000)
    run(ledger, [waiting], 40)
    assert waiting.reason is None and waiting.done_ms > 1500


def test_abandoned_calls_are_still_processed_as_wasted_work():
    ledger = Ledger(stream(1, "latency"))
    ledger.busy_until = [1900.0] * POOL_SIZE
    late = call(at=0, caller="worker", attempt=2, kind="write")  # deadline 1000, served after 1900
    done = run(ledger, [late], 40)
    assert done == [late] and late.reason == "timeout" and late.done_ms > 1900
    assert (late.caller, late.attempt) == ("worker", 2)
    assert ledger.busy_ms > 0


@pytest.mark.parametrize("kind, mean", [("read", 80), ("write", 120), ("receipt_export", 300)])
def test_hold_time_means(kind, mean):
    ledger = Ledger(stream(1, "latency"))
    holds = []
    for i in range(4000):
        before = ledger.busy_ms
        ledger._start(call(kind=kind, timeout=10**9), 0)
        holds.append(ledger.busy_ms - before)
        ledger.busy_until = [0.0] * POOL_SIZE
    assert sum(holds) / len(holds) == pytest.approx(mean, rel=0.03)


def baseline_calls(seed, minutes, scale=1.0):
    """Calls at the baseline mix: reads and exports from api, order writes from worker."""
    traffic = Traffic(stream(seed, "traffic"), {f: r * scale for f, r in RATES.items()})
    jitter, calls = random.Random(seed), []
    for n in range(minutes * 600):
        for flow, count in traffic.arrivals(n * 100).items():
            kind, caller = ("write", "worker") if flow == "order" else (flow, "api")
            calls += [call(kind, n * 100 + jitter.randrange(100), caller, timeout=10**9) for _ in range(count)]
    return calls


def test_baseline_utilization_is_about_32_percent():  # 42% with the TDD's 10 connections (D-24)
    ledger = Ledger(stream(2, "latency"))
    done = run(ledger, baseline_calls(2, 10), 10 * 600)
    assert all(c.reason is None for c in done)
    assert ledger.busy_ms / (POOL_SIZE * 600_000) == pytest.approx(0.32, abs=0.05)


def test_capacity_is_about_130_rps():  # 100 with the TDD's 10 connections (D-24)
    ledger = Ledger(stream(3, "latency"))
    done = run(ledger, baseline_calls(3, 2, scale=4), 2 * 600)  # about 170 rps offered
    served = sum(1 for c in done if c.reason is None and c.done_ms >= 30_000)
    assert served / 90 == pytest.approx(130, rel=0.1)


def test_api_and_ledger_together_at_baseline():
    rng = stream(4, "latency")
    api, ledger, traffic = Api(rng, [].append), Ledger(rng), Traffic(stream(4, "traffic"))
    for n in range(3000):
        now = n * 100
        api.step(now, traffic.arrivals(now))
        ledger.step(now, api.outbox)
        api.outbox.clear()
    reasons = Counter(r.reason for r in api.responses)
    assert reasons[None] > 0.999 * len(api.responses)
    reads = sorted(r.latency_ms for r in api.responses if r.flow == "read")
    assert 100 < reads[int(0.95 * len(reads))] < 300  # p95: own time, step granularity, ledger hold
