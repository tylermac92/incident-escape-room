"""Simulated `jobs` queue and `jobs.dlq` (SIM-06, TDD §7.1, §8.3, §9.1).

FIFO. A job whose processing failed (a handled failure) goes back to the tail 2 s later. Jobs
in flight when the consumer crashed go back to the head. There is no max-delivery: a message
reaches `jobs.dlq` only through a player action (SCN-10). `attempts` counts deliveries.
"""

import heapq
import itertools
from collections import deque
from dataclasses import dataclass

from sim.engine import STEP_MS

REQUEUE_DELAY_MS = 2000


@dataclass(eq=False)
class Message:
    placed_ms: int
    malformed: bool = False  # processing it crashes the consumer (poison_message, SCN-05)
    attempts: int = 0  # deliveries so far
    ready_ms: int = 0  # when it last became available to take
    done_ms: int | None = None  # acknowledged at
    lost: bool = False  # removed by an action (order_lost)

    def __post_init__(self):
        self.ready_ms = self.placed_ms


class Jobs:
    def __init__(self):
        self.waiting: deque[Message] = deque()
        self.in_flight: list[Message] = []  # in delivery order
        self.dlq: list[Message] = []
        self._requeue: list[tuple[int, int, Message]] = []  # (ready ms, seq, message)
        self._seq = itertools.count()

    @property
    def depth(self) -> int:
        """Waiting plus in flight; a failed job waiting out its 2 s requeue delay counts as in flight."""
        return len(self.waiting) + len(self.in_flight) + len(self._requeue)

    @property
    def head_attempts(self) -> int:
        return self.waiting[0].attempts if self.waiting else 0

    def all_messages(self) -> list[Message]:
        """Every message in jobs: waiting, in flight, or waiting out a requeue delay."""
        return [*self.waiting, *self.in_flight, *(m for _, _, m in self._requeue)]

    def put(self, msg: Message) -> Message:
        self.waiting.append(msg)
        return msg

    def take(self) -> Message:
        msg = self.waiting.popleft()
        msg.attempts += 1
        self.in_flight.append(msg)
        return msg

    def ack(self, msg: Message) -> None:
        self.in_flight.remove(msg)

    def requeue(self, msg: Message, t_ms: int) -> None:
        """Handled failure at t_ms: back to the tail REQUEUE_DELAY_MS later."""
        self.in_flight.remove(msg)
        msg.ready_ms = t_ms + REQUEUE_DELAY_MS
        heapq.heappush(self._requeue, (msg.ready_ms, next(self._seq), msg))

    def redeliver_all(self, crashed: Message | None = None) -> None:
        """Consumer crash or restart: every in-flight job goes back to the head, any crasher first."""
        others = [m for m in self.in_flight if m is not crashed]
        self.waiting.extendleft(reversed(others))
        if crashed:
            self.waiting.appendleft(crashed)
        self.in_flight.clear()

    def remove_all(self) -> list[Message]:
        """Empty jobs (restart_all, purge_queue): every message, waiting, in flight or delayed."""
        removed = self.all_messages()
        self.waiting.clear()
        self.in_flight.clear()
        self._requeue.clear()
        return removed

    def step(self, now_ms: int) -> None:
        """Move requeued jobs whose delay ends in this step to the tail."""
        while self._requeue and self._requeue[0][0] < now_ms + STEP_MS:
            self.waiting.append(heapq.heappop(self._requeue)[2])
