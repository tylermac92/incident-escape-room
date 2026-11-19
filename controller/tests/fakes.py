"""A scripted stand-in for sim on the link, and healthy-by-default tick contents."""

import asyncio

CONFIG = {"budget": 12, "round_time_limit_s": 720, "stability_window_s": 60,
          "alerts": {"api_error_rate_pct": 5, "api_latency_p95_ms": 1000, "orders_backlog": 500, "for_s": 30}}
ONSET_MS = 700_000
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

    After cmd.resume it plays: one tick per event-loop turn until cmd.pause or cmd.stop.
    `bad(t_ms)` gives that second's bad-event counts.
    """

    def __init__(self, script, bad=lambda t: {}):
        self.script, self.bad, self.config, self.sent = script, bad, CONFIG, []
        self.events, self.t_ms, self.on_step, self._play = asyncio.Queue(), 0, None, None

    def up(self):
        return True

    def drain(self):
        while not self.events.empty():
            self.events.get_nowait()

    def _step_second(self):
        self.t_ms += 1000
        if self.on_step:
            self.on_step(self)
        out = self.script(self.t_ms)
        if out is not None:
            self.events.put_nowait({
                "type": "evt.tick", "sim_time_ms": self.t_ms, "services": out,
                "bad_events": {"counts": self.bad(self.t_ms), "weights": WEIGHTS},
                "hidden": {"scenario_id": "x", "fault": {"active": self.t_ms > ONSET_MS, "onset_ms": ONSET_MS}}})

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
        elif kind == "cmd.resume":
            self._play = asyncio.get_running_loop().create_task(self._playing())
        elif kind in ("cmd.pause", "cmd.stop") and self._play:
            self._play.cancel()
            self._play = None
