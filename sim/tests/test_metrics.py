import math
import random
from types import SimpleNamespace as NS

import pytest

from sim.api import Call, Response
from sim.jobs import Jobs, Message
from sim.metrics import Metrics, percentile


def services(responses=(), calls=(), attempts=(), api_peak=0, worker_peak=0, db_peak=0):
    api = NS(responses=list(responses), clients_peak=api_peak, status="Up")
    ledger = NS(completed=list(calls), peak_in_use=db_peak, status="Up", queue=[1, 2, 3])
    worker = NS(attempts=list(attempts), clients_peak=worker_peak, status="Crash-looping")
    return api, ledger, worker


def one_second(metrics, jobs=None, **kw):
    api, ledger, worker = services(**kw)
    metrics.record(api, ledger, worker)
    return metrics.tick(api, ledger, worker, jobs or Jobs())


def test_percentiles_of_a_known_distribution():
    assert percentile(list(range(1, 1001)), 95) == 950 and percentile(list(range(1, 101)), 50) == 50
    assert percentile([], 95) is None
    rng = random.Random(7)
    m = one_second(Metrics(), responses=[Response("read", 0, round(rng.expovariate(1 / 100))) for _ in range(20000)])
    assert m["api"]["latency_p95_ms"] == pytest.approx(-100 * math.log(0.05), rel=0.05)  # exponential, mean 100


def test_error_rate_denominator_is_every_completion_in_the_window():
    metrics = Metrics()
    one_second(metrics, responses=[Response("read", 0, 10, "timeout")] * 2 + [Response("read", 0, 10)] * 6)
    m = one_second(metrics, responses=[Response("order", 0, 15, "unavailable")] * 2)
    assert m["api"]["error_rate_pct"] == 40.0  # 4 of 10 over both seconds
    assert m["api"]["errors_pct_by_reason"] == {"timeout": 20.0, "unavailable": 20.0}
    for _ in range(9):
        m = one_second(metrics)
    assert m["api"]["error_rate_pct"] == 100.0  # the first second has left the 10 s window
    m = one_second(metrics)
    assert m["api"]["error_rate_pct"] is None and m["api"]["latency_p95_ms"] is None


def test_throughput_breakdowns():
    metrics = Metrics()
    calls = [Call("api", "read", 1, 0, 1000, 80), Call("api", "read", 2, 0, 1000, 80, "timeout"),
             Call("worker", "write", 1, 0, 2000, 120)]
    attempts = [Response("job", 0, 220), Response("job", 0, 0, "crash")]
    one_second(metrics, responses=[Response("read", 0, 50)] * 30, calls=calls, attempts=attempts)
    m = one_second(metrics, responses=[Response("receipt_export", 0, 50)] * 2)
    assert m["api"]["throughput_rps"] == {"read": 15.0, "receipt_export": 1.0, "order": 0.0}  # 2 s so far
    assert m["ledger"]["throughput_rps"] == {"api.first": 0.5, "api.retry": 0.5, "worker.first": 0.5, "worker.retry": 0.0}
    assert m["ledger"]["errors_pct_by_reason"] == {"timeout": 33.3}
    assert m["worker"]["throughput_rps"] == {"completed": 0.5, "attempts": 1.0}
    assert m["worker"]["errors_pct_by_reason"] == {"crash": 50.0}


def test_samples_statuses_and_pool_maximum_within_the_second():
    metrics, jobs = Metrics(), Jobs()
    for _ in range(4):
        jobs.put(Message(0))
    jobs.take()
    api, ledger, worker = services(api_peak=12, worker_peak=3, db_peak=9)
    metrics.record(api, ledger, worker)
    api.clients_peak, ledger.peak_in_use = 47, 4  # a later step in the same second
    metrics.record(api, ledger, worker)
    m = metrics.tick(api, ledger, worker, jobs)
    assert m["api"]["pool_in_use"] == {"api.ledger_client": {"used": 47, "max": 50}}
    assert m["ledger"]["pool_in_use"] == {"ledger.db": {"used": 9, "max": 10}}
    assert m["worker"]["pool_in_use"] == {"worker.ledger_client": {"used": 3, "max": 10}}
    assert m["worker"]["queue_depth"] == {"jobs": 4, "jobs.head_attempts": 0, "jobs.dlq": 0}
    assert m["ledger"]["queue_depth"] == {"ledger.requests": 3}
    assert [m[s]["status"] for s in ("api", "worker", "ledger")] == ["Up", "Crash-looping", "Up"]
    assert one_second(metrics)["api"]["pool_in_use"]["api.ledger_client"]["used"] == 0  # reset each second
