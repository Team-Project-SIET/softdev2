"""Keep retired operational application code out of the research package."""

import ast
import importlib
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED = (
    "app.tui",
    "app.integrations.line",
    "app.customer",
    "app.driver",
    "app.shipment",
    "app.vehicle",
    "app.routing",
    "app.packing",
    "app.database.seed",
)


def test_research_package_excludes_retired_code_and_entrypoints() -> None:
    for module in RETIRED:
        path = ROOT.joinpath(*module.split("."))
        assert not path.exists(), module
        assert not path.with_suffix(".py").exists(), module
        assert not path.with_suffix(".pyc").exists(), module
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert "logistics-tui" not in project["scripts"]
    assert "logistics-seed" not in project["scripts"]
    assert project["scripts"]["transport-experiment"] == "app.experiments.cli:main"
    assert callable(importlib.import_module("app.experiments.cli").main)
    dependencies = {value.split("=", 1)[0].split(">", 1)[0] for value in project["dependencies"]}
    assert "textual" not in dependencies
    assert "ortools" in dependencies


def test_live_python_imports_exclude_retired_packages() -> None:
    for root in ("app", "tests", "alembic"):
        for path in (ROOT / root).rglob("*.py"):
            syntax = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(syntax):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                    names.extend(f"{node.module}.{alias.name}" for alias in node.names)
                else:
                    continue
                assert not any(
                    name == retired or name.startswith(retired + ".")
                    for name in names
                    for retired in RETIRED
                ), path
