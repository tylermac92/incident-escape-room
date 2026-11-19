"""CTL-04: the round state machine and the lifecycle endpoints."""

import itertools

import pytest
from fastapi.testclient import TestClient

from controller import app as app_module
from controller.errors import ApiError
from controller.game import TRANSITIONS, Game, Round
from controller.link import LinkDown

STATES = ["PREPARING", "BRIEFING", "ACTIVE", "PAUSED", "RESOLVED", "TIMED_OUT", "ENDED", "ABORTED", "DEBRIEF"]
# §6.1, written out independently of TRANSITIONS. BRIEFING -> ABORTED is for game failures.
EDGES = {("PREPARING", "BRIEFING"), ("PREPARING", "ABORTED"), ("BRIEFING", "ACTIVE"), ("BRIEFING", "ABORTED"),
         ("ACTIVE", "PAUSED"), ("PAUSED", "ACTIVE"), ("ACTIVE", "RESOLVED"), ("ACTIVE", "TIMED_OUT"),
         ("ACTIVE", "ABORTED"), ("PAUSED", "ABORTED"), ("RESOLVED", "DEBRIEF"), ("TIMED_OUT", "DEBRIEF"),
         ("ENDED", "DEBRIEF"), ("ACTIVE", "ENDED"), ("PAUSED", "ENDED")}
CONFIG = {"budget": 12, "round_time_limit_s": 720, "feed": {"interval_s": 5, "min_count": 5}, "alerts": {"api_error_rate_pct": 5, "api_latency_p95_ms": 1000,
                                                             "orders_backlog": 500, "for_s": 30}}


@pytest.mark.parametrize("mode", ["standard", "practice"])
@pytest.mark.parametrize("start,to", list(itertools.product(STATES, STATES)))
def test_every_transition(mode, start, to):
    legal = (start, to) in EDGES
    if to == "ENDED":
        legal &= mode == "practice"  # D-02
    if to == "TIMED_OUT":
        legal &= mode == "standard"
    rnd = Round("r_1", "s_1", "pool_leak", 1, 1, mode, state=start)
    if not legal:
        with pytest.raises(ApiError) as e:
            rnd.move(to, "player_restart" if to == "ABORTED" else None)
        assert (e.value.status, e.value.code, rnd.state) == (409, "invalid_state", start)
    else:
        rnd.move(to, "player_restart" if to == "ABORTED" else None)
        assert rnd.state == to


def test_table_has_no_unknown_states():
    assert set(TRANSITIONS) | {t for ts in TRANSITIONS.values() for t in ts} <= set(STATES)


class FakeLink:
    def __init__(self):
        self.sent, self.config, self.is_up = [], CONFIG, True

    def up(self):
        return self.is_up

    async def send(self, cmd):
        if not self.is_up:
            raise LinkDown
        self.sent.append(cmd["type"])


@pytest.fixture
def env(tmp_path, monkeypatch):
    async def no_preroll(self, rnd, retry):  # CTL-05's runner has its own tests
        pass

    monkeypatch.setattr(Game, "_run", no_preroll)
    link, flags = FakeLink(), {"locked": False}
    game = Game(link, lambda: flags["locked"], tmp_path / "session.json")
    monkeypatch.setattr(app_module, "game", game)
    client = TestClient(app_module.app)
    client.post("/api/sessions")
    return client, game, link, flags


def error(response):
    return response.status_code, response.json()["error"]["code"]


def prepared(client, game, state="BRIEFING"):
    body = client.post("/api/sessions/current/rounds").json()
    game.round(body["id"]).state = state  # as if the pre-roll (CTL-05) had run
    return body["id"]


def test_prepare_creates_a_hidden_round(env):
    client, game, *_ = env
    body = client.post("/api/sessions/current/rounds").json()
    assert body["state"] == "PREPARING" and body["attempt"] == 1 and body["budget_remaining"] == 12
    assert "scenario_id" not in body and "seed" not in body
    assert game.round(body["id"]).scenario_id == game.session.round_order[0]
    assert error(client.post("/api/sessions/current/rounds")) == (409, "invalid_state")


def test_start_pause_resume(env):
    client, game, link, _ = env
    rid = prepared(client, game)
    assert error(client.post(f"/api/rounds/{rid}/pause")) == (409, "invalid_state")
    assert client.post(f"/api/rounds/{rid}/start").json()["state"] == "ACTIVE"
    assert error(client.post(f"/api/rounds/{rid}/start")) == (409, "invalid_state")
    assert client.post(f"/api/rounds/{rid}/pause").json()["state"] == "PAUSED"
    body = client.post(f"/api/rounds/{rid}/resume").json()
    assert body["state"] == "ACTIVE" and body["on_call_at"] and body["paused_s"] >= 0
    assert link.sent == ["cmd.resume", "cmd.pause", "cmd.resume"]
    assert client.get(f"/api/rounds/{rid}").json()["state"] == "ACTIVE"


def test_restart_aborts_and_makes_a_fresh_attempt(env):
    client, game, link, _ = env
    rid = prepared(client, game, "PAUSED")
    old = game.round(rid)
    old.budget_remaining = 3
    new = client.post(f"/api/rounds/{rid}/restart").json()
    assert (old.state, old.abort_reason) == ("ABORTED", "player_restart") and link.sent == ["cmd.stop"]
    assert new["state"] == "PREPARING" and new["attempt"] == 2 and new["budget_remaining"] == 12
    fresh = game.round(new["id"])
    assert fresh.scenario_id == old.scenario_id and fresh.seed != old.seed
    assert error(client.post(f"/api/rounds/{rid}/restart")) == (409, "invalid_state")  # no longer current


def test_after_an_abort_prepare_retries_the_same_scenario(env):
    client, game, *_ = env
    rid = prepared(client, game, "ABORTED")
    body = client.post("/api/sessions/current/rounds").json()
    assert body["attempt"] == 2 and game.round(body["id"]).scenario_id == game.round(rid).scenario_id


def test_debrief_moves_on_then_session_complete(env):
    client, game, *_ = env
    for i in range(3):
        rid = prepared(client, game, "DEBRIEF")
        assert game.round(rid).scenario_id == game.session.round_order[i]
    assert game.session.rounds[0].debrief_closed_at  # closed by the next prepare (D-12)
    assert error(client.post("/api/sessions/current/rounds")) == (409, "session_complete")


def test_locked_refuses_prepare_start_and_restart(env):
    client, game, _, flags = env
    rid = prepared(client, game)
    flags["locked"] = True
    assert error(client.post("/api/sessions/current/rounds")) == (423, "locked")
    assert error(client.post(f"/api/rounds/{rid}/start")) == (423, "locked")
    game.round(rid).state = "ABORTED"
    assert error(client.post(f"/api/rounds/{rid}/restart")) == (423, "locked")


def test_sim_down(env):
    client, game, link, _ = env
    link.is_up = False
    assert error(client.post("/api/sessions/current/rounds")) == (503, "sim_unavailable")
    link.is_up = True
    rid = prepared(client, game)
    link.is_up = False
    assert error(client.post(f"/api/rounds/{rid}/start")) == (503, "sim_unavailable")
    assert game.round(rid).state == "BRIEFING"


def test_unknown_round_and_verb(env):
    client, *_ = env
    assert error(client.get("/api/rounds/r_nope")) == (404, "not_found")
    assert error(client.post("/api/rounds/r_nope/start")) == (404, "not_found")
    assert error(client.post("/api/rounds/r_nope/explode")) == (422, "invalid_request")


def test_controller_restart_aborts_the_live_round(env, tmp_path):
    client, game, *_ = env
    done = prepared(client, game, "DEBRIEF")
    live = prepared(client, game, "ACTIVE")
    restored = Game(FakeLink(), lambda: False, tmp_path / "session.json")
    restored.load()
    assert restored.round(done).state == "DEBRIEF"
    assert (restored.round(live).state, restored.round(live).abort_reason) == ("ABORTED", "controller_restart")
