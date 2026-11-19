"""Bad customer event accounting (SIM-08, TDD §8.4, §11.1 B, FR-6).

The single source of customer impact. Counts are kept per simulated second and taken by the tick.
"""

from collections import Counter, deque

from sim.engine import STEP_MS

WEIGHTS = {"read_failed": 1, "read_slow": 1, "receipt_unavailable": 1, "order_rejected": 1,
           "order_delayed": 1, "order_lost": 3}
SLOW_MS = 2000
ORDER_TARGET_MS = 30_000


class BadEvents:
    def __init__(self):
        self.counts: Counter = Counter()
        self._orders: deque = deque()  # placed orders (sim.jobs.Message), oldest first

    def track(self, msg) -> None:
        """An order was placed on `jobs`."""
        self._orders.append(msg)

    def lost(self, msgs) -> None:
        """Orders removed by purge, restart_all, or quarantine of a healthy message."""
        for msg in msgs:
            msg.lost = True
            self.counts["order_lost"] += 1

    def step(self, now_ms: int, responses) -> None:
        """Count this step's finished `api` requests and the orders whose 30 s target ends in it."""
        for r in responses:
            if r.flow == "read":
                if r.reason is not None:
                    self.counts["read_failed"] += 1
                elif r.latency_ms > SLOW_MS:
                    self.counts["read_slow"] += 1
            elif r.flow == "receipt_export":
                if r.reason is not None or r.disabled:
                    self.counts["receipt_unavailable"] += 1
            elif r.reason is not None:
                self.counts["order_rejected"] += 1
        # worker has run this step, so an order still not done by its breach time is late. Once each.
        while self._orders and self._orders[0].placed_ms + ORDER_TARGET_MS < now_ms + STEP_MS:
            msg = self._orders.popleft()
            breach = msg.placed_ms + ORDER_TARGET_MS
            if not msg.lost and (msg.done_ms is None or msg.done_ms > breach):
                self.counts["order_delayed"] += 1

    def take(self) -> dict[str, int]:
        """This second's counts, every category present, then start the next second."""
        counts = {c: self.counts[c] for c in WEIGHTS}
        self.counts.clear()
        return counts
