"""Simulated `worker` service (SIM-07, TDD §7.1, §8.3, §9.1, §9.2).

10 slots (`worker.ledger_client` of 10). A free slot takes the head of `jobs`, processes it for
100 ms, then writes it to `ledger` with a 2000 ms timeout and the caller's retry policy.
Success acknowledges the job; running out of retries is a handled failure (`downstream_timeout`)
and requeues it to the tail. Taking a malformed job crashes the consumer: every in-flight job
goes back to the head and the consumer restarts 5 s later.

Each job attempt is recorded in `attempts` as a Response (flow "job"); reason None means completed.
"""

from dataclasses import dataclass

from sim.api import BACKOFF_BASE_MS, POLICIES, Call, Response
from sim.engine import STEP_MS

SLOTS = 10
PROCESS_MS = 100
TIMEOUT_MS = 2000
RESTART_BACKOFF_MS = 5000


@dataclass(eq=False)
class Slot:
    msg: object
    taken_ms: int
    write_at: int  # when the next write attempt starts
    attempt: int = 1
    call: Call | None = None


class Worker:
    def __init__(self, rng, jobs, policy: str = "backoff", restart_backoff_ms: int = RESTART_BACKOFF_MS):
        """rng: the round's `latency` stream (backoff jitter)."""
        self.rng, self.jobs, self.policy, self.restart_backoff_ms = rng, jobs, policy, restart_backoff_ms
        self.slots: list[Slot | None] = [None] * SLOTS
        self.free_at = [0] * SLOTS
        self.outbox: list[Call] = []  # writes starting in the next step, for ledger
        self.attempts: list[Response] = []  # drained by the metrics and bad-event phases
        self.pool_used = 0  # slots with a write in flight at the end of this step, for pool_in_use
        self.down_until = 0  # consumer restart after a crash
        self.crash_looping = False  # set by a crash, cleared by the next completed job

    @property
    def status(self) -> str:
        return "Crash-looping" if self.crash_looping else "Up"

    def step(self, now_ms: int) -> None:
        end = now_ms + STEP_MS
        self.jobs.step(now_ms)
        # ledger has run this step, so every answer before `end` is known exactly.
        for i, slot in enumerate(self.slots):
            call = slot and slot.call
            if not call:
                continue
            if call.done_ms is not None and call.done_ms < end and call.done_ms <= call.deadline_ms:
                if call.reason is None:
                    self._finish(i, call.done_ms, None)
                else:
                    self._write_failed(i, call.done_ms)
            elif call.deadline_ms < end:
                call.abandoned = True
                self._write_failed(i, call.deadline_ms)

        if self.down_until < end:
            for i in range(SLOTS):
                if self.slots[i] is None and self.jobs.waiting:
                    t = max(self.free_at[i], self.jobs.waiting[0].ready_ms, now_ms, self.down_until)
                    msg = self.jobs.take()
                    if msg.malformed:
                        self._crash(t, msg)
                        break
                    self.slots[i] = Slot(msg, t, t + PROCESS_MS)

        for slot in self.slots:
            if slot and slot.call is None and slot.write_at < end + STEP_MS:
                # shortcut: a retry due inside this step starts at the next step (up to 100 ms late),
                # because ledger has already run; exact enough for the 2 s timeout.
                start = max(slot.write_at, end)
                slot.call = Call("worker", "write", slot.attempt, start, start + TIMEOUT_MS)
                self.outbox.append(slot.call)
        self.pool_used = sum(1 for s in self.slots if s and s.call)

    def _finish(self, i, t, reason):
        slot = self.slots[i]
        self.attempts.append(Response("job", slot.taken_ms, t, reason))
        if reason is None:
            self.jobs.ack(slot.msg)
            slot.msg.done_ms = t
            self.crash_looping = False
        else:
            self.jobs.requeue(slot.msg, t)
        self.slots[i], self.free_at[i] = None, t

    def _write_failed(self, i, t):
        slot = self.slots[i]
        if slot.attempt > POLICIES[self.policy]:
            self._finish(i, t, "downstream_timeout")
            return
        delay = 0
        if self.policy == "backoff":  # exponential from 200 ms, full jitter (as in api)
            delay = round(self.rng.uniform(0, BACKOFF_BASE_MS * 2 ** (slot.attempt - 1)))
        slot.attempt, slot.write_at, slot.call = slot.attempt + 1, t + delay, None

    def _crash(self, t, msg):
        for slot in self.slots:
            if slot:
                if slot.call:
                    slot.call.abandoned = True  # ledger still processes it: wasted work
                self.attempts.append(Response("job", slot.taken_ms, t, "crash"))
        self.attempts.append(Response("job", t, t, "crash"))
        self.jobs.redeliver_all(msg)
        self.slots = [None] * SLOTS
        self.down_until = t + self.restart_backoff_ms
        self.free_at = [self.down_until] * SLOTS
        self.crash_looping = True
