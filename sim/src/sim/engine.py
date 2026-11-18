"""Fixed-step engine, simulation clock and pacing (SIM-01, TDD §6.2, §6.3, §8.1, D-05).

Simulation time advances only in steps of STEP_MS. Pacing is the caller's choice:
- stepped: call step() directly, as fast as possible (pre-roll in every build, test mode).
- play: run play(), which steps PLAY_STEPS_PER_S times per wall-clock second.
Pause means not stepping (cancel the play task): sim time stops, so action delays,
which are counted in sim time, freeze with it.
"""

import asyncio
import heapq
import itertools
from collections.abc import Callable

STEP_MS = 100
PLAY_STEPS_PER_S = 10
# Phases after "due actions take effect", in the order each step runs them (§6.3).
PHASES = ("traffic", "api", "ledger", "worker", "faults", "bad_events")

Handler = Callable[["Engine"], None]


class Engine:
    def __init__(self, phases: dict[str, Handler] | None = None,
                 on_action: Callable[["Engine", object], None] | None = None):
        unknown = set(phases or {}) - set(PHASES)
        if unknown:
            raise ValueError(f"unknown phases: {sorted(unknown)}")
        self._phases = [(phases or {}).get(name) for name in PHASES]
        self._on_action = on_action
        self.steps = 0
        self._pending: list[tuple[int, int, object]] = []  # (due step, arrival number, action)
        self._arrivals = itertools.count()

    @property
    def now_ms(self) -> int:
        return self.steps * STEP_MS

    def submit(self, action, delay_ms: int = 0) -> int:
        """Queue an action; it takes effect at the start of the next step plus its delay.

        Returns the sim time (ms) it will take effect. Same-step actions apply in arrival order.
        """
        due = self.steps + -(-delay_ms // STEP_MS)  # a delay that is not a whole step rounds up
        heapq.heappush(self._pending, (due, next(self._arrivals), action))
        return due * STEP_MS

    def step(self) -> None:
        while self._pending and self._pending[0][0] <= self.steps:
            action = heapq.heappop(self._pending)[2]
            if self._on_action:
                self._on_action(self, action)
        for handler in self._phases:
            if handler:
                handler(self)
        self.steps += 1


async def play(engine: Engine, steps_per_s: float = PLAY_STEPS_PER_S) -> None:
    """Step at a fixed wall-clock rate until cancelled (cancelling is how play pauses)."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    for i in itertools.count(1):
        engine.step()
        # Deadlines from the start, so a slow step does not make the clock drift.
        await asyncio.sleep(max(0.0, start + i / steps_per_s - loop.time()))
