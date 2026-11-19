"""CTL-11: the customer-impact feed and its safeguards."""

import hashlib
import json
import random
import re

import pytest
from fakes import CONTENT

from controller.feed import CATEGORIES, Feed, feed_rng, load_content

CONFIG = {"interval_s": 5, "min_count": 5}
BANNED = ("pool", "leak", "retry", "poison", "queue", "connection", "storm", "flag")  # SEC-06


def run(series, seed=1, onset_s=None, t0_s=None, checks=lambda t: True):
    """series[i] is second i+1's counts."""
    feed = Feed(seed, CONTENT, CONFIG)
    for i, counts in enumerate(series):
        t = (i + 1) * 1000
        feed.add(t, counts, checks(t), onset_s is None or t <= onset_s * 1000, t0_s and t0_s * 1000)
    return feed.items


def noisy(seconds, seed=3):
    rng = random.Random(seed)
    return [{c: rng.choice([0, 0, 0, rng.randint(1, 12)]) for c in CATEGORIES} for _ in range(seconds)]


def test_rng_is_seeded_per_d18():
    expected = int.from_bytes(hashlib.sha256(b"42:feed").digest()[:8], "big")
    assert feed_rng(42).random() == random.Random(expected).random()


def test_same_seed_and_series_give_the_same_feed():
    series = noisy(600)
    assert run(series, seed=9) == run(series, seed=9)
    assert run(series, seed=9) != run(series, seed=10)


def test_evidence_matches_the_window_and_meets_the_minimum():
    series = noisy(600)
    items = [i for i in run(series) if i["evidence"]]
    assert items
    for item in items:
        ev = item["evidence"]
        assert ev["count"] >= 5 and ev["category"] == item["category"]
        start, end = ev["window_start_ms"] // 1000, ev["window_end_ms"] // 1000  # seconds (start, end]
        assert end - start == 10 and ev["count"] == sum(s[ev["category"]] for s in series[start:end])


def test_at_most_one_item_per_interval():
    items = run([{"read_failed": 100}] * 300)
    assert len(items) == 60 and all(i["t_ms"] % 5000 == 0 for i in items)  # count >= 50: every slot emits


def test_quiet_means_no_complaints():
    items = run([{}] * 600)
    assert items and all(i["kind"] == "chatter" and i["evidence"] is None for i in items)


def test_chatter_only_in_the_baseline_and_at_most_once_a_minute():
    items = run([{}] * 1200, onset_s=600)
    times = [i["t_ms"] for i in items]
    assert times and max(times) <= 600_000 and all(b - a >= 60_000 for a, b in zip(times, times[1:]))


def test_escalates_after_three_minutes_of_one_bad_spell():
    items = run([{"order_delayed": 60}] * 300)
    assert {i["kind"] for i in items if i["t_ms"] <= 180_000} == {"complaint"}
    assert {i["kind"] for i in items if i["t_ms"] > 181_000} == {"escalation"}


def test_a_ten_second_gap_starts_a_new_spell():
    series = [{"order_delayed": 60}] * 170 + [{}] * 10 + [{"order_delayed": 60}] * 100
    assert {i["kind"] for i in run(series)} == {"complaint"}


def test_texts_come_from_the_fixed_category_templates():
    def pattern(text):
        return re.compile(re.escape(text).replace(r"\{brand\}", ".+").replace(r"\{product\}", ".+") + "$")

    for item in run(noisy(900)):
        if item["category"]:
            templates = CONTENT["templates"][item["kind"]][item["category"]]
            assert any(pattern(t).match(item["text"]) for t in templates), item


def test_recovery_needs_30_quiet_seconds_and_passing_checks_and_comes_once():
    bad, quiet = [{"read_failed": 60}] * 60, [{}] * 120
    items = run(bad + quiet, checks=lambda t: t >= 130_000)
    recoveries = [i for i in items if i["kind"] == "recovery"]
    assert [i["t_ms"] for i in recoveries] == [130_000]  # quiet from 61 s, checks pass from 130 s
    assert not [i for i in run(bad + quiet, checks=lambda t: False) if i["kind"] == "recovery"]
    assert not [i for i in run([{}] * 300) if i["kind"] == "recovery"]  # nothing to recover from


def test_items_up_to_t0_are_pre_alert():
    items = run([{"read_failed": 60}] * 120, t0_s=60)
    assert {i["pre_alert"] for i in items if i["t_ms"] <= 60_000} == {True}
    assert {i["pre_alert"] for i in items if i["t_ms"] > 60_000} == {False}


def test_items_carry_fictional_customers():
    item = run([{"read_failed": 60}] * 5)[0]
    assert item["customer"]["name"] in CONTENT["lists"]["names"]
    assert item["customer"]["city"] in CONTENT["lists"]["cities"]


def test_templates_name_no_cause():
    words = re.findall(r"[a-z]+", json.dumps(CONTENT["templates"]).lower())
    assert not [w for w in words if any(w.startswith(b) for b in BANNED)]


def test_every_category_needs_templates(tmp_path):
    templates = json.loads(json.dumps(CONTENT["templates"]))
    templates["escalation"]["order_lost"] = []
    (tmp_path / "templates.json").write_text(json.dumps(templates))
    (tmp_path / "lists.json").write_text(json.dumps(CONTENT["lists"]))
    with pytest.raises(ValueError, match="order_lost"):
        load_content(tmp_path)
