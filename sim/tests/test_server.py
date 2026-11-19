"""Phase 0 sim server: /healthz and /link follow the isolation result, and fail closed."""

import asyncio
import json
import urllib.error
import urllib.request

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from sim import server

PASS = {"status": "pass", "failed": []}
FAIL = {"status": "fail", "failed": ["route"]}


def get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


async def scenario(result, check):
    server.state["isolation"] = result
    async with server.server(port=0) as srv:
        port = srv.sockets[0].getsockname()[1]
        return await check(port)


def run(result, check):
    return asyncio.run(scenario(result, check))


def test_healthz_follows_isolation():
    async def check(port):
        return await asyncio.to_thread(get, port, "/healthz")

    assert run(PASS, check) == (200, json.dumps(PASS) + "\n")
    assert run(FAIL, check)[0] == 503


def test_unknown_path_is_404():
    async def check(port):
        return (await asyncio.to_thread(get, port, "/nope"))[0]

    assert run(PASS, check) == 404


def test_link_sends_heartbeats_when_healthy():
    async def check(port):
        async with connect(f"ws://127.0.0.1:{port}/link") as ws:
            return json.loads(await asyncio.wait_for(ws.recv(), 2))

    assert run(PASS, check) == {"type": "evt.heartbeat", "isolation": PASS}


def test_link_reports_a_failing_check_then_closes():
    async def check(port):
        async with connect(f"ws://127.0.0.1:{port}/link") as ws:
            await asyncio.wait_for(ws.recv(), 2)
            server.state["isolation"] = FAIL  # what the 60 s recheck would do
            last = json.loads(await asyncio.wait_for(ws.recv(), 3))
            with pytest.raises(ConnectionClosed) as closed:
                await asyncio.wait_for(ws.recv(), 3)
            return last, closed.value.rcvd.code

    assert run(PASS, check) == ({"type": "evt.heartbeat", "isolation": FAIL}, 1011)


def test_link_reports_failure_at_connect_then_closes():
    async def check(port):
        async with connect(f"ws://127.0.0.1:{port}/link") as ws:
            first = json.loads(await asyncio.wait_for(ws.recv(), 2))
            with pytest.raises(ConnectionClosed) as closed:
                await asyncio.wait_for(ws.recv(), 2)
            return first, closed.value.rcvd.code

    assert run(FAIL, check) == ({"type": "evt.heartbeat", "isolation": FAIL}, 1011)


def test_link_carries_commands_and_events():
    async def check(port):
        async with connect(f"ws://127.0.0.1:{port}/link") as ws:
            await ws.send(json.dumps({"type": "cmd.start_round", "scenario_id": "poison_message", "seed": 3}))
            await ws.send(json.dumps({"type": "cmd.step", "n": 10}))
            await ws.send(json.dumps({"type": "cmd.resume"}))
            await ws.send(json.dumps({"type": "cmd.pause"}))
            await ws.send(json.dumps({"type": "cmd.step", "n": 10}))  # not allowed after pre-roll
            got = []
            while len(got) < 2:
                event = json.loads(await asyncio.wait_for(ws.recv(), 2))
                if event["type"] != "evt.heartbeat":
                    got.append(event)
            return [(e["type"], e.get("sim_time_ms"), e.get("code")) for e in got]

    assert run(PASS, check) == [("evt.tick", 1000, None), ("evt.error", None, "not_allowed")]
