"""CTL-05 against the real sim over a real WebSocket (TDD §15.3), with sim's own venv.

Skipped when sim's venv is missing (run `uv sync` in sim/ first). Also reports the wall-clock
pre-roll time that QA-17 will measure.
"""

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from controller.game import Game
from controller.link import Link

SIM = Path(__file__).parents[2] / "sim"
PYTHON = SIM / ".venv" / "bin" / "python"
SERVE = """
import asyncio, sys
from pathlib import Path
from sim import server
server.state["pack"] = server.load_pack(Path(sys.argv[1]))
server.state["isolation"] = {"status": "pass", "failed": []}  # no containers here: the check is not the subject
async def main():
    async with server.server(int(sys.argv[2])):
        await asyncio.Future()
asyncio.run(main())
"""
PAGES = {"pool_leak": {"api_latency_high", "api_error_rate_high"}, "poison_message": {"orders_backlog_high"},
         "retry_storm": {"api_error_rate_high", "api_latency_high"}}  # the pack's signature.page lists (D-22)

pytestmark = pytest.mark.skipif(not PYTHON.exists(), reason="sim/.venv not set up")


@pytest.fixture(scope="module")
def sim_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([PYTHON, "-c", SERVE, SIM / "scenarios", str(port)], stderr=sys.stderr)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), 0.1).close()
                break
            except OSError:
                time.sleep(0.1)
        yield port
    finally:
        proc.terminate()
        proc.wait(5)


@pytest.mark.parametrize("scenario_id", sorted(PAGES))
def test_preroll_reaches_the_page(sim_port, scenario_id, tmp_path):
    async def main():
        link = Link()
        serving = asyncio.create_task(link.serve(f"ws://127.0.0.1:{sim_port}/link"))
        while not (link.up() and link.config):
            await asyncio.sleep(0.01)
        game = Game(link, lambda: False, tmp_path / "session.json")
        await game.new_session("standard")
        game.session.round_order = [scenario_id] + [s for s in PAGES if s != scenario_id]
        started = time.monotonic()
        rnd = await game.prepare()
        while rnd.state == "PREPARING":
            await asyncio.sleep(0.01)
        elapsed = time.monotonic() - started
        view = game.view(rnd)
        serving.cancel()
        return rnd, view, elapsed

    rnd, view, elapsed = asyncio.run(main())
    print(f"{scenario_id}: pre-roll of {rnd.t0_ms // 1000} s took {elapsed:.1f} s")
    assert rnd.state == "BRIEFING" and rnd.t0_ms > rnd.t_onset_ms >= 600_000  # at least 600 s of baseline
    page = [a for a in view["alerts"] if a["is_page"]]
    assert len(page) == 1 and page[0]["rule_id"] in PAGES[scenario_id] and page[0]["fired_at_ms"] == rnd.t0_ms
    assert elapsed < 10  # "a few seconds" (QA-17 measures it properly)
