"""One round's simulated world (SIM-10, TDD §3.3, §6.3): the services wired to the engine.

Each step runs the services in §6.3 order. Every 10th step ends a simulated second and emits
`evt.tick`. Events go to `emit`, in order.
"""

from sim import api as api_mod
from sim import ledger as ledger_mod
from sim import worker as worker_mod
from sim.api import Api
from sim.bad_events import WEIGHTS, BadEvents
from sim.engine import STEP_MS, Engine
from sim.jobs import Jobs, Message
from sim.ledger import Ledger
from sim.metrics import POOLS, Metrics
from sim.rng import streams
from sim.traffic import Traffic
from sim.worker import Worker

STEPS_PER_TICK = 1000 // STEP_MS
# §10.1: the delay (ms) before each action's effect completes, and its targets (closed sets, SR-7).
ACTIONS = {
    "restart_service": (8000, {"api", "worker", "ledger"}),
    "restart_all": (25_000, {None}),
    "recycle_pool": (5000, {"ledger"}),
    "set_feature_flag": (3000, {"receipt_export", "checkout_banner"}),
    "set_retry_policy": (5000, {"api", "worker"}),
    "quarantine_head_message": (2000, {"jobs"}),
    "purge_queue": (3000, {"jobs"}),
}
SLOWDOWN_FACTOR = 8  # ledger_slowdown injection (D-10): the retry_storm maintenance multiplier


class World:
    def __init__(self, scenario_id: str, seed: int, emit, pack):
        """pack: the loaded scenario pack (sim.scenarios); the world is its baseline plus the
        scenario's allowed overrides (§7.1, SCN-02)."""
        rng = streams(seed)
        self.scenario_id, self.emit = scenario_id, emit
        cfg, overrides = pack.world, pack.scenarios[scenario_id]["parameters"].get("overrides", {})
        self.flags = {**cfg["flags"], **overrides.get("flags", {})}
        policy = {**cfg["retry_policy"], **overrides.get("retry_policy", {})}
        # A feature that has never been on has no customers using it yet, so no requests either.
        self._exports_launched = self.flags["receipt_export"]
        t = cfg["traffic"]
        self.traffic = Traffic(rng["traffic"], t["rates"], amplitude=t["amplitude"], noise=t["noise"])
        self.jobs, self.bad, self.metrics = Jobs(), BadEvents(), Metrics()
        self.api = Api(rng["latency"], self._enqueue, policy["api"], self.flags)
        self.ledger = Ledger(rng["latency"], cfg["ledger"]["pool_size"], cfg["ledger"]["hold_mean_ms"])
        self.worker = Worker(rng["latency"], self.jobs, policy["worker"], cfg["worker"]["restart_backoff_ms"])
        self._arrivals: dict[str, int] = {}
        self.engine = Engine({
            "traffic": self._traffic,
            "api": lambda e: self.api.step(e.now_ms, self._arrivals),
            "ledger": self._ledger,
            "worker": lambda e: self.worker.step(e.now_ms),
            "bad_events": self._record,
        }, on_action=lambda e, apply: apply())

    def _traffic(self, e):
        self._arrivals = self.traffic.arrivals(e.now_ms)
        self._exports_launched |= self.flags["receipt_export"]
        if not self._exports_launched:
            self._arrivals["receipt_export"] = 0

    def _enqueue(self, placed_ms):
        self.bad.track(self.jobs.put(Message(placed_ms)))

    def _ledger(self, e):
        # api's calls start in this step; worker's were made last step to start in this one.
        self.ledger.step(e.now_ms, self.api.outbox + self.worker.outbox)
        self.api.outbox.clear()
        self.worker.outbox.clear()

    def _record(self, e):
        self.bad.step(e.now_ms, self.api.responses)
        self.metrics.record(self.api, self.ledger, self.worker)
        self.api.responses.clear()
        self.ledger.completed.clear()
        self.worker.attempts.clear()
        if (e.steps + 1) % STEPS_PER_TICK == 0:
            self.emit(self.tick(e.now_ms + STEP_MS))

    def tick(self, t_ms: int) -> dict:
        return {
            "type": "evt.tick", "sim_time_ms": t_ms,
            "services": self.metrics.tick(self.api, self.ledger, self.worker, self.jobs),
            "bad_events": {"counts": self.bad.take(), "weights": WEIGHTS},
            "config": {
                "flags": dict(self.flags),
                "retry_policy": {"api": self.api.policy, "worker": self.worker.policy},
                "timeout_ms": {"api.ledger_client": api_mod.TIMEOUT_MS, "worker.ledger_client": worker_mod.TIMEOUT_MS,
                               "ledger.db": ledger_mod.POOL_WAIT_MS},
                "pool_size": {**POOLS, "ledger.db": self.ledger.pool_size}, "queue_cap": {"ledger.requests": ledger_mod.QUEUE_CAP},
            },
            # For the controller only; it strips these before anything reaches the UI (T-SPOIL).
            # shortcut: no fault runs until the fault injector (SCN-03) sets these.
            "hidden": {"scenario_id": self.scenario_id, "fault": {"active": False, "neutralized": False}},
        }

    def submit_action(self, cmd: dict) -> None:
        """A validated cmd.action; evt.action_applied is emitted when its delay has passed."""
        # shortcut: actions only report being applied; their effects arrive with SCN-08 to SCN-10.
        self.engine.submit(lambda: self.emit({"type": "evt.action_applied", "action_id": cmd["action_id"],
                                              "sim_time_ms": self.engine.now_ms}),
                           ACTIONS[cmd["type"]][0])

    def inject_slowdown(self, duration_s: int) -> None:
        """Test only (D-10): multiply ledger hold times for duration_s, from the next step."""
        self.engine.submit(lambda: setattr(self.ledger, "hold_factor", SLOWDOWN_FACTOR))
        self.engine.submit(lambda: setattr(self.ledger, "hold_factor", 1.0), duration_s * 1000)
