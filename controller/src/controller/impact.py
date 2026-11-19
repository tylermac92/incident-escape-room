"""Impact accounting and the counters players see (CTL-10, TDD §8.4, §9.8, §11.1).

Everything here is an exact function of the per-second bad-event counts from sim. Counters run
through the pre-roll (D-09); scored impact B counts only seconds after T0.
"""

from collections import deque

CUSTOMERS_CAP = 2500  # the simulated active-customer count
CUSTOMERS_WINDOW_S = 300
EVENTS_PER_TICKET = 40
QUIET_BEFORE_CLOSING_S, CLOSE_EVERY_S = 30, 10


class Impact:
    def __init__(self):
        self.window: deque = deque(maxlen=CUSTOMERS_WINDOW_S)  # bad events per second
        self.total = 0  # bad events since the round started
        self.pre_alert = 0  # weighted, up to and including T0's second: shown, never scored
        self.scored = 0  # B: weighted, after T0 until the round ends
        self.closed = 0
        self.quiet_s = 0  # seconds in a row with no bad event in any category

    def add(self, counts: dict, weights: dict, after_t0: bool) -> None:
        events = sum(counts.values())
        weighted = sum(weights[category] * n for category, n in counts.items())
        if after_t0:
            self.scored += weighted
        else:
            self.pre_alert += weighted
        self.window.append(events)
        self.total += events
        self.quiet_s = 0 if events else self.quiet_s + 1
        # After 30 quiet seconds, one ticket closes every 10 s: at 40 s, 50 s, ...
        closing = self.quiet_s > QUIET_BEFORE_CLOSING_S and (self.quiet_s - QUIET_BEFORE_CLOSING_S) % CLOSE_EVERY_S == 0
        if closing and self.closed < self.opened:
            self.closed += 1

    @property
    def opened(self) -> int:
        return self.total // EVENTS_PER_TICKET

    def counters(self) -> dict:
        return {"customers_affected_5m": min(CUSTOMERS_CAP, sum(self.window)),
                "open_tickets": self.opened - self.closed,
                "pre_alert_impact": self.pre_alert, "impact": self.scored}
