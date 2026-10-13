"""Offline native P07 replay plus controlled storage and comparison checks."""

import csv
import json
import socket
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.experiments.cli import main
from app.experiments.freight_analytics import analyze, render_html, summarize
from app.experiments.freight_evaluation import FreightEvaluation, FreightMetric, evaluate_freight
from app.experiments.freight_history import FreightHistory
from app.planning.realized import ArtifactReference
from app.simulation.openttd.proof.native import NativeBackend
from app.simulation.openttd.secure_admin import SecureAdminSession

ROOT = Path(__file__).resolve().parents[1] / "artifacts/runtime"


@pytest.fixture(autouse=True)
def forbid_native_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline P07 attempted process launch, native authorization or network access")

    monkeypatch.setattr(NativeBackend, "__init__", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(SecureAdminSession, "connect_secure", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture(scope="module")
def retained_paths():
    paths = [ROOT / f"openttd-15.3-first-freight-delivery-attempt{n}" for n in (4, 8, 9)]
    if not all((path / "artifact-manifest.sha256").exists() for path in paths):
        pytest.skip("optional retained native artifacts are not installed")
    return paths


@pytest.fixture
def evaluations(retained_paths):
    return tuple(evaluate_freight(path) for path in retained_paths)


@pytest.fixture
def controlled_evaluations():
    # Pure storage/comparison fixtures; they do not claim native verification.
    artifact = ArtifactReference(sha256="b" * 64, reference="controlled.json")
    metrics = tuple(
        FreightMetric(
            name=name,
            unit=unit,
            scope="controlled-test",
            actual=amount,
            provenance="Controlled aggregation fixture, never game evidence.",
        )
        for name, amount, unit in (
            ("delivered_cargo", Decimal(20), "cargo_units"),
            ("delivery_revenue", Decimal(325), "GBP"),
            ("net_return", None, "GBP"),
        )
    )
    planner = FreightEvaluation(
        run_name="controlled-planner",
        attempt=9,
        mode="planner-driven",
        status="verified-delivery",
        reason=None,
        source_directory="/controlled-test",
        receipt=artifact,
        artifact_manifest=artifact,
        result=artifact,
        native_plan_digest="b" * 64,
        execution_plan_digest="b" * 64,
        cohort_digest="c" * 64,
        cohort_definition={"mode": "planner-driven"},
        metrics=metrics,
        findings=(),
        limitations=("Controlled test fixture",),
    )
    old = planner.model_copy(
        update={
            "run_name": "controlled-standalone",
            "attempt": 4,
            "mode": "standalone",
            "cohort_digest": "d" * 64,
            "cohort_definition": {"mode": "standalone"},
            "receipt": ArtifactReference(sha256="d" * 64, reference="controlled.json"),
        }
    )
    failed = planner.model_copy(
        update={
            "run_name": "controlled-failure",
            "attempt": 8,
            "status": "failed",
            "metrics": (),
            "receipt": None,
            "cohort_digest": None,
            "cohort_definition": {},
            "artifact_manifest": ArtifactReference(sha256="e" * 64, reference="controlled.json"),
        }
    )
    return old, failed, planner


def values(run):
    return {m.name: m for m in run.metrics}


def test_native_p07_compares_plan_to_actual_and_preserves_unknowns(evaluations):
    old, failed, planner = evaluations
    m = values(planner)
    assert planner.status == "verified-delivery" and planner.mode == "planner-driven"
    assert planner.receipt and planner.execution_plan_digest
    assert (
        m["delivered_cargo"].planned,
        m["delivered_cargo"].actual,
        m["delivered_cargo"].difference,
    ) == (20, 20, 0)
    assert (m["stations"].planned, m["stations"].actual) == (2, 2)
    assert (m["depots"].planned, m["depots"].actual) == (1, 1)
    assert (m["vehicles"].planned, m["vehicles"].actual) == (1, 1)
    assert (m["corridor_tiles"].planned, m["corridor_tiles"].actual) == (24, 24)
    assert (m["total_capex"].planned, m["total_capex"].actual) == (8583, 9586)
    assert (
        m["infrastructure_capex"].planned,
        m["infrastructure_capex"].actual,
        m["infrastructure_capex"].difference,
    ) == (4154, 5157, 1003)
    assert m["vehicle_purchase"].actual == 4429
    assert (m["road_capex"].planned, m["road_capex"].actual) == (3479, 4067)
    assert (m["station_capex"].planned, m["station_capex"].actual) == (300, 685)
    assert (m["depot_capex"].planned, m["depot_capex"].actual) == (375, 405)
    assert m["source_waiting"].actual == 48
    assert m["delivery_revenue"].actual == 325 and m["vehicle_profit"].actual == 289
    assert m["revenue_profit_residual"].actual == 36
    assert m["load_fill"].actual == 100
    for name in ("operating_costs", "net_return", "time_utilization"):
        assert m[name].actual is None and m[name].comparison == "unavailable"
    assert values(old)["delivery_revenue"].actual == 341
    assert values(old)["total_capex"].planned is None
    assert old.mode == "standalone" and old.cohort_digest != planner.cohort_digest
    assert failed.status == "failed" and failed.metrics == () and failed.receipt is None
    assert any("£1003" in finding for finding in planner.findings)
    assert not any("routing inefficiency proven" in finding for finding in planner.findings)


def test_cli_exports_real_retained_results_and_is_idempotent(retained_paths, tmp_path, capsys):
    output, db = tmp_path / "analysis", tmp_path / "history.sqlite"
    args = [
        "analyze-freight",
        *map(str, retained_paths),
        "--history",
        str(db),
        "--output",
        str(output),
    ]
    assert main(args) == 0
    assert main(args) == 0
    report = json.loads((output / "summary.json").read_text())
    assert len(report["runs"]) == 3
    assert report["successful_deliveries"] == 2 and report["failed_attempts"] == 1
    assert len(report["cohorts"]) == 2
    assert all(c["count"] == 1 and not c["trend_available"] for c in report["cohorts"])
    assert all(c["metrics"]["delivered_cargo"]["mean"] == 20 for c in report["cohorts"])
    with (output / "metrics.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert next(r for r in rows if r["metric"] == "net_return")["actual"] == ""
    assert next(r for r in rows if r["status"] == "failed")["actual"] == ""
    html = (output / "charts.html").read_text()
    for title in (
        "1. Planned vs actual performance",
        "2. Revenue and spending",
        "3. Delivered cargo",
        "4. Vehicle utilization",
        "5. Descriptive history across comparable runs",
    ):
        assert title in html
    assert html.count("<svg") == 8
    assert "One comparable run; no trend can be inferred." in html
    assert "<polyline" not in html and "unknown" in html
    assert (
        "https://" not in html and "<script" not in html
    )  # Self-contained, no external chart service.
    assert "successful_deliveries" in capsys.readouterr().out


def test_changed_evidence_rejected_before_history_creation(retained_paths, tmp_path):
    import shutil

    path = tmp_path / "tampered"
    shutil.copytree(retained_paths[2], path)
    receipt = json.loads((path / "receipt.json").read_text())
    receipt["delivered"] = 999
    (path / "receipt.json").write_text(json.dumps(receipt))
    db = tmp_path / "history.sqlite"
    with pytest.raises(ValueError, match="integrity"):
        analyze([path], db, tmp_path / "output")
    assert not db.exists() and not (tmp_path / "output").exists()


def test_outputs_cannot_overwrite_native_evidence(retained_paths, tmp_path):
    with pytest.raises(ValueError, match="must not modify"):
        analyze([retained_paths[2]], tmp_path / "history.sqlite", retained_paths[2])


def test_controlled_comparison_only_averages_matching_verified_cohorts(controlled_evaluations):
    old, failed, planner = controlled_evaluations
    # Controlled second evaluation to exercise aggregation; never native evidence.
    metrics = tuple(
        m.model_copy(update={"actual": Decimal(30)}) if m.name == "delivered_cargo" else m
        for m in planner.metrics
    )
    second = planner.model_copy(
        update={
            "attempt": 10,
            "run_name": "controlled-second-run",
            "metrics": metrics,
            "receipt": ArtifactReference(sha256="a" * 64, reference="controlled-receipt.json"),
        }
    )
    report = summarize((old, failed, planner, second))
    assert report["successful_deliveries"] == 3 and len(report["cohorts"]) == 2
    group = next(c for c in report["cohorts"] if c["count"] == 2)
    assert group["metrics"]["delivered_cargo"]["mean"] == 25
    assert not group["trend_available"]
    assert "<polyline" not in render_html((old, failed, planner, second), report)
    assert all(c["metrics"]["delivered_cargo"]["count"] == c["count"] for c in report["cohorts"])


def test_history_refuses_conflicting_provenance_and_detects_corruption(
    controlled_evaluations, tmp_path
):
    evaluations = controlled_evaluations
    history = FreightHistory(tmp_path / "history.sqlite")
    try:
        history.add(list(evaluations))
        history.add(list(evaluations))
        assert len(history.runs()) == 3
        changed = evaluations[2].model_copy(update={"source_directory": "/wrong-source"})
        with pytest.raises(ValueError, match="different provenance"):
            history.add([changed])
        with history.engine.begin() as connection:
            connection.execute(text("UPDATE freight_run_history SET evaluation_digest = 'broken'"))
        with pytest.raises(ValueError, match="digest mismatch"):
            history.runs()
    finally:
        history.close()


def test_history_migration_upgrade_and_safe_downgrade(tmp_path):
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    path = Path(__file__).resolve().parents[1] / "alembic/versions/0009_freight_run_history.py"
    spec = importlib.util.spec_from_file_location("freight_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
                assert "freight_run_history" in inspect(connection).get_table_names()
                connection.execute(
                    text("INSERT INTO freight_run_history VALUES ('source', 'evaluation', '{}')")
                )
                with pytest.raises(ValueError, match="Refuse"):
                    module.downgrade()
                connection.execute(text("DELETE FROM freight_run_history"))
                module.downgrade()
                assert "freight_run_history" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()


def test_export_symlink_cannot_overwrite_retained_receipt(retained_paths, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "summary.json").symlink_to(retained_paths[2] / "receipt.json")
    with pytest.raises(ValueError, match="must not modify"):
        analyze([retained_paths[2]], tmp_path / "history.sqlite", output)


def test_network_cli_and_history_replay_are_offline_and_reproducible(tmp_path):
    from app.planning.network_cli import main as network_main

    native = ROOT / "openttd-15.3-first-freight-delivery-attempt12"
    if not (native / "artifact-manifest.sha256").exists():
        pytest.skip("optional retained native network artifacts are not installed")
    output = tmp_path / "network"
    args = [
        str(native / "planning-scenario.json"),
        "--native-network-directory",
        str(native),
        "--output",
        str(output),
    ]
    assert network_main(args) == 0
    first = (output / "evaluation.json").read_bytes()
    assert network_main(args) == 0
    assert (output / "evaluation.json").read_bytes() == first
    report = json.loads(first)
    assert report["classification"] == "NATIVE_MULTI_SERVICE_EVALUATION"
    assert report["verified_service_count"] == 2
    paths = [ROOT / f"openttd-15.3-first-freight-delivery-attempt{n}" for n in (4, 8, 9, 12)]
    analysis = tmp_path / "analysis"
    db = tmp_path / "history.sqlite"
    analyze(paths, db, analysis)
    analyze(paths, db, analysis)
    summary = json.loads((analysis / "summary.json").read_text())
    assert len(summary["runs"]) == 4
    assert summary["successful_deliveries"] == 3 and summary["failed_attempts"] == 1
    network = next(run for run in summary["runs"] if run["attempt"] == 12)
    assert network["mode"] == "planner-network"
    metrics = {m["name"]: m for m in network["metrics"]}
    assert metrics["delivered_cargo"]["actual"] == "40"
    assert metrics["total_capex"]["actual"] == "19101"
    assert metrics["delivery_revenue"]["actual"] == "682"
    assert metrics["operating_costs"]["actual"] is None
    assert all(not c["trend_available"] for c in summary["cohorts"])
    feedback = json.loads((analysis / "feedback.json").read_text())[0]
    assert feedback["findings"]
    assert feedback["evidence_directory"] == str(native.resolve())
    html = (analysis / "charts.html").read_text()
    assert "serial network services" in html and "Evidence-linked optimization feedback" in html
    assert "Actual minus planned: 1935" in html
    assert "<polyline" not in html
    with pytest.raises(SystemExit):
        network_main([*args[:-1], str(native)])


def test_network_failure_keeps_mode_and_unknown_delivery():
    native = ROOT / "openttd-15.3-first-freight-delivery-attempt11"
    if not (native / "artifact-manifest.sha256").exists():
        pytest.skip("optional retained network failure is not installed")
    evaluation = evaluate_freight(native)
    assert evaluation.status == "failed" and evaluation.mode == "planner-network"
    assert evaluation.metrics == () and evaluation.network_report is None


def test_history_accepts_legacy_single_service_payload_without_optional_network_report(
    controlled_evaluations, tmp_path
):
    from sqlalchemy.orm import Session

    from app.experiments.freight_evaluation import document_digest
    from app.experiments.freight_history import FreightRunRecord

    evaluation = controlled_evaluations[2]
    document = evaluation.model_dump(mode="json")
    document.pop("network_report")
    history = FreightHistory(tmp_path / "legacy.sqlite")
    try:
        with Session(history.engine) as session, session.begin():
            session.add(
                FreightRunRecord(
                    source_digest=evaluation.history_key,
                    evaluation_digest=document_digest(document),
                    evaluation=document,
                )
            )
        history.add([evaluation])
        assert len(history.runs()) == 1
    finally:
        history.close()
