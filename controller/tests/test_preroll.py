"""CTL-05: the controller-stepped pre-roll, against a scripted stand-in for sim."""

import asyncio

import pytest

from controller import game as game_module
from controller.game import Game
from controller.link import LinkDown
from fakes import ONSET_MS, FakeSim, after_onset, services

async def prepared(link, locked=lambda: False, tmp=None):
    game = Game(link, locked, tmp / "session.json")
    await game.new_session("standard")
    await game.prepare()
    while True:  # until the pre-roll (and its one retry) has finished
        rnd = game.session.current_round
        if rnd.state == "BRIEFING" or rnd.state == "ABORTED" and game._task.done():
            return game
        await asyncio.sleep(0)


def run(link, tmp_path, **kw):
    async def main():
        return await prepared(link, tmp=tmp_path, **kw)
    return asyncio.run(main())


def test_stops_in_the_second_the_page_fires(tmp_path):
    link = FakeSim(after_onset(error_pct=10))
    game = run(link, tmp_path)
    rnd = game.session.current_round
    # Bad from 701 s; the 30th consecutive bad evaluation is at 730 s.
    assert (rnd.state, rnd.t0_ms, rnd.t_onset_ms) == ("BRIEFING", 730_000, ONSET_MS)
    assert link.sent[0] == {"type": "cmd.start_round", "scenario_id": rnd.scenario_id, "seed": rnd.seed}
    assert link.sent[1:] == [{"type": "cmd.step", "n": 10}] * 730  # then stays paused
    view = game.view(rnd)
    assert view["timer_remaining_s"] == 720 and view["t_ms"] == 730_000  # the timer starts at T0
    assert view["alerts"] == [{"rule_id": "api_error_rate_high", "state": "FIRING", "fired_at_ms": 730_000,
                               "cleared_at_ms": None, "is_page": True}]
    assert "hidden" not in str(view) and not {"scenario_id", "t_onset_ms", "seed"} & set(view)


def test_same_second_ties_page_in_table_order(tmp_path):
    game = run(FakeSim(after_onset(error_pct=10, p95=2000)), tmp_path)
    alerts = {a["rule_id"]: a["is_page"] for a in game.view(game.session.current_round)["alerts"]}
    assert alerts == {"api_error_rate_high": True, "api_latency_high": False}  # D-22


def test_no_alert_before_onset(tmp_path):
    game = run(FakeSim(lambda t: services(jobs=900 if t > ONSET_MS + 100_000 else 1000 if t < 100_000 else 1)), tmp_path)
    rnd = game.session.current_round
    assert rnd.state == "BRIEFING" and rnd.t0_ms == ONSET_MS + 130_000  # the baseline spike never armed


def test_no_page_aborts_then_retries_once_with_a_new_seed(tmp_path):
    link = FakeSim(lambda t: services())
    game = run(link, tmp_path)
    first, second = game.session.rounds
    assert [(r.state, r.abort_reason, r.attempt) for r in game.session.rounds] == [
        ("ABORTED", "preroll_no_alert", 1), ("ABORTED", "preroll_no_alert", 2)]
    assert first.seed != second.seed and first.scenario_id == second.scenario_id
    steps = sum(c["type"] == "cmd.step" for c in link.sent)
    assert steps == 2 * (ONSET_MS + game_module.PREROLL_LIMIT_MS + 1000) // 1000
    assert [c["type"] for c in link.sent].count("cmd.stop") == 2


@pytest.mark.parametrize("failure,reason", [
    ({"type": "evt.error", "code": "internal_error"}, "sim_unavailable"),
    ({"type": "link.down"}, "sim_unavailable"),
])
def test_sim_failure_aborts(tmp_path, failure, reason):
    link = FakeSim(lambda t: services() if t < 50_000 else None)
    link.on_step = lambda sim: sim.t_ms == 50_000 and sim.events.put_nowait(failure)
    rnd = run(link, tmp_path).session.current_round
    assert (rnd.state, rnd.abort_reason, rnd.attempt) == ("ABORTED", reason, 1)


def test_silent_sim_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(game_module, "HEARTBEAT_TIMEOUT_S", 0.05)
    rnd = run(FakeSim(lambda t: services() if t < 5_000 else None), tmp_path).session.current_round
    assert (rnd.state, rnd.abort_reason) == ("ABORTED", "sim_unavailable")


def test_link_lost_while_sending(tmp_path):
    link = FakeSim(lambda t: services())

    async def send(cmd):
        if cmd["type"] == "cmd.step" and link.t_ms >= 3000:
            raise LinkDown
        await FakeSim.send(link, cmd)

    link.send = send
    assert run(link, tmp_path).session.current_round.abort_reason == "sim_unavailable"


def test_isolation_failure_aborts(tmp_path):
    link = FakeSim(lambda t: services())
    rnd = run(link, tmp_path, locked=lambda: link.t_ms >= 20_000).session.current_round
    assert (rnd.state, rnd.abort_reason) == ("ABORTED", "isolation_check_failed")


def test_late_ticks_from_a_stopped_round_are_skipped(tmp_path):
    link = FakeSim(after_onset(error_pct=10))
    stale = {"type": "evt.tick", "sim_time_ms": 999_000, "services": services(error_pct=99),
             "hidden": {"fault": {"active": True, "onset_ms": 0}}}
    link.on_step = lambda sim: sim.t_ms == 1000 and sim.events.put_nowait(stale)
    assert run(link, tmp_path).session.current_round.t0_ms == 730_000


def test_round_event_log(tmp_path):
    """CTL-07: every event has a strictly increasing seq and a sim time."""
    game = run(FakeSim(after_onset(error_pct=10)), tmp_path)
    assert [(e["seq"], e["sim_time_ms"], e["kind"], e["payload"]) for e in game.events] == [
        (1, 0, "state_change", {"from": None, "to": "PREPARING"}),
        (2, 730_000, "state_change", {"from": "PREPARING", "to": "BRIEFING"})]
