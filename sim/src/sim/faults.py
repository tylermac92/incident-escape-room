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
    """One fault_script kind; subclasses override onset() and neutralized(). This base does nothing."""

    def __init__(self, script: dict, rng):
        self.script, self.rng = script, rng  # rng: the round's `fault` stream

    def onset(self, t: Targets, now_ms: int) -> None:
        pass

    def neutralized(self, t: Targets) -> bool:
        return False


FAULTS: dict[str, type[Fault]] = {}  # fault_script kind -> implementation (SCN-04 to SCN-06)


class Injector:
    def __init__(self, world, scenario: dict, rng):
        self.targets = Targets(world)
        # shortcut: kinds without an implementation yet run the do-nothing Fault, until SCN-06 adds the last.
        self.fault = FAULTS.get(scenario["fault_script"]["kind"], Fault)(scenario["fault_script"], rng)
        self.active = False
        delay_ms = round(scenario["parameters"]["onset_s"] * 1000 * rng.uniform(1 - ONSET_JITTER, 1 + ONSET_JITTER))
        self.onset_ms = world.engine.submit(self._onset, delay_ms)  # sim time; hidden until the debrief

    def _onset(self):
        self.active = True
        self.fault.onset(self.targets, self.onset_ms)

    def hidden(self) -> dict:
        return {"active": self.active, "neutralized": self.active and self.fault.neutralized(self.targets),
                "onset_ms": self.onset_ms}
