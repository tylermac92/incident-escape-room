"""CTL-02: the link's commands, events, action correlation, and heartbeat watchdog."""

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from controller import link as link_module
from controller.link import Link, LinkDown

PASS = {"status": "pass", "failed": []}
BEAT = {"type": "evt.heartbeat", "isolation": PASS, "pack_version": "1.0.0", "controller": {"budget": 12},
        "effect_matrices": {}}


def run(sim, check):
    """Serve `sim(ws)` on a free port, connect a Link to it, and return check(link)."""
    async def main():
        async with serve(sim, "127.0.0.1", 0) as server:
            link = Link()
            port = server.sockets[0].getsockname()[1]
            task = asyncio.create_task(link.serve(f"ws://127.0.0.1:{port}/link"))
            try:
                return await asyncio.wait_for(check(link), 5)
            finally:
                task.cancel()
    return asyncio.run(main())


async def first(link, kind):
    while (event := await link.events.get())["type"] != kind:
        pass
    return event


def test_commands_events_and_action_correlation():
    async def sim(ws):
        await ws.send(json.dumps(BEAT))
        async for raw in ws:
            cmd = json.loads(raw)
            if cmd["type"] == "cmd.step":
                await ws.send(json.dumps({"type": "evt.tick", "sim_time_ms": 1000}))
            elif cmd["type"] == "cmd.action":
                await ws.send(json.dumps({"type": "evt.action_applied", "action_id": "other", "sim_time_ms": 1}))
                await ws.send(json.dumps({"type": "evt.action_applied",
                                          "action_id": cmd["action"]["action_id"], "sim_time_ms": 6000}))

    async def check(link):
        while not link.up():
            await asyncio.sleep(0.01)
        await link.send({"type": "cmd.step", "n": 10})
        tick = await link.events.get()
        applied = await link.action({"action_id": "a_1", "type": "recycle_pool", "target": "ledger", "params": {}})
        return tick["sim_time_ms"], await applied, link.config, link.pack_version

    assert run(sim, check) == (1000, 6000, {"budget": 12}, "1.0.0")


def test_missing_heartbeat_closes_the_link(monkeypatch):
    monkeypatch.setattr(link_module, "HEARTBEAT_TIMEOUT_S", 0.6)

    async def sim(ws):
        await ws.send(json.dumps(BEAT))
        await ws.wait_closed()  # then silence: a hung sim

    async def check(link):
        while not link.up():
            await asyncio.sleep(0.01)
        pending = await link.action({"action_id": "a_1", "type": "recycle_pool", "target": "ledger", "params": {}})
        await first(link, "link.down")
        with pytest.raises(LinkDown):
            await link.send({"type": "cmd.step", "n": 10})
        return link.up(), pending.cancelled()

    assert run(sim, check) == (False, True)


def test_send_without_a_connection_raises():
    with pytest.raises(LinkDown):
        asyncio.run(Link().send({"type": "cmd.pause"}))
