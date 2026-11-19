from sim.api import CLIENT_POOL, Api, Response
from sim.rng import stream


def run(api, ledger, arrivals_at=None, steps=100):
    """Step `api` with a fake ledger: ledger(call) returns (delay ms, reason) or None to never answer."""
    calls = []
    for n in range(steps):
        now = n * 100
        api.step(now, (arrivals_at or {}).get(now, {}))
        for call in api.outbox:
            calls.append(call)
            answer = ledger(call)
            if answer:
                call.done_ms, call.reason = call.start_ms + answer[0], answer[1]
        api.outbox.clear()
    return calls


def one_read(**kw):
    return {"arrivals_at": {0: {"read": 1}}, **kw}


def make(policy="backoff", enqueued=None):
    return Api(stream(1, "latency"), (enqueued if enqueued is not None else []).append, policy)


def test_success_adds_own_processing_time():
    api = make()
    calls = run(api, lambda c: (50, None), **one_read())
    assert [(c.attempt, c.start_ms) for c in calls] == [(1, 15)]
    assert api.responses == [Response("read", 0, 65)]


def test_backoff_times_out_three_times_then_fails_at_the_timeout_values():
    api = make("backoff")
    calls = run(api, lambda c: None, **one_read())
    assert [c.attempt for c in calls] == [1, 2, 3]  # at most 2 retries
    assert all(c.abandoned for c in calls)
    assert calls[0].deadline_ms == 1015
    gaps = [b.deadline_ms - 1000 - a.deadline_ms for a, b in zip(calls, calls[1:])]
    assert 0 <= gaps[0] <= 200 and 0 <= gaps[1] <= 400  # full jitter, exponential from 200 ms
    [response] = api.responses
    assert response.reason == "timeout" and response.end_ms == calls[-1].deadline_ms


def test_backoff_jitter_spans_its_range():
    gaps = []
    for seed in range(200):
        api = Api(stream(seed, "latency"), [].append, "backoff")
        calls = run(api, lambda c: None, steps=40, **one_read())
        gaps.append(calls[1].deadline_ms - 1000 - calls[0].deadline_ms)
    assert min(gaps) < 20 and max(gaps) > 180 and all(0 <= g <= 200 for g in gaps)


def test_aggressive_retries_four_times_immediately():
    api = make("aggressive")
    calls = run(api, lambda c: None, **one_read())
    assert [c.deadline_ms for c in calls] == [1015, 2015, 3015, 4015, 5015]  # each starts at the last timeout
    assert api.responses == [Response("read", 0, 5015, "timeout")]


def test_retry_then_success_and_ledger_reasons_propagate():
    api = make("aggressive")
    run(api, lambda c: (10, "queue_full") if c.attempt < 3 else (40, None), **one_read())
    assert len(api.responses) == 1 and api.responses[0].reason is None
    api = make("backoff")
    run(api, lambda c: (10, "pool_timeout"), **one_read())
    assert [r.reason for r in api.responses] == ["pool_timeout"]


def test_late_ledger_answer_is_a_timeout_and_the_call_stays_abandoned():
    api = make("backoff")
    calls = run(api, lambda c: (1500, None) if c.attempt == 1 else (50, None), **one_read())
    assert calls[0].abandoned and not calls[1].abandoned
    assert api.responses[0].reason is None and api.responses[0].end_ms == calls[1].start_ms + 50


def test_client_pool_caps_calls_in_flight():
    api = make()
    run(api, lambda c: None, arrivals_at={0: {"read": 70}}, steps=2)
    assert api.clients_peak == CLIENT_POOL


def test_orders_answered_202_after_enqueue():
    enqueued = []
    api = make(enqueued=enqueued)
    calls = run(api, lambda c: (50, None), arrivals_at={300: {"order": 2}})
    assert calls == [] and enqueued == [315, 315]
    assert api.responses == [Response("order", 300, 315)] * 2


def test_down_fails_every_request_immediately():
    enqueued = []
    api = make(enqueued=enqueued)
    api.up = False
    calls = run(api, lambda c: (50, None), arrivals_at={0: {"read": 1, "receipt_export": 1, "order": 1}})
    assert calls == [] and enqueued == []
    assert [(r.flow, r.latency_ms, r.reason) for r in api.responses] == [
        ("read", 0, "unavailable"), ("receipt_export", 0, "unavailable"), ("order", 0, "unavailable")]

