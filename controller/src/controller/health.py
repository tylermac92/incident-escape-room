"""The ten shared health checks (CTL-08, TDD §9.3), evaluated once per tick.

They drive stability (CTL-06), the health panel and declaration. The same set applies in every
scenario. Thresholds are §9.3 defaults; they are not tuning knobs (§8.7), so they live here.
"""

from collections import deque

SLOPE_MAX = 0.5  # messages/s over the trailing samples (D-07)
SLOPE_SAMPLES, SLOPE_MIN_SAMPLES = 30, 10


def _retry_share(ledger: dict) -> float:
    rps = ledger["throughput_rps"]
    total = sum(rps.values())
    return (rps["api.retry"] + rps["worker.retry"]) / total if total else 0.0


def _pool_share(ledger: dict) -> float:
    pool = ledger["pool_in_use"]["ledger.db"]
    return pool["used"] / pool["max"]


# (id, value from tick["services"], threshold): each passes when value < threshold.
BELOW = (
    ("api_errors", lambda s: s["api"]["error_rate_pct"] or 0, 1),
    ("api_latency", lambda s: s["api"]["latency_p95_ms"] or 0, 500),
    ("worker_errors", lambda s: s["worker"]["error_rate_pct"] or 0, 2),
    ("ledger_errors", lambda s: s["ledger"]["error_rate_pct"] or 0, 1),
    ("ledger_latency", lambda s: s["ledger"]["latency_p95_ms"] or 0, 300),
    ("ledger_pool", lambda s: _pool_share(s["ledger"]), 0.8),
    ("ledger_requests", lambda s: s["ledger"]["queue_depth"]["ledger.requests"], 20),
    ("ledger_retry_share", lambda s: _retry_share(s["ledger"]), 0.25),
)
BACKLOG_MAX = 100


def slope(ys) -> float:
    """Least-squares slope per sample (samples are 1 s apart)."""
    n = len(ys)
    if n < 2:
        return 0.0
    x_mean, y_mean = (n - 1) / 2, sum(ys) / n
    return sum((x - x_mean) * (y - y_mean) for x, y in enumerate(ys)) / sum((x - x_mean) ** 2 for x in range(n))


class Health:
    def __init__(self):
        self.depths: deque = deque(maxlen=SLOPE_SAMPLES)

    def evaluate(self, services: dict, since_t0: int | None) -> list[dict]:
        """One evaluation. `since_t0`: ticks since T0 including it, or None during pre-roll."""
        checks = [{"id": cid, "passing": value(services) < limit, "value": value(services), "threshold": limit}
                  for cid, value, limit in BELOW]
        status = services["worker"]["status"]
        checks.insert(3, {"id": "worker_status", "passing": status == "Up", "value": status, "threshold": "Up"})
        depth = services["worker"]["queue_depth"]["jobs"]
        self.depths.append(depth)
        # D-07: the trailing 30 samples, or those since T0 (at least 10) early in the round.
        n = SLOPE_SAMPLES if since_t0 is None else max(SLOPE_MIN_SAMPLES, min(SLOPE_SAMPLES, since_t0))
        rise = slope(list(self.depths)[-n:])
        checks.append({"id": "jobs_backlog", "passing": depth < BACKLOG_MAX and rise <= SLOPE_MAX,
                       "value": {"depth": depth, "slope": round(rise, 3)},
                       "threshold": {"depth": BACKLOG_MAX, "slope": SLOPE_MAX}})
        return checks
