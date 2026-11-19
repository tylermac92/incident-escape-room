"""Alert rules and page selection (CTL-09, TDD §9.6).

Each rule must hold on `for_s` consecutive one-second evaluations to fire. The first rule to fire
after onset is the page and defines T0. Rules that fire in the same second page in table order
(D-22). A firing alert clears on the first evaluation where its condition fails. Alert text names the
symptom only, never a cause.
"""

RULES = (  # (rule id, threshold key in the pack's controller.alerts, value from tick["services"], text)
    ("api_error_rate_high", "api_error_rate_pct", lambda s: s["api"]["error_rate_pct"] or 0,
     "api error rate at or above {}% for {} s"),
    ("api_latency_high", "api_latency_p95_ms", lambda s: s["api"]["latency_p95_ms"] or 0,
     "api p95 latency at or above {} ms for {} s"),
    ("orders_backlog_high", "orders_backlog", lambda s: s["worker"]["queue_depth"]["jobs"],
     "jobs backlog at or above {} messages for {} s"),
)


class Alerts:
    def __init__(self, config: dict):
        self.config = config
        self.runs = {rule: 0 for rule, *_ in RULES}
        self.alerts: dict[str, dict] = {}  # rule id -> Alert (§12.1)
        self.page: str | None = None

    def evaluate(self, services: dict, t_ms: int, armed: bool) -> list[dict]:
        """One evaluation; `armed` once the fault is active. Returns the alerts that fired or cleared."""
        changed = []
        for rule, key, value, text in RULES:
            on = value(services) >= self.config[key]
            self.runs[rule] = self.runs[rule] + 1 if on else 0
            alert = self.alerts.get(rule)
            if alert and alert["state"] == "FIRING":
                if not on:
                    alert.update(state="CLEARED", cleared_at_ms=t_ms)
                    changed.append(alert)
            elif armed and self.runs[rule] >= self.config["for_s"]:
                self.page = self.page or rule
                self.alerts[rule] = {"rule_id": rule, "state": "FIRING", "fired_at_ms": t_ms, "cleared_at_ms": None,
                                     "is_page": rule == self.page,
                                     "text": text.format(self.config[key], self.config["for_s"])}
                changed.append(self.alerts[rule])
        return changed
