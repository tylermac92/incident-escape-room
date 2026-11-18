"""Controller -> sim link: the controller's only outbound connection (Phase 0 slice of CTL-02).

Commands, events, and action correlation arrive with CTL-02. For now the link only
tracks heartbeats so readiness can report whether sim is reachable.
"""

import asyncio
import ipaddress
import json
import socket
import time
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

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


class Link:
    def __init__(self) -> None:
        self.last_heartbeat: float | None = None
        self.address_ok = True  # set False for good if sim ever resolves outside the subnet
        self.sim_isolation: dict | None = None  # sim's own self-check, from its latest heartbeat

    def up(self) -> bool:
        return self.last_heartbeat is not None and time.monotonic() - self.last_heartbeat <= HEARTBEAT_TIMEOUT_S

    def record(self, event: object) -> None:
        if not (isinstance(event, dict) and event.get("type") == "evt.heartbeat"):
            return
        self.last_heartbeat = time.monotonic()
        result = event.get("isolation")
        ok = isinstance(result, dict) and isinstance(result.get("failed"), list)
        self.sim_isolation = result if ok else {"status": "fail", "failed": ["malformed"]}

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
                async with connect(f"ws://{ip}:{SIM_PORT}/link", open_timeout=5) as ws:
                    backoff = 1
                    async for message in ws:
                        self.record(json.loads(message))
            except (OSError, TimeoutError, ValueError, WebSocketException):
                pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)
