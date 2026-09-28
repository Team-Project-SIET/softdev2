"""T18 keeps the research record without an executable prototype fallback."""

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_archived_prototype_contains_evidence_but_no_runtime() -> None:
    archive = ROOT / "prototype/live_admin"
    assert not list(archive.rglob("*.py"))
    assert not list(archive.rglob("*.pyc"))
    for name in ("README.md", "REPORT.md", "proof.json"):
        assert (archive / name).is_file()
    assert (ROOT / "tests/fixtures/openttd_admin_13_4/README.md").is_file()
    assert (ROOT / "tests/fixtures/openttd_13_4/seed-17-simpleai-road.sav").is_file()
    assert (ROOT / "docs/live-production-smoke.md").is_file()


def test_production_imports_and_entrypoints_exclude_prototype_runtime() -> None:
    for path in (ROOT / "app").rglob("*.py"):
        syntax = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(syntax):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("prototype") for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("prototype"), path
            elif isinstance(node, ast.Attribute):
                assert node.attr != "_run_experiment", path
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "prototype.live_admin" not in node.value, path
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert all("prototype" not in target for target in project["project"]["scripts"].values())
