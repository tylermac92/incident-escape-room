"""ENV-01: `sim` must not depend on `controller`, in its dependencies or its source."""

import ast
import importlib.util
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def test_controller_is_not_installed_in_sim_environment():
    assert importlib.util.find_spec("controller") is None


def test_sim_source_never_imports_controller():
    offenders = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [f"{path}: {n}" for n in names if n.split(".")[0] == "controller"]
    assert offenders == []
