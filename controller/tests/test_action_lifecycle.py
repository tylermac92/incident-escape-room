"""CTL-13: dispatch, completion, refunds, the hidden effect class, and the rejected-attempt log."""

import asyncio

from test_actions import on_call, request

from controller.actions import effect_class


def test_effect_class_lookup():
    matrix = {"restart_all": "restores", "set_feature_flag(receipt_export, off)": "partial_fix",
              "set_feature_flag(checkout_banner, *)": "no_effect", "set_retry_policy(api, backoff)": "fix",
              "set_retry_policy(*, aggressive)": "unhelpful", "recycle_pool(ledger)": "partial_fix"}
    assert effect_class(matrix, "restart_all", None, {}) == "restores"
    assert effect_class(matrix, "set_feature_flag", "receipt_export", {"enabled": False}) == "partial_fix"
    assert effect_class(matrix, "set_feature_flag", "checkout_banner", {"enabled": True}) == "no_effect"
    assert effect_class(matrix, "set_retry_policy", "worker", {"mode": "aggressive"}) == "unhelpful"
    assert effect_class(matrix, "set_retry_policy", "api", {"mode": "backoff"}) == "fix"
    assert effect_class(matrix, "recycle_pool", "ledger", {}) == "partial_fix"


def test_pending_then_completed_with_a_hidden_effect_class(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path)
        link.effect_matrices[rnd.scenario_id]["recycle_pool(ledger)"] = "fix"
        body = await game.act(rnd.id, request(1, "recycle_pool", "ledger"))
        await link.tick(4)
        assert game.view(rnd)["actions"][0]["status"] == "pending"
        await link.tick()
        return game, rnd, body

    game, rnd, body = asyncio.run(main())
    action = game.actions[0]
    assert "effect_class" not in body["action"] and "effect_class" not in str(game.view(rnd)["actions"])
    assert action["effect_class"] == "fix" and action["status"] == "completed"
    assert action["effective_at_ms"] == action["submitted_at_ms"] + 5000
    assert [(e["payload"]["status"], e["sim_time_ms"]) for e in game.events if e["kind"] == "action"] == [
        ("pending", action["submitted_at_ms"]), ("completed", action["effective_at_ms"])]
    rnd.state = "DEBRIEF"
    assert game.view(rnd)["actions"][0]["effect_class"] == "fix"  # revealed in the debrief


def test_link_lost_refunds_and_aborts(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path)
        await game.act(rnd.id, request(1, "restart_service", "api"))
        for future, _ in link.pending.values():  # what Link does when the connection closes
            future.cancel()
        link.events.put_nowait({"type": "link.down"})
        for _ in range(10):
            await asyncio.sleep(0)
        return game, rnd

    game, rnd = asyncio.run(main())
    assert (rnd.state, rnd.abort_reason, rnd.budget_remaining) == ("ABORTED", "sim_unavailable", 12)
    assert game.actions[0]["status"] == "refunded"


def test_restart_refunds_pending_costs_of_the_aborted_attempt(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path)
        await game.act(rnd.id, request(1, "restart_all"))
        await game.restart(rnd.id)
        return rnd

    rnd = asyncio.run(main())
    assert (rnd.state, rnd.budget_remaining) == ("ABORTED", 12)


def test_rejected_attempts_are_logged_with_their_reason(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path)
        for _ in range(2):  # the duplicate gets the stored answer and is not logged again
            try:
                await game.act(rnd.id, request(1, "set_retry_policy", "api", mode="backoff"))
            except Exception:
                pass
        return game

    game = asyncio.run(main())
    assert [(a["status"], a["reject_reason"], a["cost"]) for a in game.actions] == [("rejected", "no_change", None)]
