"""Headless scenario harness (TDD §15.1): drive a World directly, no socket, no containers."""

from pathlib import Path

from sim.scenarios import load_pack
from sim.world import STEPS_PER_TICK, World

PACK = load_pack(Path(__file__).parents[1] / "scenarios")


def world(scenario_id="pool_leak", seed=1, pack=PACK):
    events = []
    return World(scenario_id, seed, events.append, pack), events


def run_s(w, seconds):
    for _ in range(seconds * STEPS_PER_TICK):
        w.engine.step()


def ticks(events):
    return [e for e in events if e["type"] == "evt.tick"]
