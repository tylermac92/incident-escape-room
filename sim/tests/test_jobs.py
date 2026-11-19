from sim.jobs import Jobs, Message


def queue(n):
    jobs = Jobs()
    msgs = [jobs.put(Message(placed_ms=i)) for i in range(n)]
    return jobs, msgs


def test_fifo():
    jobs, msgs = queue(3)
    assert [jobs.take() for _ in range(3)] == msgs


def test_handled_failure_requeues_to_the_tail_after_2_s():
    jobs, (a, b, c) = queue(3)
    jobs.take()
    jobs.requeue(a, 150)
    assert list(jobs.waiting) == [b, c] and jobs.depth == 3  # waiting out the delay still counts
    jobs.step(2000)
    assert list(jobs.waiting) == [b, c]  # due at 2150: not in the step starting at 2000
    jobs.step(2100)
    assert list(jobs.waiting) == [b, c, a] and a.ready_ms == 2150
    jobs.take(), jobs.take()
    assert jobs.take() is a and a.attempts == 2


def test_crash_redelivers_in_flight_jobs_to_the_head_crasher_first():
    jobs, (a, b, c, d) = queue(4)
    jobs.take(), jobs.take(), jobs.take()  # a, b, c in flight; c crashes the consumer
    jobs.redeliver_all(c)
    assert list(jobs.waiting) == [c, a, b, d] and jobs.in_flight == []
    assert jobs.head_attempts == 1
    jobs.take()
    jobs.redeliver_all(c)
    assert jobs.head_attempts == 2  # the same message, delivered again


def test_depth_head_attempts_and_dlq():
    jobs, (a, b) = queue(2)
    assert (jobs.depth, jobs.head_attempts, len(jobs.dlq)) == (2, 0, 0)
    jobs.take()
    assert jobs.depth == 2  # in flight counts
    jobs.ack(a)
    assert jobs.depth == 1


def test_no_automatic_dead_lettering():
    jobs, (poison,) = queue(1)
    for _ in range(100):
        jobs.take()
        jobs.redeliver_all(poison)
    assert poison.attempts == 100 and jobs.dlq == [] and list(jobs.waiting) == [poison]
