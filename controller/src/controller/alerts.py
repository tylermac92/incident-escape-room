"""Alert rules and page selection (TDD §9.6; the part of CTL-09 the pre-roll needs).

Each rule must hold on `for_s` consecutive one-second evaluations to fire. The first rule to fire
after onset is the page and defines T0. Rules that fire in the same second page in table order
(D-22). A firing alert clears on the first evaluation where its condition fails.
"""

RULES = (  # (rule id, threshold key in the pack's controller.alerts, value from tick["services"])
    ("api_error_rate_high", "api_error_rate_pct", lambda s: s["api"]["error_rate_pct"] or 0),
    ("api_latency_high", "api_latency_p95_ms", lambda s: s["api"]["latency_p95_ms"] or 0),
    ("orders_backlog_high", "orders_backlog", lambda s: s["worker"]["queue_depth"]["jobs"]),
)


class Alerts:
    def __init__(self, config: dict):
        self.config = config
        self.runs = {rule: 0 for rule, _, _ in RULES}
        self.alerts: dict[str, dict] = {}  # rule id -> Alert (§12.1)
        self.page: str | None = None

    def evaluate(self, services: dict, t_ms: int, armed: bool) -> str | None:
        """One evaluation. `armed` once the fault is active. Returns the page's rule id in the second it fires."""
        paged = None
        for rule, key, value in RULES:
            on = value(services) >= self.config[key]
            self.runs[rule] = self.runs[rule] + 1 if on else 0
            alert = self.alerts.get(rule)
            if alert and alert["state"] == "FIRING":
                if not on:
                    alert.update(state="CLEARED", cleared_at_ms=t_ms)
            elif armed and self.runs[rule] >= self.config["for_s"]:
                if self.page is None:
                    self.page = paged = rule
                self.alerts[rule] = {"rule_id": rule, "state": "FIRING", "fired_at_ms": t_ms,
                                     "cleared_at_ms": None, "is_page": rule == self.page}
        return paged
