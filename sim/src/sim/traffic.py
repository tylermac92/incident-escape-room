"""Traffic generator (SIM-03, TDD §8.2, §8.7, FR-3).

Each flow is a Poisson process with rate
    r(t) = r0 × (1 + amplitude·sin(2πt/period)) × (1 + ε) × (1 + burst while one runs),
where ε is drawn once per simulated second per flow, uniform within ±noise. Bursts start
every 3–5 minutes. All draws come from the `traffic` stream.
"""

import math

from sim.engine import STEP_MS

RATES = {"read": 30.0, "receipt_export": 2.0, "order": 10.0}  # r0, per second


class Traffic:
    """rng is the round's `traffic` stream from sim.rng."""

    def __init__(self, rng, rates: dict[str, float] = RATES, amplitude: float = 0.10,
                 period_s: float = 120, noise: float = 0.05, burst: float = 0.20, burst_s: float = 10,
                 burst_gap_s: tuple[float, float] = (180, 300)):
        self.rng, self.rates = rng, dict(rates)
        self.amplitude, self.period_s, self.noise = amplitude, period_s, noise
        self.burst, self.burst_s, self.burst_gap_s = burst, burst_s, burst_gap_s
        self.bursts = [rng.uniform(*burst_gap_s)]  # start times (s); the last one is the next
        self._second, self._eps = None, {}

    def rate(self, flow: str, t_s: float) -> float:
        """Current rate (per second) of a flow; t_s must not go backwards."""
        if math.floor(t_s) != self._second:
            self._second = math.floor(t_s)
            self._eps = {f: self.rng.uniform(-self.noise, self.noise) for f in self.rates}
        while t_s >= self.bursts[-1] + self.burst_s:
            self.bursts.append(self.bursts[-1] + self.rng.uniform(*self.burst_gap_s))
        in_burst = self.bursts[-1] <= t_s
        return (self.rates[flow] * (1 + self.amplitude * math.sin(2 * math.pi * t_s / self.period_s))
                * (1 + self._eps[flow]) * (1 + (self.burst if in_burst else 0)))

    def arrivals(self, now_ms: int) -> dict[str, int]:
        """Number of new requests per flow in the step starting at now_ms."""
        t_s = now_ms / 1000
        return {f: self._poisson(self.rate(f, t_s) * STEP_MS / 1000) for f in self.rates}

    def _poisson(self, mean: float) -> int:
        # Knuth's method: fine for the few arrivals per 100 ms step.
        limit, k, p = math.exp(-mean), 0, self.rng.random()
        while p > limit:
            k += 1
            p *= self.rng.random()
        return k
