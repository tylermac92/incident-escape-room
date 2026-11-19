from collections import Counter

import pytest

from sim.engine import Engine
from sim.rng import stream
from sim.traffic import RATES, Traffic

THIRTY_MIN_STEPS = 30 * 60 * 10


def baseline(seed, rates=RATES):
    traffic, totals = Traffic(stream(seed, "traffic"), rates), Counter()
    engine = Engine({"traffic": lambda e: totals.update(traffic.arrivals(e.now_ms))})
    for _ in range(THIRTY_MIN_STEPS):
        engine.step()
    return traffic, totals


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_thirty_minute_mean_rate_is_within_3_percent(seed):
    _, totals = baseline(seed)
    for flow, r0 in RATES.items():
        assert abs(totals[flow] / 1800 / r0 - 1) <= 0.03, (flow, totals[flow] / 1800)


def test_rates_are_configurable():
    _, totals = baseline(1, {"read": 5.0})
    assert set(totals) == {"read"} and abs(totals["read"] / 1800 / 5 - 1) <= 0.03


def test_rate_follows_sine_noise_and_bursts():
    traffic = Traffic(stream(1, "traffic"))
    peak, trough = traffic.rate("read", 30), traffic.rate("read", 90)  # quarter and three-quarter period
    assert 30 * 1.10 * 0.95 <= peak <= 30 * 1.10 * 1.05
    assert 30 * 0.90 * 0.95 <= trough <= 30 * 0.90 * 1.05


def test_burst_adds_20_percent_for_10_seconds():
    flat = Traffic(stream(1, "traffic"), amplitude=0, noise=0)
    start = flat.bursts[0]
    rates = [flat.rate("read", t) for t in (start - 0.1, start, start + 9.9, start + 10)]
    assert rates == pytest.approx([30, 36, 36, 30])


def test_bursts_are_seeded_and_3_to_5_minutes_apart():
    first, _ = baseline(4)
    again, _ = baseline(4)
    assert first.bursts == again.bursts
    starts = first.bursts
    assert 180 <= starts[0] <= 300
    assert all(180 <= b - a <= 300 for a, b in zip(starts, starts[1:]))
    assert len(starts) >= 6  # 30 minutes holds at least six


def test_same_seed_same_arrivals():
    a, b = Traffic(stream(5, "traffic")), Traffic(stream(5, "traffic"))
    assert [a.arrivals(t * 100) for t in range(600)] == [b.arrivals(t * 100) for t in range(600)]
