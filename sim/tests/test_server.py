"""Phase 0 sim server: /healthz and /link follow the isolation result, and fail closed."""

import asyncio
import json
import urllib.error
import urllib.request

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

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

    assert run(PASS, check) == {"type": "evt.heartbeat"}


def test_link_refused_when_isolation_fails():
    async def check(port):
        with pytest.raises(InvalidStatus) as err:
            async with connect(f"ws://127.0.0.1:{port}/link"):
                pass
        return err.value.response.status_code

    assert run(FAIL, check) == 503

