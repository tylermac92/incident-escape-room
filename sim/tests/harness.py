"""Headless scenario harness (TDD §15.1): drive a World directly, no socket, no containers."""

from pathlib import Path

from sim.scenarios import load_pack
from sim.world import STEPS_PER_TICK, World

PACK = load_pack(Path(__file__).parents[1] / "scenarios")


def world(scenario_id="pool_leak", seed=1, pack=PACK):
    events = []
    return World(scenario_id, seed, events.append, pack), events


def run_s(w, seconds):
    for _ in range(seconds * STEPS_PER_TICK):
        w.engine.step()


def ticks(events):
    return [e for e in events if e["type"] == "evt.tick"]


def _main_error(service):
    errors = service["errors_pct_by_reason"]
    return max(errors, key=errors.get) if errors else "none"


def _retry_share(ledger):
    rps = ledger["throughput_rps"]
    total = sum(rps.values())
    return (rps["api.retry"] + rps["worker.retry"]) / total if total else 0.0


# Player-visible signals, read from tick["services"] (the names used in the pack's signature cells).
SIGNALS = {
    "ledger.pool_used": lambda s: s["ledger"]["pool_in_use"]["ledger.db"]["used"],
    "ledger.throughput_rps": lambda s: sum(s["ledger"]["throughput_rps"].values()),
    "ledger.retry_share": lambda s: _retry_share(s["ledger"]),
    "ledger.queue": lambda s: s["ledger"]["queue_depth"]["ledger.requests"],
    "ledger.main_error": lambda s: _main_error(s["ledger"]),
    "ledger.latency_p95_ms": lambda s: s["ledger"]["latency_p95_ms"] or 0,
    "api.error_rate_pct": lambda s: s["api"]["error_rate_pct"] or 0,
    "api.latency_p95_ms": lambda s: s["api"]["latency_p95_ms"] or 0,
    "worker.status": lambda s: s["worker"]["status"],
    "worker.main_error": lambda s: _main_error(s["worker"]),
    "worker.completed_rps": lambda s: s["worker"]["throughput_rps"]["completed"],
    "jobs.depth": lambda s: s["worker"]["queue_depth"]["jobs"],
    "jobs.head_attempts": lambda s: s["worker"]["queue_depth"]["jobs.head_attempts"],
}
# §9.6 page rules, thresholds from the pack: each must hold on FOR_S consecutive one-second
# evaluations. Rules that fire in the same second page in this (§9.6 table) order (D-22).
ALERTS = PACK.controller["alerts"]
RULES = {
    "api_error_rate_high": lambda s: SIGNALS["api.error_rate_pct"](s) >= ALERTS["api_error_rate_pct"],
    "api_latency_high": lambda s: SIGNALS["api.latency_p95_ms"](s) >= ALERTS["api_latency_p95_ms"],
    "orders_backlog_high": lambda s: SIGNALS["jobs.depth"](s) >= ALERTS["orders_backlog"],
}
FOR_S = ALERTS["for_s"]


def signal(tick, name):
    return SIGNALS[name](tick["services"])


def holds(cell, tick):
    value = signal(tick, cell["signal"])
    return {">=": value >= cell["value"] if not isinstance(value, str) else False,
            "<=": value <= cell["value"] if not isinstance(value, str) else False,
            "==": value == cell["value"]}[cell["op"]]


def run_to_page(scenario_id, seed, after_s=60, limit_s=900):
    """Run until the first page rule fires (as the controller would, CTL-05), then after_s more.

    Returns (world, events, rule, t0 tick index); rule is None if nothing paged by onset + limit_s.
    """
    w, events = world(scenario_id, seed)
    runs = dict.fromkeys(RULES, 0)
    while True:
        run_s(w, 1)
        tick = ticks(events)[-1]
        for rule, cond in RULES.items():
            runs[rule] = runs[rule] + 1 if cond(tick["services"]) else 0
        fired = [r for r, n in runs.items() if n >= FOR_S]
        if fired or tick["sim_time_ms"] > w.injector.onset_ms + limit_s * 1000:
            t0 = len(ticks(events)) - 1
            run_s(w, after_s)
            return w, events, (fired[0] if fired else None), t0
