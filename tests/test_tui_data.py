"""Read-only projection tests for the optional OpenTTD evidence TUI."""

import json
from pathlib import Path

from app.tui.data import (
    SAMPLE_REPORT,
    UNKNOWN,
    catalog,
    discover,
    display,
    load_detail,
    money,
    number,
    plain,
    read_json,
)


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def make_report(
    directory: Path, *, classification: str = "NATIVE_MULTI_SERVICE_EVALUATION"
) -> Path:
    directory.mkdir()
    write_json(
        directory / "evaluation.json",
        {
            "classification": classification,
            "services": [
                {
                    "demand_id": "benchmark-0-1-1",
                    "metrics": [
                        {"name": "delivered_cargo", "actual": "20"},
                        {"name": "vehicles", "actual": "1"},
                        {"name": "vehicle_purchase", "actual": "4429"},
                        {"name": "exclusive_infrastructure_capex", "actual": "5157"},
                        {"name": "operating_costs", "actual": None},
                    ],
                    "game_time": {"final_cargo_delivery_date": 712328},
                }
            ],
            "metrics": [
                {
                    "scope": "network_batch",
                    "name": "delivered_cargo",
                    "planned": "20",
                    "actual": "20",
                    "difference": "0",
                    "unit": "cargo_units",
                    "comparison": "comparable",
                },
                {
                    "scope": "network_batch",
                    "name": "delivery_revenue",
                    "planned": None,
                    "actual": "340",
                    "difference": None,
                    "unit": "GBP",
                    "comparison": "unavailable",
                },
                {
                    "scope": "network_batch",
                    "name": "operating_costs",
                    "planned": None,
                    "actual": None,
                    "difference": None,
                    "unit": "GBP",
                    "comparison": "unavailable",
                },
            ],
            "limitations": ["Synthetic fixture, not a native run."],
        },
    )
    (directory / "results.md").write_text("# Fixture report\n", encoding="utf-8")
    return directory


def make_run(directory: Path) -> Path:
    directory.mkdir()
    write_json(
        directory / "result.json",
        {
            "status": "COMPLETED",
            "services": 2,
            "delivered": 40,
            "payment_income": 680,
            "construction_purchase_spending": 12000,
        },
    )
    write_json(
        directory / "PRELAUNCH.json",
        {
            "world": {"source": "fixture", "seed": 17, "width": 256, "height": 256},
            "experiment": {"scenario": "freight", "budget_gbp": 50000},
        },
    )
    write_json(
        directory / "receipt.json",
        {
            "services": [
                {
                    "source": "mine",
                    "destination": "factory",
                    "vehicle": "truck",
                    "delivered": 20,
                    "payment_income": 340,
                    "construction_purchase_spending": 6000,
                },
                {
                    "source": "farm",
                    "destination": "factory",
                    "vehicle": "truck",
                    "delivered": 20,
                    "payment_income": 340,
                    "construction_purchase_spending": 6000,
                },
            ]
        },
    )
    return directory


def test_sample_report_catalog_and_detail_are_evidence_bearing() -> None:
    entries = catalog(SAMPLE_REPORT)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.kind == "report"
    assert entry.status == "NATIVE_MULTI_SERVICE_EVALUATION"
    assert entry.services_count == 3
    assert display(entry.delivered) == "60"

    detail = load_detail(entry)
    assert len(detail.services) == 3
    assert {row.status for row in detail.services} == {"VERIFIED_BATCH"}
    assert [row.delivered for row in detail.services] == ["20", "20", "20"]
    # The retained evaluation records no per-service revenue comparison.
    assert {row.revenue for row in detail.services} == {UNKNOWN}
    assert all(row.backlog == UNKNOWN for row in detail.services)
    assert len(detail.metrics) == 15
    assert detail.points == ()
    assert [row.label for row in detail.finance] == [
        "Delivery revenue",
        "Total CAPEX",
        "Infrastructure CAPEX",
        "Vehicle purchase",
    ]
    assert detail.files
    assert any("never launches OpenTTD" in note for note in detail.notes)


def test_missing_values_stay_unknown_and_recorded_zero_stays_zero() -> None:
    assert money(None) == UNKNOWN
    assert money("") == UNKNOWN
    assert money(0) == "£0"
    assert money("12.5") == "£12.50"
    assert money("not-a-number") == "not-a-number"

    assert display(None) == UNKNOWN
    assert display(0) == "0"
    assert display(False) == "no"
    assert plain(None) == UNKNOWN
    assert plain(712328.0) == "712328"

    assert number(None) is None
    assert number("nan") is None
    assert number("12.5") == 12.5


def test_report_detail_marks_unattributable_and_unmeasured_values_unknown(
    tmp_path: Path,
) -> None:
    report = load_detail(make_report(tmp_path / "report", classification="PARTIAL"))

    assert report.entry.status == "PARTIAL"
    service = report.services[0]
    assert service.status == UNKNOWN
    assert service.revenue == UNKNOWN
    assert service.capex == "£9,586"
    assert service.backlog == UNKNOWN
    operating = next(row for row in report.metrics if row.name == "operating_costs")
    assert operating.actual == UNKNOWN
    assert any("Synthetic fixture" in note for note in report.notes)


def test_comparable_service_revenue_is_shown(tmp_path: Path) -> None:
    report = make_report(tmp_path / "report")
    evaluation = json.loads((report / "evaluation.json").read_text(encoding="utf-8"))
    evaluation["services"][0]["metrics"].append(
        {"name": "delivery_revenue", "actual": "340", "comparison": "comparable"}
    )
    write_json(report / "evaluation.json", evaluation)

    assert load_detail(report).services[0].revenue == "£340"


def test_run_catalog_uses_receipt_and_world_without_inventing_zeroes(
    tmp_path: Path,
) -> None:
    run = make_run(tmp_path / "run")
    entries = discover(run)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.kind == "run"
    assert entry.status == "COMPLETED"
    assert entry.services_count == 2
    assert display(entry.delivered) == "40"
    assert "seed=17" in entry.world
    assert "budget_gbp=50,000" in entry.experiment

    detail = load_detail(entry)
    assert [row.service for row in detail.services] == [
        "mine -> factory",
        "farm -> factory",
    ]
    assert all(row.status == "RECEIPT" for row in detail.services)
    assert [row.revenue for row in detail.services] == ["£340", "£340"]
    assert detail.metrics == ()

    missing = tmp_path / "missing"
    missing.mkdir()
    write_json(
        missing / "result.json",
        {"status": "COMPLETED", "services": 2, "delivered": None},
    )
    missing_entry = discover(missing)[0]
    assert display(missing_entry.delivered) == UNKNOWN
    assert money(missing_entry.revenue) == UNKNOWN
    assert money(missing_entry.capex) == UNKNOWN


def test_partial_or_invalid_json_degrades_to_unknown(tmp_path: Path) -> None:
    run = make_run(tmp_path / "broken")
    (run / "receipt.json").write_text("{not json", encoding="utf-8")
    (run / "PRELAUNCH.json").write_text('["not", "an", "object"]', encoding="utf-8")
    (run / "evaluation.json").write_text("{}", encoding="utf-8")

    assert read_json(run / "receipt.json") is None

    entries = discover(run)
    assert len(entries) == 1
    assert entries[0].world == UNKNOWN
    detail = load_detail(entries[0])
    assert detail.services == ()
    assert detail.notes


def test_read_json_rejects_non_objects_and_oversized_files(tmp_path: Path) -> None:
    array = write_json(tmp_path / "array.json", [1, 2, 3])
    big = tmp_path / "big.json"
    big.write_text('{"payload": "' + "x" * 64 + '"}', encoding="utf-8")

    assert read_json(array) is None
    assert read_json(big, limit=32) is None
    assert read_json(tmp_path / "absent.json") is None


def test_discovery_ignores_unrelated_directories_and_deduplicates(tmp_path: Path) -> None:
    make_report(tmp_path / "report")
    make_run(tmp_path / "run")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "readme.txt").write_text("ignore me", encoding="utf-8")

    entries = discover(tmp_path)
    assert [entry.name for entry in entries] == ["report", "run"]

    duplicate = discover(tmp_path, include_sample=True)
    assert len(duplicate) == 3
    assert duplicate[-1].name == "sample-report"

    assert catalog(tmp_path / "absent", include_sample=False) == []


def test_discovery_finds_artifacts_one_level_below_root(tmp_path: Path) -> None:
    runtime = tmp_path / "artifacts"
    runtime.mkdir()
    make_run(runtime / "attempt")

    assert [entry.name for entry in discover(tmp_path)] == ["attempt"]


def test_proof_attempt_classification_supplies_status_and_identity(tmp_path: Path) -> None:
    run = tmp_path / "attempt"
    run.mkdir()
    write_json(
        run / "PRELAUNCH.json",
        {"proof_kind": "two-rollover-qualification", "attempt_id": "fixture-attempt"},
    )
    write_json(
        run / "proof-attempt.json",
        {"classification": "RUNTIME", "attempt_id": "fixture-attempt"},
    )

    entry = discover(run)[0]
    assert entry.kind == "run"
    assert entry.status == "RUNTIME"
    assert entry.experiment.startswith("proof_kind=")


def test_manifest_digests_are_attached_to_file_rows(tmp_path: Path) -> None:
    report = make_report(tmp_path / "report")
    digest = "a" * 64
    (report / "artifact-manifest.sha256").write_text(
        f"{digest}  evaluation.json\n",
        encoding="utf-8",
    )

    detail = load_detail(report)
    files = {row.name: row for row in detail.files}
    assert files["evaluation.json"].digest == digest
    assert files["evaluation.json"].size > 0
    assert files["results.md"].digest is None


def test_catalog_falls_back_to_bundled_sample_only_when_empty(tmp_path: Path) -> None:
    assert SAMPLE_REPORT.is_dir()
    entries = catalog(tmp_path, include_sample=True)
    assert len(entries) == 1
    assert entries[0].kind == "sample"
    assert entries[0].name == "sample-report (bundled)"

    report = make_report(tmp_path / "report")
    assert [entry.path for entry in catalog(report, include_sample=True)] == [report]


def test_cli_dump_is_read_only_text_output(capsys) -> None:
    from app.tui.cli import main

    assert main(["--root", str(SAMPLE_REPORT), "--dump"]) == 0
    output = capsys.readouterr().out
    assert "sample-report" in output
    assert "NATIVE_MULTI_SERVICE_EVALUATION" in output
    assert "Read-only" in output
