"""Simulated `api` service (SIM-04, TDD §7.1, §8.3, §9.1).

Each step, `api` takes the step's arrivals, answers orders with 202 once they are enqueued
to `jobs`, and calls `ledger` for synchronous requests through a 50-slot client pool, with a
per-attempt timeout and the current retry policy.

Interface with `ledger` (SIM-05): calls for this step are left in `outbox`; `ledger` takes
them and sets `done_ms` (possibly in the future) and `reason` (None means success). A call the
caller has given up on is marked `abandoned`; `ledger` still processes it (wasted work).
"""

import heapq
import itertools
from dataclasses import dataclass

from sim.engine import STEP_MS

OWN_MS = 15
TIMEOUT_MS = 1000
CLIENT_POOL = 50
POLICIES = {"backoff": 2, "aggressive": 4}  # retries per request
BACKOFF_BASE_MS = 200
SYNC_FLOWS = ("read", "receipt_export")


@dataclass(eq=False)
class Call:
    """One attempt from a caller to `ledger`."""
    caller: str
    kind: str
    attempt: int  # 1 is the first attempt
    start_ms: int
    deadline_ms: int
    done_ms: int | None = None
    reason: str | None = None
    abandoned: bool = False


@dataclass
class Response:
    """A finished customer request; reason None means success (orders: 202)."""
    flow: str
    start_ms: int
    end_ms: int
    reason: str | None = None
    disabled: bool = False  # receipt export answered "temporarily unavailable": not an error, still bad

    @property
    def latency_ms(self) -> int:
        return self.end_ms - self.start_ms


class Api:
    def __init__(self, rng, enqueue, policy: str = "backoff", flags: dict | None = None):
        """rng: the round's `latency` stream (backoff jitter). enqueue(placed_ms) adds an order to `jobs`.

        flags: the world's feature flags, shared and live.
        """
        self.rng, self.enqueue, self.policy = rng, enqueue, policy
        self.flags = flags if flags is not None else {"receipt_export": True}
        self.up = True  # False while Restarting (SCN-08)
        self.outbox: list[Call] = []
        self.responses: list[Response] = []  # drained by the metrics and bad-event phases
        self.clients_peak = 0  # most client slots in use this step, for pool_in_use
        self._in_flight: dict[Call, tuple[str, int]] = {}  # call -> (flow, request start)
        self._pending: list[tuple[int, int, str, int, int]] = []  # (ready, seq, flow, request start, attempt)
        self._seq = itertools.count()

    @property
    def status(self) -> str:
        return "Up" if self.up else "Restarting"

    def step(self, now_ms: int, arrivals: dict[str, int]) -> None:
        # shortcut: ledger runs after api in a step, so a timeout or ledger answer is noticed at the
        # next step boundary and a retry starts up to 100 ms late; the recorded times stay exact.
        for call, (flow, started) in list(self._in_flight.items()):
            # ledger sets done_ms when it starts a call, so an answer counts only once it is in the past.
            if call.done_ms is not None and call.done_ms <= min(call.deadline_ms, now_ms):
                self._finish(call, flow, started, call.done_ms, call.reason)
            elif now_ms >= call.deadline_ms:
                call.abandoned = True
                self._finish(call, flow, started, call.deadline_ms, "timeout")

        for flow, count in arrivals.items():
            for _ in range(count):
                if not self.up:
                    self.responses.append(Response(flow, now_ms, now_ms, "unavailable"))
                elif flow == "receipt_export" and not self.flags["receipt_export"]:
                    self.responses.append(Response(flow, now_ms, now_ms + OWN_MS, disabled=True))
                elif flow in SYNC_FLOWS:
                    self._schedule(now_ms + OWN_MS, flow, now_ms, 1)
                else:
                    self.enqueue(now_ms + OWN_MS)
                    self.responses.append(Response(flow, now_ms, now_ms + OWN_MS))

        # Attempts ready this step take a free client slot in ready order; waiting counts toward the timeout.
        waiting = []
        while self._pending and self._pending[0][0] < now_ms + STEP_MS:
            ready, _, flow, started, attempt = heapq.heappop(self._pending)
            deadline = ready + TIMEOUT_MS
            if deadline <= now_ms:
                self._retry_or_fail(flow, started, attempt, deadline, "timeout")
            elif len(self._in_flight) < CLIENT_POOL:
                call = Call("api", flow, attempt, max(ready, now_ms), deadline)
                self._in_flight[call] = (flow, started)
                self.outbox.append(call)
            else:
                waiting.append((ready, flow, started, attempt))
        for ready, flow, started, attempt in waiting:
            heapq.heappush(self._pending, (ready, next(self._seq), flow, started, attempt))
        self.clients_peak = len(self._in_flight)

    def _schedule(self, ready, flow, started, attempt):
        heapq.heappush(self._pending, (ready, next(self._seq), flow, started, attempt))

    def _finish(self, call, flow, started, at_ms, reason):
        del self._in_flight[call]
        if reason is None:
            self.responses.append(Response(flow, started, at_ms))
        else:
            self._retry_or_fail(flow, started, call.attempt, at_ms, reason)

    def _retry_or_fail(self, flow, started, attempt, at_ms, reason):
        if attempt > POLICIES[self.policy]:
            self.responses.append(Response(flow, started, at_ms, reason))
            return
        delay = 0
        if self.policy == "backoff":  # exponential from 200 ms, full jitter
            delay = round(self.rng.uniform(0, BACKOFF_BASE_MS * 2 ** (attempt - 1)))
        self._schedule(at_ms + delay, flow, started, attempt + 1)
