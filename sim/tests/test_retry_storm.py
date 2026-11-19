"""SCN-06: retry_storm (TDD §7.5)."""

import math

import pytest

from harness import PACK, holds, run_s, run_to_page, signal, ticks, world

SIGNATURE = PACK.scenarios["retry_storm"]["signature"]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_pages_an_api_rule_and_shows_its_signature(seed):
    w, events, rule, t0 = run_to_page("retry_storm", seed)
    assert rule in SIGNATURE["page"] and ticks(events)[t0]["sim_time_ms"] > w.injector.onset_ms
    assert [c["text"] for c in SIGNATURE["cells"] if not holds(c, ticks(events)[-1])] == []


def test_the_storm_outlasts_the_maintenance_window():
    w, events = world("retry_storm", 4)
    onset_s = math.ceil(w.injector.onset_ms / 1000)
    run_s(w, onset_s + 5)
    assert w.ledger.hold_factor == 8
    run_s(w, 20)
    assert w.ledger.hold_factor == 1.0  # maintenance is over...
    run_s(w, 120)
    last = ticks(events)[-1]
    assert signal(last, "ledger.retry_share") > 0.6 and signal(last, "api.error_rate_pct") > 60  # ...the storm isn't
    assert signal(last, "ledger.throughput_rps") > 2 * 32  # more than twice what customers ask for


def test_holds_only_with_backoff():
    w, events, _, _ = run_to_page("retry_storm", 1, after_s=0)
    assert ticks(events)[-1]["hidden"]["fault"]["neutralized"] is False
    w.api.policy = "backoff"  # what set_retry_policy does (SCN-09)
    run_s(w, 1)
    assert ticks(events)[-1]["hidden"]["fault"]["neutralized"] is True
