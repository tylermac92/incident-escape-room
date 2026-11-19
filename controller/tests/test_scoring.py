"""CTL-15: the §11.4 worked examples from fixed inputs, outcome rules, and clamp boundaries."""

import asyncio

import pytest
from fakes import CONFIG
from test_actions import on_call, request
from test_declare import HEALS

from controller.scoring import score

W = CONFIG["score"]


def acts(*specs):
    return [{"type": kind, "status": "completed", "effect_class": cls} for kind, cls in specs]


def run(outcome="recovered", mode="standard", ttr_s=100, b=0, neutralized=True, remaining=12, actions=(), premature=0):
    return score(W, outcome=outcome, mode=mode, ttr_s=ttr_s, impact_b=b, neutralized=neutralized,
                 budget_remaining=remaining, budget_total=12, time_limit_s=720, actions=list(actions),
                 premature=premature)


# §11.4: (TTR, B, neutralized, budget left, actions) -> speed, impact, hold, budget, penalties, total.
WORKED = [
    ("pool_leak flag off + recycle", 106, 3562, True, 10,
     acts(("set_feature_flag", "partial_fix"), ("recycle_pool", "partial_fix")), (292, 229, 200, 167, 0, 888)),
    ("pool_leak restart ledger", 97, 3066, False, 9, acts(("restart_service", "mitigates")), (297, 239, 100, 150, 25, 760)),
    ("pool_leak restart_all", 85, 6260, False, 2, acts(("restart_all", "restores")), (300, 175, 100, 33, 150, 458)),
    ("poison quarantine", 106, 980, True, 11, acts(("quarantine_head_message", "fix")), (292, 280, 200, 183, 0, 956)),
    ("poison purge", 63, 4920, True, 8, acts(("purge_queue", "fix")), (300, 202, 200, 133, 0, 835)),
    ("poison restart_all", 85, 5850, True, 2, acts(("restart_all", "restores")), (300, 183, 200, 33, 150, 566)),
    ("storm backoff", 107, 3304, True, 11, acts(("set_retry_policy", "fix")), (292, 234, 200, 183, 0, 909)),
    ("storm restart api", 89, 3096, False, 9, acts(("restart_service", "mitigates")), (300, 238, 100, 150, 25, 763)),
    ("storm restart_all", 85, 6720, False, 2, acts(("restart_all", "restores")), (300, 166, 100, 33, 150, 449)),
]


@pytest.mark.parametrize("name,ttr,b,neutralized,remaining,actions,expected", WORKED, ids=[w[0] for w in WORKED])
def test_worked_examples(name, ttr, b, neutralized, remaining, actions, expected):
    s = run(ttr_s=ttr, b=b, neutralized=neutralized, remaining=remaining, actions=actions)
    assert (s["speed"], s["impact"], s["hold"], s["budget"], s["breadth_penalty"], s["total"]) == expected


def test_speed_clamps_at_the_grace_period_and_the_time_limit():
    assert run(ttr_s=0)["speed"] == run(ttr_s=90)["speed"] == 300
    assert run(ttr_s=720)["speed"] == 0
    assert run(ttr_s=405)["speed"] == 150


def test_impact_clamps_at_the_scale():
    assert run(b=0)["impact"] == 300 and run(b=15000)["impact"] == 0 and run(b=40000)["impact"] == 0


def test_outcome_rules():
    full = run(outcome="recovered", remaining=6)
    undeclared = run(outcome="recovered_undeclared", remaining=6)
    assert full["total"] - undeclared["total"] == 100 and undeclared["hold"] == 100
    lost = run(outcome="not_recovered", b=3000, actions=acts(("restart_service", "no_effect")), premature=1)
    assert (lost["speed"], lost["hold"], lost["budget"], lost["impact"]) == (0, 0, 0, 240)
    assert lost["total"] == 240 - 25 - 30 - 50


def test_penalties_and_the_floor():
    wasted = acts(*[("set_feature_flag", "no_effect")] * 3, ("purge_queue", "unhelpful"), ("restart_all", "restores"))
    s = run(outcome="not_recovered", b=15000, actions=wasted, premature=7)
    assert (s["noeffect_penalty"], s["breadth_penalty"], s["premature_penalty"], s["total"]) == (120, 150, 150, 0)


def test_rejected_and_refunded_actions_cost_nothing():
    actions = [{"type": "restart_all", "status": "refunded", "effect_class": "restores"},
               {"type": "restart_service", "status": "rejected", "effect_class": None}]
    assert run(actions=actions)["breadth_penalty"] == 0


def test_practice_mode_does_not_score_speed():
    s = run(mode="practice", outcome="recovered_undeclared", ttr_s=10, b=0, neutralized=True)
    assert s["speed"] is None and s["total"] == 700 - 100  # undeclared: no +100 for declaring


def test_total_is_computed_before_rounding():
    s = run(ttr_s=106, b=3562, remaining=10)  # 292.38 + 228.76 + 200 + 166.67 = 887.81
    assert s["total"] == 888 and sum(s[k] for k in ("speed", "impact", "hold", "budget")) == 888


def test_a_declared_round_is_scored_and_shown_only_in_the_debrief(tmp_path):
    async def main():
        game, rnd, link = await on_call(tmp_path, HEALS)
        await game.act(rnd.id, request(1, "recycle_pool", "ledger"))
        before = game.view(rnd)
        link.neutralized = True
        await link.tick(65)
        await game.declare(rnd.id)
        return before, game.view(rnd), rnd

    before, after, rnd = asyncio.run(main())
    assert "score" not in before and "held" not in before
    assert after["held"] is True and after["score"]["hold"] == 200 and after["score"]["noeffect_penalty"] == 30
    assert after["score"]["budget"] == round(200 * 11 / 12) and rnd.ttr_s == 6
