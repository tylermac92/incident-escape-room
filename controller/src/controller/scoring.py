"""The score (CTL-15, TDD §11.2, §11.3). Weights and thresholds come from the pack (`controller.score`).

Score = clamp(S_speed + S_impact + S_hold + S_budget - P_breadth - P_noeffect - P_premature, 0, 1000),
computed before rounding. Aborted rounds are not scored.
"""

RECOVERED = ("recovered", "recovered_undeclared")
NO_EFFECT = ("no_effect", "unhelpful")  # the classes P_noeffect charges for (§10.2)


def clamp(x: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, x))


def score(w: dict, *, outcome: str, mode: str, ttr_s: float | None, impact_b: float, neutralized: bool,
          budget_remaining: int, budget_total: int, time_limit_s: int, actions: list[dict], premature: int) -> dict:
    recovered = outcome in RECOVERED
    if mode == "practice":
        speed = None  # D-02: no timer, so speed is "not scored"; the maximum is 700
    elif recovered:
        grace = w["speed_grace_s"]
        speed = w["speed_max"] * clamp(1 - (ttr_s - grace) / (time_limit_s - grace))
    else:
        speed = 0.0
    impact = w["impact_max"] * clamp(1 - impact_b / w["impact_scale"])
    hold = (w["hold_declared"] * (outcome == "recovered") + w["hold_neutralized"] * neutralized) if recovered else 0
    budget = w["budget_max"] * budget_remaining / budget_total if recovered else 0
    charged = [a for a in actions if a["status"] in ("pending", "completed")]  # not rejected, not refunded
    breadth = sum({"restart_all": w["breadth_restart_all"], "restart_service": w["breadth_restart_service"]}
                  .get(a["type"], 0) for a in charged)
    noeffect = w["noeffect"] * sum(a["effect_class"] in NO_EFFECT for a in charged)
    premature_penalty = w["premature"] * min(premature, w["premature_max_count"])
    total = clamp((speed or 0) + impact + hold + budget - breadth - noeffect - premature_penalty, 0, 1000)
    parts = {"speed": speed, "impact": impact, "hold": hold, "budget": budget, "breadth_penalty": breadth,
             "noeffect_penalty": noeffect, "premature_penalty": premature_penalty}
    return {k: None if v is None else round(v) for k, v in parts.items()} | {"total": round(total)}
