"""P07 capacity companion exports only controlled allocations and sampled evidence."""

import json

import pytest

from app.experiments.freight_capacity_report import render_capacity_report


def comparison():
    return dict(
        monthly_queue_samples=[
            dict(service="S2", mean_sampled_queue=651.42),
            dict(service="S3", mean_sampled_queue=557.10),
        ],
        configurations=[
            dict(
                configuration="B",
                allocation={"S1": 1, "S2": 2, "S3": 1},
                estimated_capex_gbp="30036",
            )
        ],
        readiness_blockers=["Fourth-vehicle binding <unavailable>"],
    )


def test_companion_retains_unknown_treatment_results_and_escapes_text():
    html = render_capacity_report(comparison())
    assert "651.42" in html and "557.1" in html
    assert "30036" in html and html.count("<td>UNKNOWN</td>") == 2
    assert "&lt;unavailable&gt;" in html
    assert 'href="charts.html"' in html
    assert "Historical Attempt 19 remains FAILED" in html


def test_existing_cli_exports_capacity_companion_offline(monkeypatch, tmp_path):
    from app.experiments import capacity_experiment, freight_continuous_analytics
    from app.experiments.cli import main

    attempt, output = tmp_path / "attempt", tmp_path / "output"
    attempt.mkdir()

    def analyze(source, destination, **kwargs):
        assert source == attempt
        destination.mkdir()
        (destination / "summary.json").write_text(json.dumps({"source_directory": str(attempt)}))
        return {}

    def prepare(source, report):
        assert source == attempt and report["source_directory"] == str(attempt)
        return comparison()

    monkeypatch.setattr(freight_continuous_analytics, "analyze_continuous", analyze)
    monkeypatch.setattr(capacity_experiment, "prepare_capacity_experiment", prepare)
    assert (
        main(
            [
                "analyze-continuous-freight",
                str(attempt),
                "--output",
                str(output),
                "--prepare-capacity-experiment",
            ]
        )
        == 0
    )
    assert json.loads((output / "capacity-experiment.json").read_text()) == comparison()
    assert (output / "capacity-comparison.html").read_text() == render_capacity_report(comparison())


@pytest.mark.parametrize("name", ["capacity-experiment.json", "capacity-comparison.html"])
def test_capacity_cli_rejects_protected_output_symlink_before_replay(tmp_path, monkeypatch, name):
    from app.experiments import freight_continuous_analytics
    from app.experiments.cli import main

    attempt, output = tmp_path / "attempt", tmp_path / "output"
    attempt.mkdir()
    output.mkdir()
    protected = attempt / "evidence.json"
    protected.write_text("preserved")
    (output / name).symlink_to(protected)

    def forbidden(*args, **kwargs):
        raise AssertionError("must reject before replay/output writes")

    monkeypatch.setattr(freight_continuous_analytics, "analyze_continuous", forbidden)
    assert (
        main(
            [
                "analyze-continuous-freight",
                str(attempt),
                "--output",
                str(output),
                "--prepare-capacity-experiment",
            ]
        )
        == 1
    )
    assert protected.read_text() == "preserved"
