"""SCN-04: pool_leak (TDD §7.3)."""

import math

import pytest

from harness import PACK, holds, run_s, run_to_page, signal, ticks, world

CELLS = PACK.scenarios["pool_leak"]["signature"]["cells"]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_pages_api_latency_high_and_shows_its_signature(seed):
    w, events, rule, t0 = run_to_page("pool_leak", seed)
    tk = ticks(events)
    assert rule == "api_latency_high" and tk[t0]["sim_time_ms"] > w.injector.onset_ms
    assert [c["text"] for c in CELLS if not holds(c, tk[-1])] == []  # at T0+60 s


def test_the_pool_climbs_in_steps_and_never_gives_connections_back():
    w, events = world("pool_leak", 2)
    onset_s = math.ceil(w.injector.onset_ms / 1000)
    run_s(w, onset_s)
    before = [signal(t, "ledger.pool_used") for t in ticks(events)[onset_s - 60:]]
    assert 3 <= sum(before) / len(before) <= 6  # about 4 at baseline
    leaked, p95 = [], []
    for _ in range(400):
        run_s(w, 1)
        leaked.append(w.injector.targets.leaked_leases())
        p95.append(signal(ticks(events)[-1], "ledger.latency_p95_ms"))
    assert leaked == sorted(leaked) and leaked[-1] >= 6  # steps up, never down, even when traffic dips
    assert max(p for p, k in zip(p95, leaked) if k <= 4) < 400  # latency holds until about 6 have leaked


def test_holds_only_when_the_flag_is_off_and_no_leases_are_leaked():
    w, events, _, _ = run_to_page("pool_leak", 1, after_s=0)
    assert ticks(events)[-1]["hidden"]["fault"] == {**ticks(events)[-1]["hidden"]["fault"], "active": True, "neutralized": False}
    w.flags["receipt_export"] = False  # what set_feature_flag does (SCN-09)
    run_s(w, 60)
    last = ticks(events)[-1]
    assert last["hidden"]["fault"]["neutralized"] is False  # leaked connections are still gone...
    assert signal(last, "ledger.pool_used") == 10 and signal(last, "api.error_rate_pct") > 50  # ...so no recovery
    w.ledger.busy_until = [0.0] * w.ledger.pool_size  # what recycle_pool does (SCN-09)
    run_s(w, 1)
    assert ticks(events)[-1]["hidden"]["fault"]["neutralized"] is True
