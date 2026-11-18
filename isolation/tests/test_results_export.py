import io
import json

import pytest

from isolation import results_export
from isolation.results_export import summarize

# Shaped like a CTL-17 line; that ticket fixes the real schema.
ROUND = {"round_id": "r1", "scenario_id": "pool_leak", "seed": 42, "mode": "standard",
         "outcome": "recovered", "score": {"total": 812}, "actions": [{"type": "restart", "target": "sim/ledger"}],
         "events": [{"t_ms": 0, "kind": "alert", "feed": {"customer": "Ana P.", "city": "Brightwater"}}]}
FOLLOW = {"round_id": "r1", "debrief_closed_at": "2026-11-18T10:00:00Z"}


def lines(*records):
    return "\n".join(json.dumps(r) for r in records) + "\n"


def test_counts_rounds_and_lists_fields():
    second = dict(ROUND, round_id="r2", ttr_s=95)
    rounds, fields, problems = summarize(lines(ROUND, FOLLOW, second))
    assert (rounds, problems) == (2, [])  # the follow-up line is not a round
    assert fields == ["actions", "events", "mode", "outcome", "round_id", "scenario_id", "score", "seed", "ttr_s"]


@pytest.mark.parametrize("record, path", [
    (dict(ROUND, player_name="Tyler"), "player_name"),
    (dict(ROUND, player={"id": 1}), "player"),
    (dict(ROUND, score={"total": 1, "user": "x"}), "score.user"),
    (dict(ROUND, actions=[{"type": "restart", "ip_address": "10.0.0.2"}]), "actions[0].ip_address"),
    (dict(ROUND, hostname="laptop"), "hostname"),
    (dict(ROUND, **{"E-Mail": "a@b.c"}), "E-Mail"),
])
def test_identifying_fields_fail(record, path):
    _, _, problems = summarize(lines(record))
    assert problems == [f"line 1 has a player-identifying field: {path}"]


def test_ordinary_names_are_not_identifying():
    # Words that merely contain "user"/"ip" and fictional feed data are fine.
    record = dict(ROUND, pipeline="x", ship_eta=3, users_affected=10, recipe={"name": "checkout"})
    assert summarize(lines(record))[2] == []


@pytest.mark.parametrize("text, problem", [
    ("", "there are no completed rounds to export"),
    ("\n\n", "there are no completed rounds to export"),
    (lines(FOLLOW), "there are no completed rounds to export"),
    ("{not json\n", "line 1 is not valid JSON"),
    ("[1, 2]\n", "line 1 is not a JSON object"),
])
def test_empty_or_malformed_fails(text, problem):
    assert summarize(text)[2] == [problem]


def test_main(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(lines(ROUND)))
    assert results_export.main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "rounds: 1", "fields: actions, events, mode, outcome, round_id, scenario_id, score, seed",
        "player-identifying fields: none"]
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert results_export.main() == 1
