"""CTL-08: boundary values for each health check, and the D-07 slope rule."""

import random

import pytest
from fakes import services

from controller.health import Health, slope


def check(svc, cid, since_t0=None, health=None):
    return next(c for c in (health or Health()).evaluate(svc, since_t0) if c["id"] == cid)


def test_healthy_baseline_passes_all_ten():
    checks = Health().evaluate(services(), None)
    assert len(checks) == 10 and all(c["passing"] for c in checks)
    assert set(checks[0]) == {"id", "passing", "value", "threshold"}


def at(path, value):
    """services() with one leaf replaced; the path separates keys with |."""
    svc = services()
    keys = path.split("|")
    node = svc
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value
    return svc


# (check id, leaf path, last passing value, first failing value): pass means value < threshold.
BOUNDARIES = [
    ("api_errors", "api|error_rate_pct", 0.9, 1.0),
    ("api_latency", "api|latency_p95_ms", 499, 500),
    ("worker_errors", "worker|error_rate_pct", 1.9, 2.0),
    ("ledger_errors", "ledger|error_rate_pct", 0.9, 1.0),
    ("ledger_latency", "ledger|latency_p95_ms", 299, 300),
    ("ledger_pool", "ledger|pool_in_use|ledger.db|used", 10.3, 10.4),  # 13 * 0.8 = 10.4
    ("ledger_requests", "ledger|queue_depth|ledger.requests", 19, 20),
]


@pytest.mark.parametrize("cid,path,ok,bad", BOUNDARIES)
def test_boundaries(cid, path, ok, bad):
    assert check(at(path, ok), cid)["passing"]
    assert not check(at(path, bad), cid)["passing"]


def test_missing_latency_or_rate_counts_as_zero():
    assert check(at("api|latency_p95_ms", None), "api_latency")["passing"]
    assert check(at("api|error_rate_pct", None), "api_errors")["passing"]


def test_retry_share_boundary():
    def share(retry):  # 30 first attempts plus `retry` retries from api
        svc = services()
        svc["ledger"]["throughput_rps"] = {"api.first": 30.0 - retry, "api.retry": retry, "worker.first": 0.0,
                                           "worker.retry": 0.0}
        return check(svc, "ledger_retry_share")

    assert share(7.4)["passing"] and not share(7.5)["passing"]  # 7.5 / 30 = 25%
    svc = services()
    svc["ledger"]["throughput_rps"] = dict.fromkeys(svc["ledger"]["throughput_rps"], 0.0)
    assert check(svc, "ledger_retry_share")["value"] == 0  # no traffic is no retries


def test_worker_status():
    assert check(services(worker_status="Up"), "worker_status")["passing"]
    for status in ("Crash-looping", "Restarting"):
        assert not check(services(worker_status=status), "worker_status")["passing"]


def backlog(depths, since_t0=None):
    health = Health()
    for depth in depths:
        result = check(services(jobs=depth), "jobs_backlog", since_t0, health)
    return result


def test_backlog_depth_boundary():
    assert backlog([99] * 30)["passing"] and not backlog([100] * 30)["passing"]


def test_slope_series():
    rng = random.Random(7)
    noisy = [50 + rng.uniform(-10, 10) for _ in range(30)]
    draining = [95 - 2 * i for i in range(30)]
    growing = [10 + i for i in range(30)]  # +1/s
    creeping = [10 + 0.5 * i for i in range(30)]  # exactly the limit
    assert abs(slope(noisy)) < 0.5 and backlog(noisy)["passing"]
    assert backlog(draining)["passing"]
    assert not backlog(growing)["passing"]
    assert backlog(creeping)["passing"] and not backlog([10 + 0.51 * i for i in range(30)])["passing"]


def test_slope_uses_samples_since_t0_with_a_minimum_of_ten():
    # Growing for a long time, then flat for the 12 seconds since T0.
    depths = [10 + 3 * i for i in range(20)] + [70] * 12
    assert backlog(depths, since_t0=12)["passing"]  # only the 12 flat samples count
    assert not backlog(depths, since_t0=None)["passing"]  # pre-roll: the trailing 30
    # 5 samples since T0: the trailing 10 are used, which still include the climb.
    assert not backlog([10 + 3 * i for i in range(25)] + [80] * 5, since_t0=5)["passing"]


def test_slope_of_known_line():
    assert slope([1, 3, 5, 7]) == pytest.approx(2.0)
    assert slope([4]) == 0.0
