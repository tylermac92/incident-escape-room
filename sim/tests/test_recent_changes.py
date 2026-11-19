"""SCN-07: recent-changes entries with decoys."""

import re

import pytest

from harness import PACK, run_s, ticks, world
from sim.scenarios import SCENARIO_IDS

BANNED = ("pool", "leak", "retry", "poison", "queue", "connection", "storm", "flag")  # §9.7, SEC-06


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_three_or_four_entries_with_the_relevant_one_at_onset(scenario_id):
    decoys = {d["text"] for d in PACK.decoy_changes}
    counts = set()
    for seed in range(20):
        w, _ = world(scenario_id, seed)
        changes = w.recent_changes
        counts.add(len(changes))
        relevant = [c for c in changes if c["text"] == PACK.scenarios[scenario_id]["recent_change"]]
        assert relevant == [{"t_ms": w.injector.onset_ms, "text": relevant[0]["text"]}]
        assert {c["text"] for c in changes} - {relevant[0]["text"]} <= decoys
        assert changes == sorted(changes, key=lambda c: c["t_ms"])
    assert counts == {3, 4}
    assert world(scenario_id, 5)[0].recent_changes == world(scenario_id, 5)[0].recent_changes  # seeded


def test_ticks_show_only_changes_that_have_happened():
    w, events = world("poison_message", 2)
    run_s(w, 30)
    early = ticks(events)[-1]["recent_changes"]
    assert all(c["t_ms"] <= 30_000 for c in early)
    run_s(w, w.injector.onset_ms // 1000)
    assert ticks(events)[-1]["recent_changes"] == w.recent_changes


def test_wording_never_names_a_cause():
    texts = [d["text"] for d in PACK.decoy_changes] + [s["recent_change"] for s in PACK.scenarios.values()]
    for text in texts:
        assert not [w for w in BANNED if re.search(rf"\b{w}", text.lower())], text
