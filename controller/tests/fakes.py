"""A scripted stand-in for sim on the link, and healthy-by-default tick contents."""

import asyncio
from pathlib import Path

from controller.actions import CATALOG
from controller.feed import load_content

CONTENT = load_content(Path(__file__).parents[1] / "feed_templates")
CONFIG = {"budget": 12, "round_time_limit_s": 720, "stability_window_s": 60, "feed": {"interval_s": 5, "min_count": 5},
          "score": {"speed_max": 300, "speed_grace_s": 90, "impact_max": 300, "impact_scale": 15000,
                    "hold_declared": 100, "hold_neutralized": 100, "budget_max": 200, "breadth_restart_all": 150,
                    "breadth_restart_service": 25, "noeffect": 30, "premature": 50, "premature_max_count": 3},
          "action_costs": {"restart_service": 3, "restart_all": 10, "recycle_pool": 1, "set_feature_flag": 1,
                           "set_retry_policy": 1, "quarantine_head_message": 1, "purge_queue": 4},
          "alerts": {"api_error_rate_pct": 5, "api_latency_p95_ms": 1000, "orders_backlog": 500, "for_s": 30}}
ONSET_MS = 700_000
# Every §10.2 row; a test may override one. The same matrix for every scenario.
MATRIX = dict.fromkeys(["restart_service(api)", "restart_service(worker)", "restart_service(ledger)", "restart_all",
                        "recycle_pool(ledger)", "set_feature_flag(receipt_export, off)",
                        "set_feature_flag(receipt_export, on)", "set_feature_flag(checkout_banner, *)",
                        "set_retry_policy(api, backoff)", "set_retry_policy(worker, backoff)",
                        "set_retry_policy(*, aggressive)", "quarantine_head_message(jobs)", "purge_queue(jobs)"], "no_effect")
WEIGHTS = {"read_failed": 1, "read_slow": 1, "receipt_unavailable": 1, "order_rejected": 1, "order_delayed": 1,
           "order_lost": 3}


def services(error_pct=0.0, p95=100, jobs=1, worker_status="Up"):
    """A tick's `services`: every health check passes unless an argument says otherwise."""
    return {"api": {"status": "Up", "error_rate_pct": error_pct, "latency_p95_ms": p95},
            "worker": {"status": worker_status, "error_rate_pct": 0.0, "queue_depth": {"jobs": jobs}},
            "ledger": {"status": "Up", "error_rate_pct": 0.0, "latency_p95_ms": 100,
                       "throughput_rps": {"api.first": 30.0, "api.retry": 0.0, "worker.first": 7.0, "worker.retry": 0.0},
                       "queue_depth": {"ledger.requests": 0}, "pool_in_use": {"ledger.db": {"used": 4.0, "max": 13}}}}


def after_onset(**bad):
    return lambda t: services(**bad) if t > ONSET_MS else services()


class FakeSim:
    """A link whose sim answers each cmd.step with the tick script(t_ms) returns (None: no tick).

    After cmd.resume it plays: one tick per event-loop turn until cmd.pause or cmd.stop; with
    manual=True, only when the test calls tick(). `bad(t_ms)` gives that second's bad-event counts.
    cmd.action is applied (its future resolved) once its catalog delay has passed.
    """

    def __init__(self, script, bad=lambda t: {}, manual=False):
        self.script, self.bad, self.config, self.sent, self.manual = script, bad, CONFIG, [], manual
        self.effect_matrices = {sid: dict(MATRIX) for sid in ("pool_leak", "poison_message", "retry_storm")}
        self.events, self.t_ms, self.on_step, self._play = asyncio.Queue(), 0, None, None
        self.sim_config = {"flags": {"receipt_export": True, "checkout_banner": True},
                           "retry_policy": {"api": "backoff", "worker": "backoff"}}
        self.pending: dict = {}  # action_id -> (future, apply at t_ms)
        self.neutralized = False

    async def action(self, action):
        self.sent.append({"type": "cmd.action", "action": action})
        future = asyncio.get_running_loop().create_future()
        self.pending[action["action_id"]] = (future, self.t_ms + CATALOG[action["type"]]["delay_s"] * 1000)
        return future

    async def tick(self, seconds=1):
        """manual=True: play `seconds` and let the controller take them in."""
        for _ in range(seconds):
            self._step_second()
            for _ in range(5):
                await asyncio.sleep(0)

    def up(self):
        return True

    def drain(self):
        while not self.events.empty():
            self.events.get_nowait()

    def _step_second(self):
        self.t_ms += 1000
        if self.on_step:
            self.on_step(self)
        for action_id, (future, at) in list(self.pending.items()):
            if at <= self.t_ms:
                del self.pending[action_id]
                if not future.done():
                    future.set_result(self.t_ms)
        out = self.script(self.t_ms)
        if out is not None:
            self.events.put_nowait({
                "type": "evt.tick", "sim_time_ms": self.t_ms, "services": out, "config": self.sim_config,
                "bad_events": {"counts": self.bad(self.t_ms), "weights": WEIGHTS},
                "hidden": {"scenario_id": "x", "fault": {"active": self.t_ms > ONSET_MS, "onset_ms": ONSET_MS,
                                                          "neutralized": self.neutralized}}})

    async def _playing(self):
        while True:
            self._step_second()
            await asyncio.sleep(0)

    async def send(self, cmd):
        self.sent.append(cmd)
        kind = cmd["type"]
        if kind == "cmd.start_round":
            self.t_ms = 0
        elif kind == "cmd.step":
            for _ in range(cmd["n"] // 10):
                self._step_second()
        elif kind == "cmd.resume" and not self.manual:
            self._play = asyncio.get_running_loop().create_task(self._playing())
        elif kind in ("cmd.pause", "cmd.stop") and self._play:
            self._play.cancel()
            self._play = None
