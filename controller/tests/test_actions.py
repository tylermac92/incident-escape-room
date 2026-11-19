"""CTL-12: the action catalog, request validation, preconditions, budget, and idempotency."""

import asyncio

import pytest
from fakes import CONTENT, ONSET_MS, FakeSim, services
from fastapi.testclient import TestClient

from controller import app as app_module
from controller.errors import ApiError
from controller.game import Game

BROKEN = lambda t: services(error_pct=10) if t > ONSET_MS else services()  # noqa: E731  pages at 730 s


async def on_call(tmp_path, script=BROKEN):
    """A standard round that has just gone ACTIVE, with a sim that ticks only when told."""
    link = FakeSim(script, manual=True)
    game = Game(link, lambda: False, tmp_path / "session.json")
    game.content = CONTENT
    await game.new_session("standard")
    rnd = await game.prepare()
    while rnd.state == "PREPARING":
        await asyncio.sleep(0)
    await game.start(rnd.id)
    await link.tick()
    return game, rnd, link


def request(n, kind, target=None, **params):
    return {"client_request_id": f"c-{n}", "type": kind, "target": target, "params": params}


async def code(coro):
    try:
        await coro
    except ApiError as e:
        return e.status, e.code
    return 201, "accepted"


def test_accepted_action_is_charged_and_sent(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path)
        body = await game.act(rnd.id, request(1, "set_retry_policy", "api", mode="aggressive"))
        return body, link.sent[-1], rnd.budget_remaining

    body, sent, budget = asyncio.run(main())
    action = body["action"]
    assert (body["budget_remaining"], budget, body["sandbox_target"]) == (11, 11, "sim/api")
    assert (action["id"], action["status"], action["cost"]) == ("a_0001", "pending", 1)
    assert action["effective_at_ms"] - action["submitted_at_ms"] == 5000
    assert sent == {"type": "cmd.action", "action": {"action_id": "a_0001", "type": "set_retry_policy",
                                                     "target": "api", "params": {"mode": "aggressive"}}}


def test_preconditions_reject_without_charge(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path)
        results = {}
        results["no_change"] = await code(game.act(rnd.id, request(1, "set_feature_flag", "receipt_export", enabled=True)))
        await game.act(rnd.id, request(2, "restart_service", "ledger"))
        results["same_target"] = await code(game.act(rnd.id, request(3, "recycle_pool", "ledger")))
        results["other_target"] = await code(game.act(rnd.id, request(4, "restart_service", "api")))
        results["budget"] = rnd.budget_remaining  # 12 - 3 - 3
        await link.tick(8)  # both restarts applied
        await game.act(rnd.id, request(6, "restart_service", "worker"))
        await link.tick(8)
        try:
            await game.act(rnd.id, request(7, "restart_all"))
        except ApiError as e:
            results["insufficient"] = (e.code, e.message, e.details)
        return results

    r = asyncio.run(main())
    assert r["no_change"] == (409, "no_change")
    assert r["same_target"] == (409, "action_in_progress") and r["other_target"] == (201, "accepted")
    assert r["budget"] == 6
    assert r["insufficient"] == ("insufficient_budget", "Restart everything costs 10 points; you have 3 left.",
                                 {"cost": 10, "budget_remaining": 3})


def test_a_pending_restart_all_blocks_everything(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path)
        await game.act(rnd.id, request(1, "restart_all"))
        blocked = await code(game.act(rnd.id, request(2, "set_feature_flag", "checkout_banner", enabled=False)))
        await link.tick(25)
        return blocked, await code(game.act(rnd.id, request(3, "set_feature_flag", "checkout_banner", enabled=False)))

    assert asyncio.run(main()) == ((409, "action_in_progress"), (201, "accepted"))


@pytest.mark.parametrize("tweak,req", [
    (lambda svc: svc["ledger"].update(status="Restarting"), request(1, "recycle_pool", "ledger")),
    (lambda svc: svc["api"].update(status="Restarting"), request(1, "set_retry_policy", "api", mode="aggressive")),
    (lambda svc: svc["worker"].update(status="Restarting"), request(1, "restart_all")),
    (lambda svc: svc["worker"]["queue_depth"].update(jobs=0), request(1, "purge_queue", "jobs")),
])
def test_target_unavailable(tmp_path, tweak, req):
    def script(t):
        svc = BROKEN(t)
        if t > 731_000:
            tweak(svc)
        return svc

    async def main():
        game, rnd, link = await on_call(tmp_path, script)
        await link.tick()
        return await code(game.act(rnd.id, req)), rnd.budget_remaining

    assert asyncio.run(main()) == ((409, "target_unavailable"), 12)


def test_crash_looping_worker_can_still_be_restarted(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path, lambda t: services(error_pct=10 * (t > ONSET_MS),
                                                                     worker_status="Crash-looping"))
        return await code(game.act(rnd.id, request(1, "restart_service", "worker")))

    assert asyncio.run(main()) == (201, "accepted")


def test_duplicate_request_returns_the_original_answer(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path)
        first = await game.act(rnd.id, request(1, "recycle_pool", "ledger"))
        again = await game.act(rnd.id, request(1, "recycle_pool", "ledger"))
        rejected = await code(game.act(rnd.id, request(2, "set_feature_flag", "checkout_banner", enabled=True)))
        await link.tick(6)  # the recycle completes
        repeat = await code(game.act(rnd.id, request(2, "set_feature_flag", "checkout_banner", enabled=True)))
        sends = sum(c["type"] == "cmd.action" for c in link.sent)
        return first, again, rejected, repeat, rnd.budget_remaining, sends

    first, again, rejected, repeat, budget, sends = asyncio.run(main())
    assert again == first and budget == 11 and sends == 1
    assert rejected == repeat == (409, "no_change")


def test_only_while_active(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path)
        await game.pause(rnd.id)
        return await code(game.act(rnd.id, request(1, "recycle_pool", "ledger")))

    assert asyncio.run(main()) == (409, "invalid_state")


@pytest.fixture
def client(tmp_path, monkeypatch):
    game = Game(FakeSim(BROKEN), lambda: False, tmp_path / "session.json")
    monkeypatch.setattr(app_module, "game", game)
    monkeypatch.setattr(app_module.link, "config", FakeSim(BROKEN).config)
    return TestClient(app_module.app)


def test_catalog(client):
    actions = client.get("/api/actions/catalog").json()["actions"]
    assert [(a["type"], a["cost"], a["delay_s"]) for a in actions] == [
        ("restart_service", 3, 8), ("restart_all", 10, 25), ("recycle_pool", 1, 5), ("set_feature_flag", 1, 3),
        ("set_retry_policy", 1, 5), ("quarantine_head_message", 1, 2), ("purge_queue", 4, 3)]
    assert all(a["description"] and a["side_effects"] and "targets" in a and "params" in a for a in actions)


@pytest.mark.parametrize("body", [
    {"client_request_id": "c-1", "type": "restart_service", "target": "api", "params": {}, "extra": 1},
    {"client_request_id": "c-1", "type": "restart_service", "target": "evil.example.com"},
    {"client_request_id": "c-1", "type": "restart_service", "target": "10.0.0.1:22"},
    {"client_request_id": "c-1", "type": "restart_service", "target": "http://sim:9000/"},
    {"client_request_id": "c-1", "type": "restart_service", "target": "/etc/passwd"},
    {"client_request_id": "rm -rf /", "type": "restart_service", "target": "api"},
    {"client_request_id": "c-1", "type": "run_command", "target": "api"},
    {"client_request_id": "c-1", "type": "set_feature_flag", "target": "receipt_export", "params": {"enabled": "false"}},
    {"client_request_id": "c-1", "type": "set_feature_flag", "target": "receipt_export", "params": {"cmd": "ls"}},
    {"client_request_id": "c-1", "type": "set_retry_policy", "target": "api", "params": {"mode": "never"}},
    {"client_request_id": "c-1", "type": "set_retry_policy", "target": "ledger", "params": {"mode": "backoff"}},
    {"client_request_id": "c-1", "type": "set_retry_policy", "target": "api", "params": {"enabled": True}},
    {"client_request_id": "c-1", "type": "restart_all", "target": "api"},
    {"client_request_id": "c-1", "type": "recycle_pool", "target": "ledger", "params": {"mode": "backoff"}},
])
def test_anything_outside_the_enumerations_is_422(client, body):
    response = client.post("/api/rounds/r_any/actions", json=body)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "invalid_request")
