"""SCN-02: one baseline world, the scenario's allowed overrides, and a live config snapshot."""

import copy
import dataclasses

from harness import PACK, run_s, ticks, world


def config(scenario_id):
    w, events = world(scenario_id)
    run_s(w, 1)
    return ticks(events)[-1]["config"]


def test_baseline_world_and_scenario_overrides():
    base = config("poison_message")
    assert base == {
        "flags": {"receipt_export": True, "checkout_banner": True},
        "retry_policy": {"api": "backoff", "worker": "backoff"},
        "timeout_ms": {"api.ledger_client": 1000, "worker.ledger_client": 2000, "ledger.db": 2000},
        "pool_size": {"api.ledger_client": 50, "worker.ledger_client": 10, "ledger.db": 10},
        "queue_cap": {"ledger.requests": 300},
    }
    assert config("retry_storm") == {**base, "retry_policy": {"api": "aggressive", "worker": "backoff"}}
    assert config("pool_leak") == {**base, "flags": {"receipt_export": False, "checkout_banner": True}}


def test_pack_tuning_needs_no_code_change():
    world_cfg = copy.deepcopy(PACK.world)
    world_cfg["ledger"]["pool_size"] = 6
    world_cfg["traffic"]["rates"]["read"] = 60
    w, events = world("poison_message", pack=dataclasses.replace(PACK, world=world_cfg))
    run_s(w, 60)
    last = ticks(events)[-1]
    assert last["config"]["pool_size"]["ledger.db"] == 6 and last["services"]["ledger"]["pool_in_use"]["ledger.db"]["max"] == 6
    assert 50 < last["services"]["api"]["throughput_rps"]["read"] < 70


def test_exports_before_launch_after_launch_and_after_turning_off():
    w, events = world("pool_leak")  # receipt_export off: not launched, so nobody asks for exports
    run_s(w, 30)
    assert ticks(events)[-1]["services"]["api"]["throughput_rps"]["receipt_export"] == 0
    w.flags["receipt_export"] = True  # what onset (SCN-04) or the flag action (SCN-09) does
    run_s(w, 30)
    assert ticks(events)[-1]["services"]["api"]["throughput_rps"]["receipt_export"] > 1
    w.flags["receipt_export"] = False
    run_s(w, 1)
    assert ticks(events)[-1]["config"]["flags"]["receipt_export"] is False  # within one tick
    run_s(w, 29)
    last = ticks(events)[-1]
    assert last["services"]["api"]["throughput_rps"]["receipt_export"] > 1  # still asked for...
    assert last["bad_events"]["counts"]["receipt_unavailable"] > 0  # ...and refused, which customers feel
    assert last["services"]["api"]["error_rate_pct"] < 1  # but a deliberate refusal is not an api error
