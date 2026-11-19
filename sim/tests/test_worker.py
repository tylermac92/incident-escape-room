from sim.jobs import Jobs, Message
from sim.ledger import Ledger
from sim.rng import stream
from sim.worker import SLOTS, Worker


def make(n=0, malformed_at=None):
    jobs = Jobs()
    for i in range(n):
        jobs.put(Message(placed_ms=0, malformed=(i == malformed_at)))
    return jobs, Worker(stream(1, "latency"), jobs)


def run(worker, ledger, steps, start=0):
    """ledger(call) returns (delay ms, reason) or None to never answer."""
    calls = []
    for n in range(start, start + steps):
        worker.step(n * 100)
        for call in worker.outbox:
            calls.append(call)
            answer = ledger(call)
            if answer:
                call.done_ms, call.reason = call.start_ms + answer[0], answer[1]
        worker.outbox.clear()
    return calls


def test_job_is_processed_then_written_then_acknowledged():
    jobs, worker = make(1)
    msg = jobs.waiting[0]
    calls = run(worker, lambda c: (50, None), 5)
    assert [(c.caller, c.kind, c.attempt, c.start_ms, c.deadline_ms) for c in calls] == [("worker", "write", 1, 100, 2100)]
    assert [(a.start_ms, a.end_ms, a.reason) for a in worker.attempts] == [(0, 150, None)]
    assert msg.done_ms == 150 and jobs.depth == 0 and worker.status == "Up"


def test_handled_failure_retries_with_backoff_then_requeues_to_the_tail():
    jobs, worker = make(1)
    msg = jobs.waiting[0]
    calls = run(worker, lambda c: (10, "pool_timeout") if c.attempt < 3 else None, 50)
    assert [c.attempt for c in calls][:4] == [1, 2, 3, 1]  # at most 2 retries, then retaken from the tail
    assert 0 <= calls[1].start_ms - 200 <= 200 and 0 <= calls[2].start_ms - calls[1].start_ms - 10 <= 400 + 100
    failed = worker.attempts[0]
    assert (failed.start_ms, failed.end_ms, failed.reason) == (0, calls[2].deadline_ms, "downstream_timeout")
    assert calls[2].abandoned and msg.attempts == 2 and msg.ready_ms == failed.end_ms + 2000


def test_crash_redelivers_to_the_head_and_restarts_after_5_s():
    jobs, worker = make(5, malformed_at=0)
    poison = jobs.waiting[0]
    run(worker, lambda c: None, 1)
    assert worker.status == "Crash-looping" and list(jobs.waiting)[0] is poison and jobs.depth == 5
    run(worker, lambda c: None, 60, start=1)
    assert poison.attempts == 2  # retaken at 5 s; the next try is at 10 s
    assert [(a.start_ms, a.reason) for a in worker.attempts] == [(0, "crash"), (5000, "crash")]
    jobs.waiting.popleft()  # what quarantine_head_message will do (SCN-10)
    run(worker, lambda c: (50, None), 60, start=61)
    assert worker.status == "Up" and jobs.depth == 0


def test_crash_with_jobs_in_flight_puts_the_crasher_first():
    jobs, worker = make(SLOTS + 3, malformed_at=SLOTS)
    msgs = list(jobs.waiting)
    answered = []

    def ledger(call):  # only the first write succeeds, so one slot frees and takes the poison
        if not answered:
            answered.append(call)
            return 50, None

    run(worker, ledger, 2)
    assert list(jobs.waiting)[:SLOTS] == [msgs[SLOTS]] + msgs[1:SLOTS]
    assert sum(a.reason == "crash" for a in worker.attempts) == SLOTS  # 9 interrupted + the crasher
    assert msgs[0].done_ms == 150 and worker.down_until == 5150


def test_maximum_rate_is_about_40_jobs_per_second():
    jobs, worker = make(3000)
    ledger = Ledger(stream(2, "latency"))
    for n in range(600):
        ledger.step(n * 100, worker.outbox)
        worker.outbox.clear()
        worker.step(n * 100)
    done = [a for a in worker.attempts if a.reason is None and a.end_ms >= 10_000]
    assert 36 <= len(done) / 50 <= 46
