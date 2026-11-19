"""CTL-10: scored impact B and the counters, as exact functions of the bad-event series."""

import random

from fakes import WEIGHTS

from controller.impact import Impact


def feed(series, t0_index=None):
    """series: per-second counts; seconds after index t0_index count toward B."""
    impact = Impact()
    for i, counts in enumerate(series):
        impact.add(counts, WEIGHTS, after_t0=t0_index is not None and i > t0_index)
    return impact


def test_b_starts_after_t0_and_weights_lost_orders_by_three():
    series = [{"read_failed": 2}] * 5 + [{"order_lost": 1, "read_slow": 1}] * 5
    c = feed(series, t0_index=4).counters()
    assert (c["pre_alert_impact"], c["impact"]) == (10, 20)


def test_customers_affected_is_the_last_five_minutes_capped():
    assert feed([{"read_failed": 3000}]).counters()["customers_affected_5m"] == 2500
    impact = feed([{"read_failed": 7}] + [{}] * 299)
    assert impact.counters()["customers_affected_5m"] == 7
    impact.add({}, WEIGHTS, after_t0=False)  # the first second leaves the window
    assert impact.counters()["customers_affected_5m"] == 0


def test_tickets_open_per_40_events_and_close_after_quiet():
    impact = feed([{"order_delayed": 39}])
    assert impact.counters()["open_tickets"] == 0
    impact.add({"order_delayed": 41}, WEIGHTS, False)  # 80 in all
    assert impact.counters()["open_tickets"] == 2
    opens = []
    for _ in range(60):
        impact.add({}, WEIGHTS, False)
        opens.append(impact.counters()["open_tickets"])
    # Quiet for 30 s, then one closes every 10 s: at quiet seconds 40 and 50.
    assert opens[38] == 2 and opens[39] == 1 and opens[48] == 1 and opens[49] == 0 and opens[-1] == 0


def test_a_bad_second_restarts_the_quiet_clock():
    impact = feed([{"read_failed": 40}] + [{}] * 35 + [{"read_failed": 1}] + [{}] * 39)
    assert impact.counters()["open_tickets"] == 1
    impact.add({}, WEIGHTS, False)
    assert impact.counters()["open_tickets"] == 0


def test_counters_match_a_direct_computation_on_random_series():
    rng = random.Random(6)
    categories = list(WEIGHTS)
    series = [{c: rng.choice([0, 0, 0, rng.randint(1, 30)]) for c in categories} for _ in range(900)]
    c = feed(series, t0_index=600).counters()
    totals = [sum(s.values()) for s in series]
    weighted = [sum(WEIGHTS[k] * n for k, n in s.items()) for s in series]
    assert c["customers_affected_5m"] == min(2500, sum(totals[-300:]))
    assert (c["pre_alert_impact"], c["impact"]) == (sum(weighted[:601]), sum(weighted[601:]))
    assert 0 <= c["open_tickets"] <= sum(totals) // 40
