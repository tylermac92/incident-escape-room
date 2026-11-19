"""CTL-09: alert rules, page selection, FIRING and CLEARED, and symptom-only text."""

from fakes import CONFIG, services

from controller.alerts import Alerts

CAUSE_WORDS = ("leak", "retry", "poison", "storm", "pool", "crash", "ledger", "export", "maintenance")


def run(alerts, series, armed=True, start_s=1):
    changed = []
    for i, svc in enumerate(series):
        changed += [dict(a) for a in alerts.evaluate(svc, (start_s + i) * 1000, armed)]
    return changed


def test_fires_on_the_30th_consecutive_second_and_clears_on_the_first_good_one():
    alerts = Alerts(CONFIG["alerts"])
    changed = run(alerts, [services(error_pct=5)] * 29 + [services()] + [services(error_pct=6)] * 30 + [services()])
    assert [(a["state"], a["fired_at_ms"], a["cleared_at_ms"]) for a in changed] == [
        ("FIRING", 60_000, None), ("CLEARED", 60_000, 61_000)]  # the 29-second run never fired


def test_later_rules_are_secondary_and_the_page_survives_a_refire():
    alerts = Alerts(CONFIG["alerts"])
    run(alerts, [services(jobs=500)] * 30)  # orders_backlog_high pages
    run(alerts, [services(jobs=500, p95=1000)] * 30, start_s=31)
    run(alerts, [services()] + [services(jobs=600)] * 30, start_s=61)  # page clears, then fires again
    assert {r: a["is_page"] for r, a in alerts.alerts.items()} == {"orders_backlog_high": True,
                                                                    "api_latency_high": False}
    assert alerts.page == "orders_backlog_high" and alerts.alerts["orders_backlog_high"]["state"] == "FIRING"


def test_nothing_fires_before_onset():
    alerts = Alerts(CONFIG["alerts"])
    assert run(alerts, [services(error_pct=50)] * 60, armed=False) == [] and alerts.page is None


def test_text_names_the_symptom_only():
    alerts = Alerts(CONFIG["alerts"])
    run(alerts, [services(error_pct=50, p95=5000, jobs=900)] * 30)
    texts = [a["text"] for a in alerts.alerts.values()]
    assert texts == ["api error rate at or above 5% for 30 s", "api p95 latency at or above 1000 ms for 30 s",
                     "jobs backlog at or above 500 messages for 30 s"]
    assert not any(word in text for text in texts for word in CAUSE_WORDS)
