"""CTL-03: sessions, their mirror in session.json, and what the UI may see of them."""

import json

import pytest
from fastapi.testclient import TestClient

from controller import app as app_module
from controller.game import SCENARIO_IDS, Game, Round


@pytest.fixture
def game(tmp_path, monkeypatch):
    game = Game(tmp_path / "session.json")
    monkeypatch.setattr(app_module, "game", game)
    return game


@pytest.fixture
def client(game):
    return TestClient(app_module.app)


def error(response):
    return response.status_code, response.json()["error"]["code"]


def debrief_all(session):
    session.rounds = [Round(f"r_{i}", session.id, sid, 1, 1, state="DEBRIEF") for i, sid in enumerate(session.round_order)]


def test_create_defaults_to_standard_with_a_hidden_random_order(client, game):
    body = client.post("/api/sessions").json()
    assert body["mode"] == "standard" and body["status"] == "in_progress" and body["current_round"] is None
    assert sorted(game.session.round_order) == sorted(SCENARIO_IDS)
    assert not any(sid in json.dumps(body) for sid in SCENARIO_IDS)  # §9.7: no spoilers


def test_orders_vary(game):
    orders = {tuple(game.new_session("standard").round_order) for _ in range(60)}
    assert len(orders) > 1


def test_practice_mode_and_validation(client):
    assert client.post("/api/sessions", json={"mode": "practice"}).json()["mode"] == "practice"
    assert error(client.post("/api/sessions", json={"mode": "hard"})) == (422, "invalid_request")
    assert error(client.post("/api/sessions", json={"mode": "standard", "x": 1})) == (422, "invalid_request")


def test_new_session_abandons_the_old_one(client, game):
    client.post("/api/sessions")
    old = game.session
    client.post("/api/sessions")
    assert old.status == "abandoned" and game.session.id != old.id
    assert client.get("/api/sessions/current").json()["id"] == game.session.id


def test_no_session_is_404(client):
    assert error(client.get("/api/sessions/current")) == (404, "not_found")
    assert error(client.post("/api/sessions/current/complete")) == (404, "not_found")


def test_complete_needs_three_debriefs_and_is_idempotent(client, game):
    client.post("/api/sessions")
    assert error(client.post("/api/sessions/current/complete")) == (409, "invalid_state")
    debrief_all(game.session)
    first = client.post("/api/sessions/current/complete").json()
    closed_at = game.session.current_round.debrief_closed_at
    assert first["status"] == "complete" and closed_at
    assert client.post("/api/sessions/current/complete").json() == first
    assert game.session.current_round.debrief_closed_at == closed_at
    assert {r["scenario_id"] for r in first["rounds"]} == set(SCENARIO_IDS)  # revealed after debrief


def test_session_survives_a_restart(client, game, tmp_path):
    client.post("/api/sessions", json={"mode": "practice"})
    debrief_all(game.session)
    client.post("/api/sessions/current/complete")
    restored = Game(tmp_path / "session.json")
    restored.load()
    assert restored.session == game.session


def test_unwritable_or_unreadable_file_does_not_break_the_game(tmp_path):
    game = Game(tmp_path / "missing-dir" / "session.json")
    game.new_session("standard")  # save fails, logged, gameplay goes on
    (tmp_path / "bad.json").write_text("{not json")
    broken = Game(tmp_path / "bad.json")
    broken.load()
    assert broken.session is None
