"""ENV-13 runtime detection, versions, and resources.

LINUX is trimmed from real `docker version`/`docker info` output (Docker Engine 29.10, Ubuntu).
COLIMA is trimmed from real output on an Apple Silicon Mac (Colima, Engine 28.4, arm64 VM
with 4 GiB). The other runtimes are built in the same shape from their known distinguishing
fields (not recorded here): Podman's "Podman Engine" component, Docker Desktop's OperatingSystem,
Colima's context name and socket path, and WSL2's kernel name.
"""

import copy
import io
import json

import pytest

from isolation import host_runtime
from isolation.host_runtime import detect, evaluate, version_tuple

LINUX = {
    "version": {
        "Client": {"Platform": {"Name": "Docker Engine - Community"}, "Version": "29.10.0", "Os": "linux", "Arch": "amd64", "Context": "default"},
        "Server": {"Platform": {"Name": "Docker Engine - Community"}, "Version": "29.10.0", "Os": "linux", "Arch": "amd64",
                   "Components": [{"Name": "Engine", "Version": "29.10.0"}, {"Name": "containerd", "Version": "v2.4.2"},
                                  {"Name": "runc", "Version": "1.5.3"}, {"Name": "docker-init", "Version": "0.19.0"}]},
    },
    "info": {"OperatingSystem": "Ubuntu 24.04.5 LTS", "KernelVersion": "6.18.44-fc-v595", "NCPU": 4, "MemTotal": 16869130240},
}
LOCAL = ("default", "unix:///var/run/docker.sock")
PLUGINS = ("5.7.1", "github.com/docker/buildx v0.39.0 360040a")


def variant(client_os="linux", components=("Engine",), os_name="Ubuntu 24.04.5 LTS", kernel="6.8.0", **server):
    state = copy.deepcopy(LINUX)
    state["version"]["Client"]["Os"] = client_os
    state["version"]["Server"]["Components"] = [{"Name": n, "Version": "1"} for n in components]
    state["version"]["Server"].update(server)
    state["info"].update(OperatingSystem=os_name, KernelVersion=kernel)
    return state


MAC = variant(client_os="darwin", Arch="arm64")
COLIMA = {
    "version": {
        "Client": {"Platform": {"Name": "Docker Engine - Community"}, "Version": "29.10.0", "Os": "darwin", "Arch": "arm64", "Context": "colima"},
        "Server": {"Platform": {"Name": "Docker Engine - Community"}, "Version": "28.4.0", "Os": "linux", "Arch": "arm64",
                   "Components": [{"Name": "Engine", "Version": "28.4.0"}, {"Name": "containerd", "Version": "1.7.27"},
                                  {"Name": "runc", "Version": "1.2.5"}, {"Name": "docker-init", "Version": "0.19.0"}]},
    },
    "info": {"OperatingSystem": "Ubuntu 24.04.2 LTS", "KernelVersion": "6.8.0-64-generic", "NCPU": 2, "MemTotal": 4095299584},
}
COLIMA_SOCKET = "unix:///Users/me/.colima/default/docker.sock"
COLIMA_PLUGINS = ("5.8.0", "github.com/docker/buildx v0.39.0")


def run(state, context=LOCAL[0], endpoint=LOCAL[1], compose=PLUGINS[0], buildx=PLUGINS[1]):
    return evaluate(state["version"], state["info"], context, endpoint, compose, buildx)


def test_version_parsing():
    assert version_tuple("29.10.0") == (29, 10)
    assert version_tuple("v2.29.1") == (2, 29)
    assert version_tuple("2.20.0-desktop.1") == (2, 20)
    assert version_tuple("28.0.0-rc.1") == (28, 0)
    assert version_tuple("") is None


@pytest.mark.parametrize("state, context, endpoint, expected", [
    (LINUX, *LOCAL, "linux-engine"),
    (COLIMA, "colima", COLIMA_SOCKET, "colima"),
    (MAC, "colima-work", "unix:///Users/me/.colima/work/docker.sock", "colima"),
    (COLIMA, "default", COLIMA_SOCKET, "colima"),  # DOCKER_HOST at the socket
    (variant(client_os="darwin", os_name="Docker Desktop"), "desktop-linux",
     "unix:///Users/me/.docker/run/docker.sock", "docker-desktop"),
    (variant(client_os="windows", os_name="Docker Desktop", kernel="5.15.153.1-microsoft-standard-WSL2"),
     "desktop-linux", "npipe:////./pipe/dockerDesktopLinuxEngine", "docker-desktop"),
    (variant(kernel="5.15.153.1-microsoft-standard-WSL2"), *LOCAL, "wsl2"),
    (variant(components=("Podman Engine", "Conmon", "OCI Runtime (crun)"), Version="5.2.0"), *LOCAL, "podman"),
    (MAC, "orbstack", "unix:///Users/me/.orbstack/run/docker.sock", "other"),
])
def test_detect(state, context, endpoint, expected):
    assert detect(state["version"], state["info"], context, endpoint) == expected


def test_supported_runtimes_pass_cleanly():
    line, warnings, failures = run(LINUX)
    assert line == "runtime: Linux Docker Engine, engine 29.10.0, amd64"
    assert (warnings, failures) == ([], [])
    # The recorded 4 GiB VM reports 3.8 GiB, which must not trigger the memory warning.
    line, warnings, failures = run(COLIMA, "colima", COLIMA_SOCKET, *COLIMA_PLUGINS)
    assert line == "runtime: Colima, engine 28.4.0, arm64" and (warnings, failures) == ([], [])


def test_podman_is_refused():
    _, _, failures = run(variant(components=("Podman Engine",), Version="5.2.0"))
    assert len(failures) == 1 and "Podman is not supported" in failures[0] and "docker context use" in failures[0]


@pytest.mark.parametrize("state", [variant(os_name="Docker Desktop"), variant(kernel="5.15-microsoft-standard-WSL2"),
                                   MAC])
def test_untested_runtimes_warn_but_continue(state):
    _, warnings, failures = run(state, "orbstack" if state is MAC else "default")
    assert failures == [] and any("untested runtime" in w for w in warnings)


def test_versions_and_plugins():
    assert "too old" in run(variant(Version="27.5.1"))[2][0]
    assert run(variant(Version="28.0.0"))[2] == []
    assert "too old" in run(LINUX, compose="2.19.1")[2][0]
    assert run(LINUX, compose="v2.20.0")[2] == []
    assert "Compose plugin is missing" in run(LINUX, compose="")[2][0]
    assert "buildx plugin is missing" in run(LINUX, buildx="")[2][0]
    colima = run(COLIMA, "colima", COLIMA_SOCKET, compose="", buildx="")[2]
    assert len(colima) == 2 and all("cliPluginsExtraDirs" in f for f in colima)
    assert "cliPluginsExtraDirs" not in run(LINUX, compose="")[2][0]


def test_low_resources_warn_only():
    small = copy.deepcopy(LINUX)
    small["info"].update(NCPU=1, MemTotal=2 * 1024**3)
    _, warnings, failures = run(small)
    assert failures == [] and "1 CPUs and 2.0 GiB" in warnings[0] and "colima start" not in warnings[0]
    small_mac = copy.deepcopy(COLIMA)
    small_mac["info"].update(MemTotal=2 * 1024**3)
    _, warnings, _ = run(small_mac, "colima", COLIMA_SOCKET)
    assert "colima start --cpu 2 --memory 4" in warnings[0]


def test_main(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(LINUX)))
    assert host_runtime.main(["--context", "default", "--compose", "5.7.1", "--buildx", "v0.39"]) == 0
    assert capsys.readouterr().out.strip() == "runtime: Linux Docker Engine, engine 29.10.0, amd64"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(LINUX)))
    assert host_runtime.main(["--compose", "5.7.1"]) == 1  # no buildx
    monkeypatch.setattr("sys.stdin", io.StringIO('{"version": {}}'))
    assert host_runtime.main([]) == 1
