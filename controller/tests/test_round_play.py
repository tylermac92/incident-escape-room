"""CTL-06: stability tracking, the nudge, and timeout outcomes, with the fake sim playing."""

import asyncio

import pytest

from fakes import ONSET_MS, FakeSim, services

from controller.game import Game

T0 = 730_000  # error rate high from onset: the page fires 30 s later


def broken_until(heal_ms, flap_at=None):
    """Bad from onset until heal_ms; optionally one bad second at flap_at."""
    return lambda t: services(error_pct=10) if ONSET_MS < t <= heal_ms or t == flap_at else services()


def play(script, tmp_path, mode="standard", until=lambda game, rnd: rnd.state == "DEBRIEF"):
    async def main():
        link = FakeSim(script)
        game = Game(link, lambda: False, tmp_path / "session.json")
        await game.new_session(mode)
        rnd = await game.prepare()
        while rnd.state == "PREPARING":
            await asyncio.sleep(0)
        await game.start(rnd.id)
        for _ in range(100_000):
            if until(game, rnd):
                break
            await asyncio.sleep(0)
        await asyncio.sleep(0)  # let the runner stop sim
        return game, rnd, link
    return asyncio.run(main())


def kinds(game):
    return [(e["kind"], e["payload"].get("to"), e["sim_time_ms"]) for e in game.events if e["kind"] != "alert"]


def test_stable_at_timeout_is_recovered_undeclared(tmp_path):
    game, rnd, link = play(broken_until(T0 + 100_000), tmp_path)
    assert rnd.t0_ms == T0 and rnd.outcome == "recovered_undeclared"
    assert rnd.ttr_s == 101  # first all-passing tick at T0 + 101 s
    end = T0 + 720_000
    assert kinds(game)[-3:] == [("nudge", None, T0 + 101_000 + 180_000), ("state_change", "TIMED_OUT", end),
                                ("state_change", "DEBRIEF", end)]
    assert rnd.debrief_opened_at and link.sent[-1] == {"type": "cmd.stop"}


def test_unstable_at_timeout_is_not_recovered(tmp_path):
    game, rnd, _ = play(broken_until(T0 + 670_000), tmp_path)  # healthy for only 49 s at the end
    assert (rnd.outcome, rnd.ttr_s, rnd.state) == ("not_recovered", None, "DEBRIEF")
    assert not any(e["kind"] == "nudge" for e in game.events)


@pytest.mark.parametrize("heal_s,outcome", [(659, "recovered_undeclared"), (660, "not_recovered")])
def test_stability_window_boundary(tmp_path, heal_s, outcome):
    # Healthy from T0 + heal_s + 1: exactly 60 s of stability at the timeout, or 59 s.
    assert play(broken_until(T0 + heal_s * 1000), tmp_path)[1].outcome == outcome


def test_a_failing_second_resets_stability(tmp_path):
    game, rnd, _ = play(broken_until(T0 + 100_000, flap_at=T0 + 200_000), tmp_path)
    assert rnd.ttr_s == 201 and rnd.outcome == "recovered_undeclared"
    assert [e["sim_time_ms"] for e in game.events if e["kind"] == "nudge"] == [T0 + 201_000 + 180_000]


def test_practice_rounds_never_time_out(tmp_path):
    game, rnd, _ = play(broken_until(T0 + 100_000), tmp_path, mode="practice",
                        until=lambda g, r: r.state != "ACTIVE" or g._tick["sim_time_ms"] > T0 + 800_000)
    assert rnd.state == "ACTIVE" and rnd.outcome is None
