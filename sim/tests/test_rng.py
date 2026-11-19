import hashlib
import json
import pathlib
import random
import re
import subprocess
import sys

from sim.engine import Engine
from sim.rng import stream, streams

SRC = pathlib.Path(__file__).parents[1] / "src" / "sim"


def test_seeding_formula():
    expected = int.from_bytes(hashlib.sha256(b"42:traffic").digest()[:8])
    assert stream(42, "traffic").random() == random.Random(expected).random()


def test_same_across_processes():
    # Would fail if seeding used the per-process salted hash().
    code = "from sim.rng import stream; print(stream(7, 'fault').random())"
    runs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
            for _ in range(2)}
    assert runs == {f"{stream(7, 'fault').random()}\n"}


def test_draws_in_one_stream_leave_the_others_unchanged():
    quiet, busy = streams(9), streams(9)
    for _ in range(1000):
        busy["traffic"].random()
    assert [busy[n].random() for n in ("latency", "fault")] == [quiet[n].random() for n in ("latency", "fault")]


def run(seed, actions):
    """Byte stream of a toy model that draws from every substream and reacts to actions."""
    rng, out, state = streams(seed), [], {"load": 1.0}
    phases = {
        "traffic": lambda e: state.update(arrivals=rng["traffic"].expovariate(state["load"])),
        "api": lambda e: state.update(latency=rng["latency"].lognormvariate(0, 0.4)),
        "faults": lambda e: out.append(json.dumps(
            {"t": e.now_ms, "fault": rng["fault"].random(), **state}).encode()),
    }
    engine = Engine(phases, on_action=lambda e, a: state.update(load=a))
    for at_step, load in actions:
        while engine.steps < at_step:
            engine.step()
        engine.submit(load, delay_ms=500)
    for _ in range(100):
        engine.step()
    return b"\n".join(out)


def test_same_seed_and_actions_give_identical_bytes():
    actions = [(10, 2.0), (30, 0.5)]
    assert run(1, actions) == run(1, actions)
    assert run(1, actions) != run(2, actions)


def test_no_other_randomness_in_sim():
    pattern = re.compile(r"\b(import random|from random|secrets|urandom|uuid|SystemRandom|hash\()")
    offenders = [p.name for p in SRC.rglob("*.py") if p.name != "rng.py" and pattern.search(p.read_text())]
    assert offenders == []
