"""Simulated `ledger` service (SIM-05, TDD §7.1, §8.3, §9.1, D-20).

Calls (sim.api.Call, from `api` and `worker`) join `ledger.requests`, a FIFO capped at 300.
The head takes the first free `ledger.db` connection. A request that has not got one within
2000 ms of arriving (queue time counts, D-20) fails with `pool_timeout`. Hold times are
lognormal (σ = 0.4) around a mean per kind. Each step is simulated event by event, so
times inside the step are exact.

A call whose caller gave up (it finishes after its deadline) is still processed, and counts
toward throughput with reason `timeout`: wasted work. The caller treats it as a timeout too.
"""

import heapq
import math
from collections import deque

from sim.engine import STEP_MS

QUEUE_CAP = 300
POOL_SIZE = 10
POOL_WAIT_MS = 2000
SIGMA = 0.4
HOLD_MEAN_MS = {"read": 80, "write": 120, "receipt_export": 300}


class Ledger:
    def __init__(self, rng):
        """rng: the round's `latency` stream (hold times)."""
        self.rng = rng
        self.queue: deque = deque()  # ledger.requests: calls waiting for a connection
        self.busy_until = [0.0] * POOL_SIZE  # per ledger.db connection; math.inf for a leaked lease
        self.busy_ms = 0.0  # total connection hold time, for utilization
        self.completed: list = []  # calls finished this step (any reason), drained by metrics
        self.peak_in_use = 0  # most connections leased at once this step, for pool_in_use
        self.hold_factor = 1.0  # multiplies hold times: a slowdown (test injection, retry_storm maintenance)
        self._running: list = []  # (done ms, seq, call)
        self._seq = 0

    @property
    def status(self) -> str:
        return "Up"  # shortcut: no downtime until restart actions (SCN-08) add Restarting

    def in_use(self, t_ms: float) -> int:
        return sum(1 for b in self.busy_until if b > t_ms)

    def step(self, now_ms: int, calls) -> None:
        end = now_ms + STEP_MS
        self.peak_in_use = self.in_use(now_ms)
        arrivals = deque(sorted(calls, key=lambda c: c.start_ms))  # sorted() is stable: arrival order
        while True:
            head_t = start_t = expire_t = math.inf
            if self.queue:
                head = self.queue[0]
                start_t = max(head.start_ms, min(self.busy_until))
                expire_t = head.start_ms + POOL_WAIT_MS
                head_t = min(start_t, expire_t)
            arrive_t = arrivals[0].start_ms if arrivals else math.inf
            if min(head_t, arrive_t) >= end:
                assert not arrivals, "calls must start inside the step they are given in"
                break
            if head_t <= arrive_t:  # a connection freed at t serves the queue before a new arrival at t
                self.queue.popleft()
                if start_t <= expire_t:
                    self._start(head, start_t)
                else:
                    self._fail(head, expire_t, "pool_timeout")
            else:
                call = arrivals.popleft()
                if len(self.queue) >= QUEUE_CAP:
                    self._fail(call, call.start_ms, "queue_full")
                else:
                    self.queue.append(call)
        while self._running and self._running[0][0] < end:
            self.completed.append(heapq.heappop(self._running)[2])

    def _start(self, call, t):
        mean = HOLD_MEAN_MS[call.kind]
        hold = self.hold_factor * self.rng.lognormvariate(math.log(mean) - SIGMA**2 / 2, SIGMA)
        i = self.busy_until.index(min(self.busy_until))
        self.busy_until[i] = t + hold
        self.busy_ms += hold
        self.peak_in_use = max(self.peak_in_use, self.in_use(t))
        call.done_ms = math.ceil(t + hold)
        call.reason = "timeout" if call.done_ms > call.deadline_ms else None
        self._seq += 1
        heapq.heappush(self._running, (call.done_ms, self._seq, call))

    def _fail(self, call, t, reason):
        call.done_ms, call.reason = math.ceil(t), reason
        self.completed.append(call)
