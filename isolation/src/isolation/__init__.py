"""Runtime isolation self-check (TDD §5.5, ENV-07), run inside sim and controller.

It proves isolation from routing and configuration state only and never contacts
any host outside the container. Each check is a pure function over the text it
reads, so the unit tests can feed it fixtures.
"""

import fnmatch
import os
import socket
from collections.abc import Callable, Mapping
from pathlib import Path

CREDENTIAL_ENV = ("AWS_*", "GOOGLE_*", "AZURE_*", "KUBECONFIG", "VAULT_*",
                  "*_TOKEN", "*_SECRET", "*_API_KEY", "*_PASSWORD")
CREDENTIAL_FILES = tuple(
    f"{home}/{p}" for home in ("~", "/root")
    for p in (".kube/config", ".aws", ".config/gcloud", ".azure", ".docker/config.json")
)
DOCKER_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock", "/run/containerd/containerd.sock",
                  "/run/podman/podman.sock", "/var/run/podman/podman.sock")
# Files Docker itself bind-mounts into every container.
RUNTIME_FILES = {"/etc/hostname", "/etc/hosts", "/etc/resolv.conf"}
# Filesystems the runtime creates fresh (mount root "/"), never a view of host storage.
FRESH_FS = {"overlay", "tmpfs", "proc", "sysfs", "devpts", "mqueue", "cgroup", "cgroup2"}
DNS_PROBE = "isolation-check.invalid"
RTF_REJECT = 0x0200


def has_default_route(route_text: str) -> bool:
    """IPv4 /proc/net/route: a default route has destination 00000000."""
    rows = [line.split() for line in route_text.splitlines()[1:]]
    return any(row[1] == "00000000" for row in rows if row)


def has_default_route_v6(route_text: str) -> bool:
    """/proc/net/ipv6_route: ::/0 counts unless it is the kernel's reject route."""
    for row in (line.split() for line in route_text.splitlines()):
        if row and row[0] == "0" * 32 and row[1] == "00" and not int(row[8], 16) & RTF_REJECT:
            return True
    return False


def is_privileged(status_text: str, uid: int) -> bool:
    cap_eff = next(line.split()[1] for line in status_text.splitlines() if line.startswith("CapEff:"))
    return int(cap_eff, 16) != 0 or uid == 0


def forbidden_mounts(mountinfo_text: str, dev: bool) -> list[str]:
    """Mount points that could expose host storage, outside the allowlist."""
    bad = []
    for line in mountinfo_text.splitlines():
        if not line.strip():
            continue
        left, right = line.split(" - ", 1)
        fields = left.split()
        root, point, options = fields[3], fields[4], fields[5].split(",")
        fstype = right.split()[0]
        allowed = (
            (root == "/" and fstype in FRESH_FS)
            or point.startswith(("/proc/", "/sys/"))  # runtime masks and cgroup views
            or point in RUNTIME_FILES
            or point == "/data"  # the escape_results volume
            or (dev and point.startswith("/app/") and "ro" in options)  # ENV-12 source mounts
        )
        if not allowed:
            bad.append(point)
    return bad


def docker_sockets_present(exists: Callable[[str], bool]) -> list[str]:
    return [p for p in DOCKER_SOCKETS if exists(p)]


def credentials_present(environ: Mapping[str, str], exists: Callable[[str], bool]) -> list[str]:
    names = [n for n in environ if any(fnmatch.fnmatchcase(n, pat) for pat in CREDENTIAL_ENV)]
    files = [p for p in CREDENTIAL_FILES if exists(os.path.expanduser(p))]
    return names + files


def dns_probe_resolves(resolve: Callable[[str], object]) -> bool:
    try:
        resolve(DNS_PROBE)
    except OSError:
        return False
    return True


def evaluate(
    route: str | None, route_v6: str | None, status: str | None, uid: int, mountinfo: str | None, dev: bool,
    environ: Mapping[str, str], exists: Callable[[str], bool], resolve: Callable[[str], object],
) -> dict:
    checks = {
        "route": lambda: has_default_route(route) or has_default_route_v6(route_v6),
        "privileges": lambda: is_privileged(status, uid),
        "mounts": lambda: forbidden_mounts(mountinfo, dev),
        "docker_socket": lambda: docker_sockets_present(exists),
        "credentials": lambda: credentials_present(environ, exists),
        "dns": lambda: dns_probe_resolves(resolve),
    }
    failed = [name for name, check in checks.items() if _fails(check)]
    return {"status": "fail" if failed else "pass", "failed": failed}


def _fails(check: Callable[[], object]) -> bool:
    """A check that cannot run (unreadable /proc file, unexpected format) fails closed."""
    try:
        return bool(check())
    except Exception:
        return True


def _read(path: str, missing: str | None = None) -> str | None:
    """File text, or `missing` if it can't be read; None makes the check using it fail."""
    try:
        return Path(path).read_text()
    except OSError:
        return missing


def run() -> dict:
    """Run every check against this process's real state."""
    return evaluate(
        route=_read("/proc/net/route"),
        route_v6=_read("/proc/net/ipv6_route", missing=""),  # absent when IPv6 is off
        status=_read("/proc/self/status"),
        uid=os.getuid(),
        mountinfo=_read("/proc/self/mountinfo"),
        dev=os.environ.get("ESCAPE_DEV") == "1",
        environ=os.environ,
        exists=os.path.exists,
        resolve=socket.gethostbyname,
    )

