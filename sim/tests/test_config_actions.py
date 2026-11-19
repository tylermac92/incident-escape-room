"""SCN-09: recycle_pool, set_feature_flag, set_retry_policy."""

from harness import act, applied, run_s, run_to_page, signal, ticks, world


def test_recycle_alone_recovers_for_a_few_minutes_then_degrades_again():
    w, events, _, _ = run_to_page("pool_leak", 2, after_s=0)
    act(w, "recycle_pool", "ledger")
    run_s(w, 6)  # it applies at the start of the step 5 s after submission
    assert w.injector.targets.leaked_leases() == 0
    assert "unavailable" in ticks(events)[-1]["services"]["ledger"]["errors_pct_by_reason"]  # in-flight queries failed
    run_s(w, 60)
    assert signal(ticks(events)[-1], "api.error_rate_pct") < 1
    healthy_for = 0
    while signal(ticks(events)[-1], "api.error_rate_pct") < 5 and healthy_for < 900:
        run_s(w, 1)
        healthy_for += 1
    assert 120 <= healthy_for + 60 <= 600  # the leak goes on (TDD: about 2.5-4 min)
    assert ticks(events)[-1]["hidden"]["fault"]["neutralized"] is False


def test_flag_off_and_recycle_in_either_order_fixes_pool_leak_for_good():
    for first, second in ((("set_feature_flag", "receipt_export"), ("recycle_pool", "ledger")),
                          (("recycle_pool", "ledger"), ("set_feature_flag", "receipt_export"))):
        w, events, _, _ = run_to_page("pool_leak", 3, after_s=0)
        for kind, target in (first, second):
            act(w, kind, target, **({"enabled": False} if kind == "set_feature_flag" else {}))
            run_s(w, 6)
        run_s(w, 300)
        last = ticks(events)[-1]
        assert last["hidden"]["fault"]["neutralized"] is True
        assert signal(last, "api.error_rate_pct") < 1 and signal(last, "ledger.pool_used") < 6
        assert last["bad_events"]["counts"]["receipt_unavailable"] > 0  # the visible cost of the flag


def test_flag_takes_3_s_and_shows_in_the_config_within_a_tick():
    w, events = world("poison_message", 1)
    run_s(w, 10)
    a = act(w, "set_feature_flag", "checkout_banner", enabled=False)
    run_s(w, 4)
    assert applied(events)[a] == 13_000 and ticks(events)[-1]["config"]["flags"]["checkout_banner"] is False


def test_backoff_ends_the_retry_storm_within_15_s_of_taking_effect():
    w, events, _, _ = run_to_page("retry_storm", 2, after_s=0)
    a = act(w, "set_retry_policy", "api", mode="backoff")
    run_s(w, 6)
    assert applied(events)[a] and ticks(events)[-1]["config"]["retry_policy"]["api"] == "backoff"
    run_s(w, 15)
    last = ticks(events)[-1]
    assert signal(last, "ledger.queue") < 20 and last["hidden"]["fault"]["neutralized"] is True
    run_s(w, 10)  # once the 10 s windows have moved past the storm
    assert signal(ticks(events)[-1], "ledger.retry_share") < 0.25 and signal(ticks(events)[-1], "api.error_rate_pct") < 1
