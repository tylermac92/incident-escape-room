"""ENV-07: each runtime isolation check, with pass and fail fixtures."""

import isolation as iso

ROUTE_HEADER = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
ROUTE_INTERNAL = ROUTE_HEADER + "eth0\t000012AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n"
ROUTE_DEFAULT = ROUTE_INTERNAL + "eth0\t00000000\t010012AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"

V6_REJECT = "00000000000000000000000000000000 00 00000000000000000000000000000000 00 00000000000000000000000000000000 ffffffff 00000001 00000000 00200200       lo\n"
V6_DEFAULT = "00000000000000000000000000000000 00 00000000000000000000000000000000 00 fe800000000000000000000000000001 00000400 00000001 00000000 00000003     eth0\n"

STATUS_OK = "Name:\tpython\nCapPrm:\t0000000000000000\nCapEff:\t0000000000000000\n"
STATUS_CAPS = "Name:\tpython\nCapEff:\t00000000a80425fb\n"

# Trimmed from a real compose container (controller, with the /data volume).
MOUNTS_OK = """\
93 63 0:40 / / ro,relatime - overlay overlay rw,lowerdir=/x
95 93 0:48 / /proc rw,nosuid - proc proc rw
96 93 0:49 / /dev rw,nosuid - tmpfs tmpfs rw,size=65536k
110 96 0:53 / /dev/shm rw,nosuid - tmpfs shm rw
100 99 0:29 /docker/abc /sys/fs/cgroup/cpu ro,nosuid - cgroup cgroup rw,cpu
111 93 254:0 /var/lib/docker/volumes/incident-escape-room_escape_results/_data /data rw,relatime master:1 - ext4 /dev/vda rw
112 93 0:54 / /tmp rw,nosuid - tmpfs tmpfs rw,size=16384k
113 93 254:0 /var/lib/docker/containers/abc/hostname /etc/hostname ro,relatime - ext4 /dev/vda rw
114 93 254:0 /var/lib/docker/containers/abc/hosts /etc/hosts ro,relatime - ext4 /dev/vda rw
115 93 254:0 /var/lib/docker/containers/abc/resolv.conf /etc/resolv.conf ro,relatime - ext4 /dev/vda rw
69 95 0:49 /null /proc/interrupts rw,nosuid - tmpfs tmpfs rw
"""
HOST_BIND = "120 93 254:0 /home/me/project /src rw,relatime - ext4 /dev/vda rw\n"
SOCKET_BIND = "121 93 0:25 /docker.sock /x.sock rw,nosuid - tmpfs tmpfs rw\n"
DEV_RO = "122 93 254:0 /home/me/project/sim /app/src ro,relatime - ext4 /dev/vda rw\n"
DEV_RW = "122 93 254:0 /home/me/project/sim /app/src rw,relatime - ext4 /dev/vda rw\n"


def never(_path):
    return False


def nxdomain(_name):
    raise OSError("Name or service not known")


def test_routes():
    assert not iso.has_default_route(ROUTE_INTERNAL)
    assert iso.has_default_route(ROUTE_DEFAULT)
    assert not iso.has_default_route_v6("")
    assert not iso.has_default_route_v6(V6_REJECT)
    assert iso.has_default_route_v6(V6_DEFAULT)


def test_privileges():
    assert not iso.is_privileged(STATUS_OK, uid=10001)
    assert iso.is_privileged(STATUS_OK, uid=0)
    assert iso.is_privileged(STATUS_CAPS, uid=10001)


def test_mounts():
    assert iso.forbidden_mounts(MOUNTS_OK, dev=False) == []
    assert iso.forbidden_mounts(MOUNTS_OK + HOST_BIND, dev=False) == ["/src"]
    assert iso.forbidden_mounts(MOUNTS_OK + SOCKET_BIND, dev=False) == ["/x.sock"]
    assert iso.forbidden_mounts(MOUNTS_OK + DEV_RO, dev=False) == ["/app/src"]
    assert iso.forbidden_mounts(MOUNTS_OK + DEV_RO, dev=True) == []
    assert iso.forbidden_mounts(MOUNTS_OK + DEV_RW, dev=True) == ["/app/src"]


def test_docker_socket():
    assert iso.docker_sockets_present(never) == []
    assert iso.docker_sockets_present(lambda p: p == "/run/docker.sock") == ["/run/docker.sock"]


def test_credentials():
    assert iso.credentials_present({"PATH": "/bin", "TZ": "UTC", "ESCAPE_PORT": "8080"}, never) == []
    for name in ("AWS_ACCESS_KEY_ID", "GOOGLE_APPLICATION_CREDENTIALS", "AZURE_CLIENT_ID",
                 "KUBECONFIG", "VAULT_ADDR", "GITHUB_TOKEN", "APP_SECRET", "OPENAI_API_KEY", "DB_PASSWORD"):
        assert iso.credentials_present({name: "x"}, never) == [name]
    assert iso.credentials_present({}, lambda p: p.endswith("/.aws")) != []


def test_dns():
    assert not iso.dns_probe_resolves(nxdomain)
    assert iso.dns_probe_resolves(lambda _name: [("addr",)])


def clean(**overrides):
    args = dict(route=ROUTE_INTERNAL, route_v6="", status=STATUS_OK, uid=10001, mountinfo=MOUNTS_OK,
                dev=False, environ={"PATH": "/bin"}, exists=never, resolve=nxdomain)
    return iso.evaluate(**{**args, **overrides})


def test_evaluate_reports_each_failed_check():
    assert clean() == {"status": "pass", "failed": []}
    assert clean(route=ROUTE_DEFAULT)["failed"] == ["route"]
    assert clean(uid=0)["failed"] == ["privileges"]
    assert clean(mountinfo=MOUNTS_OK + HOST_BIND)["failed"] == ["mounts"]
    assert clean(exists=lambda p: p == "/var/run/docker.sock")["failed"] == ["docker_socket"]
    assert clean(environ={"AWS_SECRET_ACCESS_KEY": "x"})["failed"] == ["credentials"]
    assert clean(resolve=lambda _n: [])["failed"] == ["dns"]
    assert clean(uid=0, resolve=lambda _n: [])["status"] == "fail"


def test_a_check_that_cannot_run_fails_closed():
    assert clean(route=None)["failed"] == ["route"]  # /proc/net/route unreadable
    assert clean(route_v6=None)["failed"] == ["route"]
    assert clean(status="Name:\tpython\n")["failed"] == ["privileges"]  # no CapEff line
    assert clean(mountinfo="garbage")["failed"] == ["mounts"]
    assert clean(mountinfo=None)["failed"] == ["mounts"]
    assert clean(resolve=lambda _n: 1 / 0)["failed"] == ["dns"]
    assert iso._read("/nonexistent/route") is None
    assert iso._read("/nonexistent/route", missing="") == ""


def test_run_against_this_machine_returns_a_result():
    result = iso.run()
    assert result["status"] in {"pass", "fail"} and isinstance(result["failed"], list)
