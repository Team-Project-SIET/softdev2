"""T09 final-result contract over one static genuine OpenTTD 13.4 save."""

import asyncio
import gzip
import hashlib
import json
import shutil
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from test_live_runner import _config, _runtime

from app.simulation.openttd.final_result import FinalResultError, FinalResultProcessor
from app.simulation.openttd.live_launch import LiveLaunchPreparation
from app.simulation.openttd.live_runner import LiveRunProgress

FIXTURE = Path(__file__).parent / "fixtures/openttd_13_4/seed-17-simpleai-road.sav"
SHA256 = "062f7cb99d3fb4fb8ee722191c537331fd0f4e8e6f663b88ac3ab3b9d7ad7fad"


@pytest.fixture
def prepared(tmp_path: Path):
    runtime = _runtime(tmp_path, "normal")
    owned = LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks").prepare(
        _config(), runtime
    )
    try:
        yield owned
    finally:
        owned.close()


def _progress(prepared, artifact_dir: Path) -> LiveRunProgress:
    return LiveRunProgress(
        run_id=7,
        artifact_dir=artifact_dir,
        process_id=123,
        configured_start_day=712223,
        observed_start_day=712223,
        target_day=712224,
        last_observed_day=712224,
    )


def test_static_fixture_is_genuine_parseable_and_contains_company_zero() -> None:
    from openttdlab import parse_savegame

    assert FIXTURE.stat().st_size == 99_264
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == SHA256
    with FIXTURE.open("rb") as source:
        game = parse_savegame(iter(lambda: source.read(65536), b""))
    assert game["savegame_version"] == 302
    assert game["chunks"]["DATE"]["records"]["0"]["date"] == 712224
    assert "0" in game["chunks"]["PLYR"]["records"]


def test_public_parser_produces_existing_metrics_and_two_artifacts(
    tmp_path: Path, prepared
) -> None:
    shutil.copyfile(FIXTURE, prepared.final_save_path)
    result = asyncio.run(
        FinalResultProcessor()(prepared, _progress(prepared, tmp_path / "artifacts"), _config())
    )
    assert result.simulation_date == date(1950, 1, 2)
    assert result.savegame_version == 302
    assert [(metric.name, metric.value, metric.unit) for metric in result.metrics] == [
        ("company_money", 99566, "GBP"),
        ("company_loan", 100000, "GBP"),
        ("current_period_income", 0, "GBP"),
        ("current_period_expenses", 0, "GBP"),
        ("current_period_cargo_delivered", 0, "cargo_units"),
    ]
    summary = result.live_summary
    assert summary is not None
    assert summary.actual_final_day == 712224
    assert summary.raw_save_sha256 == SHA256
    assert summary.raw_save_reference is not None
    assert summary.parsed_artifact_reference is not None
    assert summary.parsed_artifact_sha256 is not None
    raw = Path(summary.raw_save_reference)
    parsed = Path(summary.parsed_artifact_reference)
    assert raw.name == "experiment-7.sav"
    assert parsed.name == "experiment-7.json.gz"
    assert raw.read_bytes() == FIXTURE.read_bytes()
    assert hashlib.sha256(parsed.read_bytes()).hexdigest() == summary.parsed_artifact_sha256
    assert result.raw_artifact_reference == str(parsed)
    with gzip.open(parsed, "rt", encoding="utf-8") as source:
        artifact = json.load(source)
    assert set(artifact) == {
        "configuration",
        "date",
        "savegame_version",
        "chunks",
        "output",
        "error",
    }
    assert artifact["date"] == "1950-01-02"
    assert artifact["chunks"]["PLYR"]["0"]["money"] == 99566


def test_missing_final_save_never_substitutes_monthly_autosave(tmp_path: Path, prepared) -> None:
    autosave = prepared.workspace / "save/autosave1950-01.sav"
    shutil.copyfile(FIXTURE, autosave)
    with pytest.raises(FinalResultError, match="requested final save missing"):
        asyncio.run(FinalResultProcessor()(prepared, _progress(prepared, tmp_path), _config()))


def test_corrupt_final_save_fails_but_retains_raw_artifact(tmp_path: Path, prepared) -> None:
    prepared.final_save_path.write_bytes(b"not an OpenTTD save")
    with pytest.raises(FinalResultError, match="could not be parsed"):
        asyncio.run(
            FinalResultProcessor()(prepared, _progress(prepared, tmp_path / "out"), _config())
        )
    assert (tmp_path / "out/experiment-7.sav").read_bytes() == b"not an OpenTTD save"


def test_missing_required_company_fails_without_fabricated_metrics(
    tmp_path: Path, prepared, monkeypatch
) -> None:
    import openttdlab

    shutil.copyfile(FIXTURE, prepared.final_save_path)
    monkeypatch.setattr(
        openttdlab,
        "parse_savegame",
        lambda _chunks: {"chunks": {"PLYR": {"records": {}}}},
    )
    with pytest.raises(FinalResultError, match="company 0 missing"):
        FinalResultProcessor().process(prepared, _progress(prepared, tmp_path), _config())


def test_final_save_path_must_be_owned_and_regular(tmp_path: Path, prepared) -> None:
    outside = tmp_path / "outside.sav"
    shutil.copyfile(FIXTURE, outside)
    with pytest.raises(FinalResultError, match="path mismatch"):
        asyncio.run(
            FinalResultProcessor()(
                replace(prepared, final_save_path=outside), _progress(prepared, tmp_path), _config()
            )
        )
    prepared.final_save_path.mkdir()
    with pytest.raises(FinalResultError, match="not a regular file"):
        asyncio.run(FinalResultProcessor()(prepared, _progress(prepared, tmp_path), _config()))


def test_existing_artifact_is_preserved_when_publication_conflicts(
    tmp_path: Path, prepared
) -> None:
    shutil.copyfile(FIXTURE, prepared.final_save_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    existing = artifacts / "experiment-7.sav"
    existing.write_bytes(b"unrelated existing artifact")
    with pytest.raises(FinalResultError, match="artifact could not be written"):
        asyncio.run(FinalResultProcessor()(prepared, _progress(prepared, artifacts), _config()))
    assert existing.read_bytes() == b"unrelated existing artifact"


def test_older_final_save_cannot_claim_a_later_target(tmp_path: Path, prepared) -> None:
    shutil.copyfile(FIXTURE, prepared.final_save_path)
    progress = replace(_progress(prepared, tmp_path), target_day=712253, last_observed_day=712253)
    with pytest.raises(FinalResultError, match="predates requested target"):
        asyncio.run(FinalResultProcessor()(prepared, progress, _config()))


def test_final_save_cannot_predate_last_live_date(tmp_path: Path, prepared) -> None:
    shutil.copyfile(FIXTURE, prepared.final_save_path)
    progress = replace(_progress(prepared, tmp_path), last_observed_day=712225)
    with pytest.raises(FinalResultError, match="predates last observed date"):
        asyncio.run(FinalResultProcessor()(prepared, progress, _config()))


def test_save_source_revision_must_match_expected_runtime(tmp_path: Path, prepared) -> None:
    shutil.copyfile(FIXTURE, prepared.final_save_path)
    wrong_version = _config().model_copy(update={"openttd_version": "13.5"})
    with pytest.raises(FinalResultError, match="OpenTTD revision mismatch"):
        FinalResultProcessor().process(prepared, _progress(prepared, tmp_path), wrong_version)
    assert (tmp_path / "experiment-7.sav").exists()


def test_save_source_ai_must_match_expected_configuration(tmp_path: Path, prepared) -> None:
    shutil.copyfile(FIXTURE, prepared.final_save_path)
    wrong_ai = _config().ai.model_copy(update={"name": "DifferentAI"})
    wrong_config = _config().model_copy(update={"ai": wrong_ai})
    with pytest.raises(FinalResultError, match="AI identity mismatch"):
        FinalResultProcessor().process(prepared, _progress(prepared, tmp_path), wrong_config)


def test_save_directory_symlink_cannot_escape_workspace(tmp_path: Path, prepared) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (prepared.workspace / "save").rmdir()
    (prepared.workspace / "save").symlink_to(outside, target_is_directory=True)
    shutil.copyfile(FIXTURE, prepared.final_save_path)
    with pytest.raises(FinalResultError, match="path mismatch"):
        asyncio.run(FinalResultProcessor()(prepared, _progress(prepared, tmp_path), _config()))


def test_parser_child_is_reaped_on_cancellation(tmp_path: Path, prepared, monkeypatch) -> None:
    import app.simulation.openttd.final_result as final_result

    shutil.copyfile(FIXTURE, prepared.final_save_path)
    original_spawn = asyncio.create_subprocess_exec
    child_holder = []

    async def slow_child(*_args, **_kwargs):
        child = await original_spawn(
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        child_holder.append(child)
        return child

    monkeypatch.setattr(final_result.asyncio, "create_subprocess_exec", slow_child)

    async def scenario() -> None:
        task = asyncio.create_task(
            FinalResultProcessor()(prepared, _progress(prepared, tmp_path), _config())
        )
        while not child_holder:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert child_holder[0].returncode is not None

    asyncio.run(scenario())
