import asyncio

import pytest

from sim.engine import PHASES, STEP_MS, Engine, play


def traced():
    """An engine whose phases and actions append (sim ms, what) to a log."""
    log = []
    phases = {name: (lambda e, n=name: log.append((e.now_ms, n))) for name in PHASES}
    engine = Engine(phases, on_action=lambda e, a: log.append((e.now_ms, a)))
    return engine, log


def test_time_advances_in_fixed_steps():
    engine, _ = traced()
    assert engine.now_ms == 0
    for _ in range(3):
        engine.step()
    assert (engine.steps, engine.now_ms, STEP_MS) == (3, 300, 100)


def test_phases_run_in_order_after_due_actions():
    engine, log = traced()
    engine.submit("act")
    engine.step()
    assert [what for _, what in log] == ["act", "traffic", "api", "ledger", "worker", "faults", "bad_events"]


def test_actions_apply_after_their_delay_in_arrival_order():
    engine, log = traced()
    engine.step()  # now 100 ms
    assert engine.submit("late", delay_ms=5000) == 5100
    assert engine.submit("first", delay_ms=250) == 400  # part of a step rounds up
    assert engine.submit("second", delay_ms=300) == 400  # same step: arrival order
    for _ in range(60):
        engine.step()
    assert [(t, a) for t, a in log if a not in PHASES] == [(400, "first"), (400, "second"), (5100, "late")]


def test_unknown_phase_is_rejected():
    with pytest.raises(ValueError):
        Engine({"traffik": lambda e: None})


def test_play_paces_steps_to_wall_clock():
    async def run():
        engine = Engine()
        task = asyncio.create_task(play(engine, steps_per_s=100))
        await asyncio.sleep(0.25)
        task.cancel()
        return engine.steps
    assert 15 <= asyncio.run(run()) <= 35  # loose: CI timers are coarse


def test_pause_freezes_time_and_delays_and_resume_changes_nothing():
    async def interrupted():
        engine, log = traced()
        engine.submit("act", delay_ms=3000)
        task = asyncio.create_task(play(engine, steps_per_s=200))
        await asyncio.sleep(0.05)
        task.cancel()  # pause
        paused_at = engine.steps
        await asyncio.sleep(0.05)
        assert engine.steps == paused_at  # no stepping while paused
        task = asyncio.create_task(play(engine, steps_per_s=200))  # resume
        while engine.steps < 40:
            await asyncio.sleep(0.01)
        task.cancel()
        return log[: 40 * len(PHASES) + 1]

    straight, log = traced()
    straight.submit("act", delay_ms=3000)
    for _ in range(40):
        straight.step()
    assert asyncio.run(interrupted()) == log
    assert (3000, "act") in log
