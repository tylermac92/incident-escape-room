"""Fault injector (SCN-03, TDD §5.2, §7, §8.6, SR-6).

A scenario's fault_script acts on simulated objects only, and only through Targets: ledger.db
leases, messages on jobs, ledger hold times, the api retry policy, and feature flags. This module
imports nothing that could reach the OS, files, the network or processes (test_faults checks it).

Each round, onset is scheduled from the scenario's onset_s with seeded ±20% jitter. Each tick,
`active` (onset has happened) and `neutralized` (the scenario's "holds" rule, §7.3–§7.5) are
reported in the hidden fields.
"""

import math

from sim.jobs import Message

ONSET_JITTER = 0.20


class Targets:
    """Everything a fault script may touch."""

    def __init__(self, world):
        self._w = world

    def leak_leases(self, should_leak) -> None:
        """should_leak(call) -> bool, asked as each ledger call takes a connection."""
        self._w.ledger.leak = should_leak

    def leaked_leases(self) -> int:
        return sum(1 for b in self._w.ledger.busy_until if b == math.inf)

    def add_batch(self, size: int, at_ms: int) -> Message:
        """Put `size` orders on jobs; the first is malformed. Returns that one."""
        msgs = [Message(at_ms, malformed=(i == 0)) for i in range(size)]
        for msg in msgs:
            self._w.bad.track(self._w.jobs.put(msg))
        return msgs[0]

    def in_jobs(self, msg: Message) -> bool:
        return msg in self._w.jobs.all_messages()

    def set_hold_factor(self, factor: float) -> None:
        self._w.ledger.hold_factor = factor

    def after(self, delay_ms: int, do) -> None:
        self._w.engine.submit(do, delay_ms)

    def retry_policy(self, caller: str) -> str:
        return {"api": self._w.api, "worker": self._w.worker}[caller].policy

    def flag(self, name: str) -> bool:
        return self._w.flags[name]

    def set_flag(self, name: str, on: bool) -> None:
        self._w.flags[name] = on


class Fault:
    """One fault_script kind. Subclasses implement onset() and neutralized()."""

    def __init__(self, script: dict, rng):
        self.script, self.rng = script, rng  # rng: the round's `fault` stream

    def onset(self, t: Targets, now_ms: int) -> None:
        raise NotImplementedError

    def neutralized(self, t: Targets) -> bool:
        raise NotImplementedError


class ExportLeak(Fault):
    """pool_leak (§7.3): once receipt_export is on, some exports never return their connection."""

    def onset(self, t, now_ms):
        t.set_flag("receipt_export", True)  # the change that starts it
        p = self.script["leak_probability"]
        t.leak_leases(lambda call: call.kind == "receipt_export" and self.rng.random() < p)

    def neutralized(self, t):
        return not t.flag("receipt_export") and t.leaked_leases() == 0


class PoisonBatch(Fault):
    """poison_message (§7.4): a partner-import batch whose first order is malformed."""

    def onset(self, t, now_ms):
        self.poison = t.add_batch(self.script["batch_size"], now_ms)

    def neutralized(self, t):
        return not t.in_jobs(self.poison)


class LedgerSlowdown(Fault):
    """retry_storm (§7.5): a short ledger index-maintenance window that multiplies hold times."""

    def onset(self, t, now_ms):
        t.set_hold_factor(self.script["multiplier"])
        t.after(round(self.script["duration_s"] * 1000), lambda: t.set_hold_factor(1.0))

    def neutralized(self, t):
        return t.retry_policy("api") == "backoff"


# fault_script kind -> implementation; the pack loader accepts exactly these kinds.
FAULTS: dict[str, type[Fault]] = {"export_leak": ExportLeak, "poison_batch": PoisonBatch,
                                  "ledger_slowdown": LedgerSlowdown}


class Injector:
    def __init__(self, world, scenario: dict, rng):
        self.targets = Targets(world)
        self.fault = FAULTS[scenario["fault_script"]["kind"]](scenario["fault_script"], rng)
        self.active = False
        delay_ms = round(scenario["parameters"]["onset_s"] * 1000 * rng.uniform(1 - ONSET_JITTER, 1 + ONSET_JITTER))
        self.onset_ms = world.engine.submit(self._onset, delay_ms)  # sim time; hidden until the debrief

    def _onset(self):
        self.active = True
        self.fault.onset(self.targets, self.onset_ms)

    def hidden(self) -> dict:
        return {"active": self.active, "neutralized": self.active and self.fault.neutralized(self.targets),
                "onset_ms": self.onset_ms}
