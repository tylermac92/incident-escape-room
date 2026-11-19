"""SIM-10 link commands, driven through Session without a socket."""

import asyncio
import json

import pytest

from sim import server
from sim.scenarios import load_pack
from sim.server import Session

PACK = load_pack(server.Path(__file__).parents[1] / "scenarios")


def session(test_mode=False, start=True):
    events = []
    s = Session(events.append, test_mode, PACK)
    if start:
        s.handle(json.dumps({"type": "cmd.start_round", "scenario_id": "pool_leak", "seed": 7}))
    return s, events


def send(s, **cmd):
    s.handle(json.dumps(cmd))


def of(events, kind):
    return [e for e in events if e["type"] == kind]


def test_stepping_emits_one_tick_per_simulated_second():
    s, events = session()
    send(s, type="cmd.step", n=25)
    ticks = of(events, "evt.tick")
    assert [t["sim_time_ms"] for t in ticks] == [1000, 2000]
    tick = ticks[-1]
    assert set(tick["services"]) == {"api", "worker", "ledger"}
    assert set(tick["bad_events"]["counts"]) == set(tick["bad_events"]["weights"])
    assert tick["config"]["retry_policy"] == {"api": "backoff", "worker": "backoff"}
    assert tick["hidden"]["scenario_id"] == "pool_leak"
    assert tick["hidden"]["fault"]["active"] is False and tick["hidden"]["fault"]["neutralized"] is False


def test_same_seed_same_ticks():
    a, ea = session()
    b, eb = session()
    send(a, type="cmd.step", n=300)
    for _ in range(30):
        send(b, type="cmd.step", n=10)
    assert ea == eb and len(ea) == 30


@pytest.mark.parametrize("raw, code", [
    ("{nope", "invalid_request"),
    ("[1]", "invalid_request"),
    ('{"type": "cmd.dance"}', "unknown_command"),
    ('{"type": "cmd.start_round", "scenario_id": "meteor", "seed": 1}', "invalid_request"),
    ('{"type": "cmd.start_round", "scenario_id": "pool_leak", "seed": true}', "invalid_request"),
    ('{"type": "cmd.step", "n": 0}', "invalid_request"),
    ('{"type": "cmd.step", "n": 601}', "invalid_request"),
    ('{"type": "cmd.pause"}', "invalid_state"),
    ('{"type": "cmd.test_inject", "kind": "ledger_slowdown", "duration_s": 10}', "not_allowed"),
    ('{"type": "cmd.action", "action": {"action_id": "a1", "type": "restart_service", "target": "db"}}',
     "invalid_request"),
    ('{"type": "cmd.action", "action": {"action_id": "a1", "type": "rm_rf", "target": "api"}}', "invalid_request"),
    ('{"type": "cmd.action", "action_id": "a1", "type": "restart_service"}', "unknown_command"),
    ('{"type": "cmd.action", "action": {"action_id": "a1", "type": "set_retry_policy", "target": "api", '
     '"params": {"mode": "yolo"}}}', "invalid_request"),
    ('{"type": "cmd.action", "action": {"action_id": "a1", "type": "set_feature_flag", "target": "receipt_export", '
     '"params": {"enabled": "no"}}}', "invalid_request"),
    ('{"type": "cmd.action", "action": {"action_id": "a1", "type": "restart_all", "params": {"force": true}}}',
     "invalid_request"),
])
def test_bad_commands_get_evt_error_and_change_nothing(raw, code):
    s, events = session()
    world = s.world
    pending = list(world.engine._pending)  # the scheduled onset
    s.handle(raw)
    [error] = events
    assert (error["type"], error["code"]) == ("evt.error", code)
    assert s.world is world and s.phase == "preroll" and world.engine.steps == 0 and world.engine._pending == pending


def test_commands_need_a_round():
    s, events = session(start=False)
    send(s, type="cmd.step", n=1)
    assert [e["code"] for e in events] == ["invalid_state"]


def test_action_is_applied_after_its_delay():
    s, events = session()
    send(s, type="cmd.step", n=3)
    send(s, type="cmd.action", action={"action_id": "a7", "type": "set_retry_policy", "target": "api",
                                       "params": {"mode": "backoff"}})
    send(s, type="cmd.action", action={"action_id": "a8", "type": "restart_all"})
    send(s, type="cmd.step", n=300)
    assert of(events, "evt.action_applied") == [
        {"type": "evt.action_applied", "action_id": "a7", "sim_time_ms": 5300},
        {"type": "evt.action_applied", "action_id": "a8", "sim_time_ms": 25300}]


def test_play_pause_resume_and_step_only_in_preroll():
    async def scenario():
        s, events = session()
        send(s, type="cmd.resume")
        while len(of(events, "evt.tick")) < 2:
            await asyncio.sleep(0.01)
        send(s, type="cmd.step", n=1)  # player mode: not during play
        send(s, type="cmd.pause")
        paused_at = s.world.engine.steps
        await asyncio.sleep(0.1)
        frozen = s.world.engine.steps == paused_at
        send(s, type="cmd.step", n=1)  # nor while paused
        send(s, type="cmd.resume")
        await asyncio.sleep(0.05)
        send(s, type="cmd.stop")
        return events, frozen, s

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(server, "PLAY_RATE", 500)
        events, frozen, s = asyncio.run(scenario())
    assert frozen and s.world is None
    assert [e["code"] for e in of(events, "evt.error")] == ["not_allowed", "not_allowed"]
    times = [t["sim_time_ms"] for t in of(events, "evt.tick")]
    assert times == list(range(1000, 1000 * (len(times) + 1), 1000))  # no gaps across the pause


def test_test_mode_steps_any_time_and_injects_a_ledger_slowdown():
    async def scenario():
        s, events = session(test_mode=True)
        send(s, type="cmd.resume")
        send(s, type="cmd.pause")
        send(s, type="cmd.step", n=10)
        send(s, type="cmd.test_inject", kind="ledger_slowdown", duration_s=10)
        send(s, type="cmd.step", n=1)
        slowed = s.world.ledger.hold_factor
        send(s, type="cmd.step", n=100)
        return events, slowed, s.world.ledger.hold_factor

    events, slowed, after = asyncio.run(scenario())
    assert of(events, "evt.error") == [] and (slowed, after) == (8, 1.0)
    p95 = [t["services"]["ledger"]["latency_p95_ms"] for t in of(events, "evt.tick")]
    assert max(p95) > 3 * p95[0]  # the slowdown shows in the metrics


def test_start_round_replaces_the_current_one():
    s, events = session()
    first = s.world
    send(s, type="cmd.start_round", scenario_id="retry_storm", seed=1)
    assert s.world is not first and s.world.scenario_id == "retry_storm" and s.phase == "preroll"
