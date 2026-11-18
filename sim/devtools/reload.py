"""Dev mode only (ENV-12): rerun a command whenever a .py file under a directory changes.

Usage: reload.py <dir> <command...>. Standard library and polling only, so it works on a
read-only mount and on Colima, where host file events do not reach the container.
"""

import subprocess
import sys
import time
from pathlib import Path


def snapshot(root: str) -> dict:
    return {p: p.stat().st_mtime_ns for p in Path(root).rglob("*.py")}


def main() -> None:
    root, command = sys.argv[1], sys.argv[2:]
    while True:
        seen = snapshot(root)
        proc = subprocess.Popen(command)
        while proc.poll() is None and snapshot(root) == seen:
            time.sleep(1)
        if proc.poll() is None:
            proc.terminate()
            proc.wait()
        else:  # it exited by itself: wait for a fix instead of restarting in a loop
            print(f"reload: exited with {proc.returncode}; waiting for a change", flush=True)
            while snapshot(root) == seen:
                time.sleep(1)
        print("reload: change detected, restarting", flush=True)


if __name__ == "__main__":
    main()
