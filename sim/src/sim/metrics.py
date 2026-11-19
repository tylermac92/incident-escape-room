"""Metric aggregation (SIM-09, TDD §8.5, §9.1, §9.2, FR-4).

Requests are recorded at completion, once per step. Each simulated second, tick() turns the
trailing 10 s into latency p50/p95, error rate (by reason), and throughput (by breakdown), and
samples queue depth and pool use (the maximum within the second) for each service.
"""

import math
from collections import Counter, deque

from sim.api import CLIENT_POOL
from sim.ledger import POOL_SIZE
from sim.traffic import RATES
from sim.worker import SLOTS

WINDOW_S = 10
LEDGER_LABELS = ("api.first", "api.retry", "worker.first", "worker.retry")
POOLS = {"api.ledger_client": CLIENT_POOL, "worker.ledger_client": SLOTS, "ledger.db": POOL_SIZE}


def percentile(ordered: list, p: float):
    """Nearest-rank percentile of an ascending list; None when empty."""
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)] if ordered else None


def summarize(samples: list, seconds: int, labels) -> dict:
    """samples: (latency ms, reason, label) per completed request; reason None means success."""
    latencies = sorted(lat for lat, _, _ in samples)
    errors = Counter(reason for _, reason, _ in samples if reason)
    per_label = Counter(label for _, _, label in samples)
    n = len(samples)
    return {
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "error_rate_pct": round(100 * errors.total() / n, 1) if n else None,
        "errors_pct_by_reason": {r: round(100 * k / n, 1) for r, k in sorted(errors.items())},
        "throughput_rps": {label: round(per_label[label] / seconds, 1) for label in labels},
    }


class Metrics:
    def __init__(self):
        self._window: deque = deque(maxlen=WINDOW_S)  # one bucket per second
        self._bucket = self._new_bucket()
        self._peaks = dict.fromkeys(POOLS, 0)

    @staticmethod
    def _new_bucket():
        return {"api": [], "ledger": [], "worker": []}

    def record(self, api, ledger, worker) -> None:
        """Once per step, before the services' completion lists are drained."""
        b = self._bucket
        b["api"] += [(r.latency_ms, r.reason, r.flow) for r in api.responses]
        b["ledger"] += [(c.done_ms - c.start_ms, c.reason, f"{c.caller}.{'first' if c.attempt == 1 else 'retry'}")
                        for c in ledger.completed]
        b["worker"] += [(a.latency_ms, a.reason, "completed" if a.reason is None else "failed")
                        for a in worker.attempts]
        for pool, used in (("api.ledger_client", api.clients_peak), ("worker.ledger_client", worker.clients_peak),
                           ("ledger.db", ledger.peak_in_use)):
            self._peaks[pool] = max(self._peaks[pool], used)

    def tick(self, api, ledger, worker, jobs) -> dict:
        """The services' metrics for the second that just ended."""
        self._window.append(self._bucket)
        self._bucket = self._new_bucket()
        peaks, self._peaks = self._peaks, dict.fromkeys(POOLS, 0)
        seconds = len(self._window)  # fewer than 10 at the start of a round
        merged = {svc: [s for b in self._window for s in b[svc]] for svc in ("api", "ledger", "worker")}

        sizes = {**POOLS, "ledger.db": ledger.pool_size}

        def pool(name):
            return {name: {"used": peaks[name], "max": sizes[name]}}

        worker_m = summarize(merged["worker"], seconds, ("completed",))
        worker_m["throughput_rps"]["attempts"] = round(len(merged["worker"]) / seconds, 1)
        return {
            "api": {"status": api.status, **summarize(merged["api"], seconds, RATES),
                    "pool_in_use": pool("api.ledger_client")},
            "worker": {"status": worker.status, **worker_m,
                       "queue_depth": {"jobs": jobs.depth, "jobs.head_attempts": jobs.head_attempts,
                                       "jobs.dlq": len(jobs.dlq)},
                       "pool_in_use": pool("worker.ledger_client")},
            "ledger": {"status": ledger.status, **summarize(merged["ledger"], seconds, LEDGER_LABELS),
                       "queue_depth": {"ledger.requests": len(ledger.queue)},
                       "pool_in_use": pool("ledger.db")},
        }
