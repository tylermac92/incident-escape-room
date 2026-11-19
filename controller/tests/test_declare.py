"""CTL-14: declare resolved."""

import asyncio

from fakes import ONSET_MS, services
from fastapi.testclient import TestClient
from test_actions import on_call

from controller import app as app_module
from controller.errors import ApiError

T0 = 730_000
HEALS = lambda t: services(error_pct=10) if ONSET_MS < t <= T0 + 5_000 else services()  # noqa: E731


async def declare(game, rnd):
    try:
        await game.declare(rnd.id)
    except ApiError as e:
        return e.status, e.code, e.message, e.details
    return rnd.state


def test_too_early_is_not_stable_and_the_round_continues(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path, HEALS)  # at T0 + 1 s: still failing
        failing = await declare(game, rnd)
        await link.tick(26)  # to T0 + 27 s; healthy since T0 + 6 s: 21 s green
        green = await declare(game, rnd)
        return failing, green, rnd

    failing, green, rnd = asyncio.run(main())
    assert failing[:3] == (409, "not_stable", "Not yet — 1 health check is failing.")
    assert failing[3] == {"green_for_s": 0, "required_s": 60, "penalty": 50, "failing_checks": ["api_errors"]}
    assert green[2] == "Not yet — health checks have been green for 21 of the required 60 seconds."
    assert green[3]["failing_checks"] == [] and rnd.state == "ACTIVE" and rnd.premature_declarations == 2


def test_the_penalty_counts_three_times_at_most(tmp_path):
    async def main():
        game, rnd, _ = await on_call(tmp_path, HEALS)
        return [(await declare(game, rnd))[3]["penalty"] for _ in range(5)]

    assert asyncio.run(main()) == [50, 50, 50, 0, 0]


def test_stable_for_w_resolves_and_stops_sim(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path, HEALS)
        await link.tick(64)  # from T0 + 1 s to T0 + 65 s; healthy since T0 + 6 s: 59 s green
        early = await declare(game, rnd)
        await link.tick()
        return early, await declare(game, rnd), game, rnd, link

    early, state, game, rnd, link = asyncio.run(main())
    assert early[1] == "not_stable" and state == "DEBRIEF"
    assert (rnd.outcome, rnd.ttr_s) == ("recovered", 6) and link.sent[-1] == {"type": "cmd.stop"}
    moves = [e["payload"].get("to") for e in game.events if e["kind"] == "state_change"]
    assert moves[-2:] == ["RESOLVED", "DEBRIEF"]


def test_no_countdown_is_exposed(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path, HEALS)
        await link.tick(30)
        return game.view(rnd)

    view = asyncio.run(main())
    assert "healthy_since_ms" not in view and all(set(c) == {"id", "passing", "value", "threshold"}
                                                  for c in view["health_checks"])


def test_route(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.game, "session", None)
    response = TestClient(app_module.app).post("/api/rounds/r_x/declare-resolved")
    assert (response.status_code, response.json()["error"]["code"]) == (404, "not_found")
