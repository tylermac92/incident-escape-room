"""SCN-03: the fault injector framework."""

import ast
import math
from pathlib import Path

import pytest

from harness import run_s, ticks, world
from sim import faults
from sim.faults import FAULTS, Fault

SRC = Path(faults.__file__)


class Probe(Fault):
    """A fault that records its onset and is neutralized once api backs off."""

    def onset(self, t, now_ms):
        self.at = now_ms
        t.set_hold_factor(2.0)

    def neutralized(self, t):
        return t.retry_policy("api") == "backoff"


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.setitem(FAULTS, "ledger_slowdown", Probe)


def test_onset_is_jittered_within_20_percent_and_seeded(probe):
    onsets = [world("retry_storm", seed)[0].injector.onset_ms for seed in range(40)]
    assert all(600_000 <= o <= 900_000 for o in onsets)  # onset_s 750 ± 20%
    assert max(onsets) - min(onsets) > 150_000 and onsets[0] == world("retry_storm", 0)[0].injector.onset_ms


def test_hidden_fields_follow_onset_and_the_holds_rule(probe):
    w, events = world("retry_storm", 3)
    onset_s = math.ceil(w.injector.onset_ms / 1000)
    run_s(w, onset_s + 2)
    before, after = ticks(events)[onset_s - 2]["hidden"]["fault"], ticks(events)[-1]["hidden"]["fault"]
    assert (before["active"], after["active"], after["neutralized"]) == (False, True, False)
    assert w.injector.fault.at == w.injector.onset_ms and w.ledger.hold_factor == 2.0
    w.api.policy = "backoff"
    run_s(w, 1)
    assert ticks(events)[-1]["hidden"]["fault"]["neutralized"] is True


def test_fault_scripts_get_no_way_out_of_the_simulation():
    imported = set()
    for node in ast.walk(ast.parse(SRC.read_text())):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported <= {"math", "sim.jobs"}  # no os, io, socket, subprocess, pathlib, ...
