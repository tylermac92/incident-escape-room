"""sim's only network endpoint, on port 9000 (SIM-10): /healthz and the controller link.

Phase 0 scope: the link only sends heartbeats, each carrying the isolation result, so the
controller can lock on a sim failure. Engine commands and ticks arrive with SIM-10.
sim never opens outbound connections; this module only serves.
"""

import asyncio
import http
import json

import isolation
from websockets.asyncio.server import ServerConnection, serve

PORT = 9000
CHECK_INTERVAL_S = 60
HEARTBEAT_INTERVAL_S = 1

# Fail closed until the startup check has run.
state = {"isolation": {"status": "fail", "failed": ["not_run"]}}


def healthy() -> bool:
    return state["isolation"]["status"] == "pass"


def process_request(connection: ServerConnection, request):
    if request.path == "/healthz":
        status = http.HTTPStatus.OK if healthy() else http.HTTPStatus.SERVICE_UNAVAILABLE
        return connection.respond(status, json.dumps(state["isolation"]) + "\n")
    if request.path != "/link":
        return connection.respond(http.HTTPStatus.NOT_FOUND, "not found\n")
    return None  # continue the WebSocket handshake; link() reports a failing check and closes


async def link(ws: ServerConnection) -> None:
    # Each heartbeat carries the isolation result; a failing one is sent once, then the link closes.
    while True:
        await ws.send(json.dumps({"type": "evt.heartbeat", "isolation": state["isolation"]}))
        if not healthy():
            break
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)
    await ws.close(1011, "isolation check failed")


def server(port: int = PORT):
    return serve(link, "0.0.0.0", port, process_request=process_request)


async def main() -> None:
    state["isolation"] = isolation.run()
    print(f"sim: isolation {state['isolation']}", flush=True)
    async with server():
        while True:
            await asyncio.sleep(CHECK_INTERVAL_S)
            state["isolation"] = await asyncio.to_thread(isolation.run)
            if not healthy():
                print(f"sim: isolation {state['isolation']}", flush=True)
