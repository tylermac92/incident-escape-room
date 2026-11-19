"""SCN-08: restart_service and restart_all, as state changes inside the model."""

import math

from harness import act, applied, run_s, run_to_page, signal, ticks, world


def test_restart_api_fails_every_request_for_8_s():
    w, events = world("poison_message", 1)
    run_s(w, 30)
    a = act(w, "restart_service", "api")
    run_s(w, 4)
    mid = ticks(events)[-1]
    assert mid["services"]["api"]["status"] == "Restarting" and signal(mid, "api.error_rate_pct") > 30
    assert mid["services"]["api"]["errors_pct_by_reason"].keys() == {"unavailable"}
    assert mid["bad_events"]["counts"]["order_rejected"] > 0
    run_s(w, 20)
    assert applied(events)[a] == 38_000 and ticks(events)[-1]["services"]["api"]["status"] == "Up"
    assert signal(ticks(events)[-1], "api.error_rate_pct") == 0  # the window has moved past the outage


def test_restart_ledger_stalls_reads_and_reclaims_every_lease():
    w, events, _, _ = run_to_page("pool_leak", 1, after_s=0)
    assert w.injector.targets.leaked_leases() >= 6
    a = act(w, "restart_service", "ledger")
    run_s(w, 4)
    mid = ticks(events)[-1]
    assert mid["services"]["ledger"]["status"] == "Restarting" and signal(mid, "ledger.pool_used") == 0
    assert w.injector.targets.leaked_leases() == 0 and not w.ledger.queue
    assert "unavailable" not in mid["services"]["api"]["errors_pct_by_reason"]  # stalled, so callers time out
    run_s(w, 70)
    after = ticks(events)[-1]
    assert a in applied(events) and signal(after, "api.error_rate_pct") < 1  # mitigated...
    assert after["hidden"]["fault"]["neutralized"] is False  # ...but the leak goes on (§10.2: doesn't hold)


def test_restart_worker_returns_in_flight_jobs_and_orders_wait():
    w, events = world("pool_leak", 3)
    run_s(w, 30)
    taken = list(w.jobs.in_flight)
    act(w, "restart_service", "worker")
    run_s(w, 1)
    assert list(w.jobs.waiting)[: len(taken)] == taken and w.worker.status == "Restarting"
    run_s(w, 6)
    assert signal(ticks(events)[-1], "worker.completed_rps") < 5 and w.jobs.depth > 50  # orders wait
    run_s(w, 30)
    assert w.worker.status == "Up" and w.jobs.depth < 20


def test_restart_worker_does_not_help_poison_message():
    w, events, _, _ = run_to_page("poison_message", 2, after_s=0)
    act(w, "restart_service", "worker")
    run_s(w, 12)  # 8 s down, then it takes the same message again
    assert w.worker.status == "Crash-looping" and w.jobs.waiting[0] is w.injector.fault.poison


def test_restart_all_is_down_25_s_and_empties_jobs():
    w, events, _, _ = run_to_page("poison_message", 3, after_s=0)
    depth, at = w.jobs.depth, w.engine.now_ms
    a = act(w, "restart_all")
    run_s(w, 1)
    lost = ticks(events)[-1]["bad_events"]["counts"]["order_lost"]
    assert lost == depth - 1  # every queued order but the malformed one
    assert all(ticks(events)[-1]["services"][s]["status"] == "Restarting" for s in ("api", "worker", "ledger"))
    run_s(w, 26)
    assert applied(events)[a] == at + 25_000
    assert ticks(events)[-1]["hidden"]["fault"]["neutralized"] is True  # the poison went with the queue
    run_s(w, 30)
    assert w.worker.status == "Up" and w.jobs.depth < 20


def test_retry_storm_restart_ledger_storm_resumes_restart_api_recovers_but_does_not_hold():
    w, events, _, _ = run_to_page("retry_storm", 1, after_s=0)
    act(w, "restart_service", "ledger")
    run_s(w, 8 + 20)
    assert signal(ticks(events)[-1], "ledger.retry_share") > 0.6  # storm back within seconds of ledger returning

    w, events, _, _ = run_to_page("retry_storm", 1, after_s=0)
    act(w, "restart_service", "api")
    run_s(w, 8 + 60)
    last = ticks(events)[-1]
    assert signal(last, "api.error_rate_pct") < 1 and signal(last, "ledger.retry_share") < 0.25
    assert last["hidden"]["fault"]["neutralized"] is False  # still aggressive
