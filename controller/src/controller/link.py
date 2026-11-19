"""Controller -> sim link: the controller's only outbound connection (CTL-02, TDD §3.2, §12.2).

One WebSocket to the constant address ws://sim:9000/link, opened only after `sim` resolves inside
a directly connected subnet. Heartbeats carry sim's isolation result and the pack's controller
tuning (D-25). Ticks and errors go to `events` for the round; `evt.action_applied` resolves the
future `action()` returned. If heartbeats stop for more than 3 s the link closes itself, and every
close puts a `link.down` event on the queue, because sim's round died with the connection.
"""

import asyncio
import ipaddress
import json
import socket
import time
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

SIM_HOST = "sim"  # a constant; never configurable (SR-7, TDD §5.3)
SIM_PORT = 9000
HEARTBEAT_TIMEOUT_S = 3
RTF_GATEWAY = 0x0002


def internal_networks(route_text: str) -> list[ipaddress.IPv4Network]:
    """Directly connected subnets from /proc/net/route (no default, no gateway routes)."""
    nets = []
    for row in (line.split() for line in route_text.splitlines()[1:]):
        if not row or int(row[3], 16) & RTF_GATEWAY:
            continue
        dest, mask = (ipaddress.IPv4Address(bytes.fromhex(h)[::-1]) for h in (row[1], row[7]))
        if int(mask):
            nets.append(ipaddress.IPv4Network(f"{dest}/{mask}"))
    return nets


def is_internal(ip: str, route_text: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return any(addr in net for net in internal_networks(route_text))


class LinkDown(Exception):
    """The command could not be sent: the link to sim is down."""


class Link:
    def __init__(self) -> None:
        self.last_heartbeat: float | None = None
        self.address_ok = True  # set False for good if sim ever resolves outside the subnet
        self.sim_isolation: dict | None = None  # sim's own self-check, from its latest heartbeat
        self.config: dict | None = None  # the scenario pack's `controller` section (D-25)
        self.pack_version: str | None = None
        self.events: asyncio.Queue = asyncio.Queue()  # evt.tick, evt.error, link.down
        self._ws = None
        self._actions: dict[str, asyncio.Future] = {}

    def up(self) -> bool:
        return self.last_heartbeat is not None and time.monotonic() - self.last_heartbeat <= HEARTBEAT_TIMEOUT_S

    async def send(self, cmd: dict) -> None:
        if self._ws is None or not self.up():
            raise LinkDown
        try:
            await self._ws.send(json.dumps(cmd))
        except ConnectionClosed:
            raise LinkDown from None

    async def action(self, action: dict) -> asyncio.Future:
        """Send cmd.action. The future resolves with the sim time of its evt.action_applied, or is
        cancelled if the link goes down first."""
        future = asyncio.get_running_loop().create_future()
        self._actions[action["action_id"]] = future
        try:
            await self.send({"type": "cmd.action", "action": action})
        except LinkDown:
            del self._actions[action["action_id"]]
            raise
        return future

    def drain(self) -> None:
        """Drop queued round events, e.g. a stopped round's last ticks."""
        while not self.events.empty():
            self.events.get_nowait()

    def record(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "evt.heartbeat":
            self.last_heartbeat = time.monotonic()
            result = event.get("isolation")
            ok = isinstance(result, dict) and isinstance(result.get("failed"), list)
            self.sim_isolation = result if ok else {"status": "fail", "failed": ["malformed"]}
            if isinstance(event.get("controller"), dict):
                self.config, self.pack_version = event["controller"], event.get("pack_version")
        elif kind == "evt.action_applied":
            future = self._actions.pop(event.get("action_id"), None)
            if future is not None and not future.done():
                future.set_result(event.get("sim_time_ms"))
        elif kind in ("evt.tick", "evt.error"):
            self.events.put_nowait(event)

    async def _watchdog(self, ws, since: float) -> None:
        while True:
            await asyncio.sleep(0.5)
            if time.monotonic() - max(self.last_heartbeat or since, since) > HEARTBEAT_TIMEOUT_S:
                await ws.close(1011, "heartbeat missing")
                return

    async def serve(self, url: str) -> None:
        """One connection, until it closes. Raises if it cannot connect."""
        async with connect(url, open_timeout=5) as ws:
            self._ws = ws
            watchdog = asyncio.create_task(self._watchdog(ws, time.monotonic()))
            try:
                async for message in ws:
                    self.record(json.loads(message))
            except ConnectionClosed:
                pass
            finally:
                watchdog.cancel()
                self._ws, self.last_heartbeat = None, None
                for future in self._actions.values():
                    future.cancel()
                self._actions.clear()
                self.events.put_nowait({"type": "link.down"})

    async def run(self) -> None:
        backoff = 1
        while True:
            try:
                infos = await asyncio.get_running_loop().getaddrinfo(
                    SIM_HOST, SIM_PORT, family=socket.AF_INET, type=socket.SOCK_STREAM)
                ip = infos[0][4][0]
                if not is_internal(ip, Path("/proc/net/route").read_text()):
                    self.address_ok = False
                    return  # fail closed: never connect to a non-internal address
                # Connect to the verified address, so the name is not resolved twice.
                await self.serve(f"ws://{ip}:{SIM_PORT}/link")
                backoff = 1
            except (OSError, TimeoutError, ValueError, WebSocketException):
                pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)
