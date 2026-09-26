"""Interpret the explicit save from an owned live world using public OpenTTDLab."""

import asyncio
import configparser
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from app.experiments.domain import (
    ExperimentConfig,
    LiveExecutionSummary,
    SimulationResult,
    TelemetryStatus,
)
from app.simulation.openttd.live_launch import PreparedLiveRuntime
from app.simulation.openttd.runner import parse_result_row, write_parsed_artifact

if TYPE_CHECKING:
    from app.simulation.openttd.live_runner import LiveRunProgress


class FinalResultError(RuntimeError):
    """Sanitized failure to produce the canonical final result."""


class _SaveLocation(Protocol):
    @property
    def workspace(self) -> Path: ...

    @property
    def final_save_path(self) -> Path: ...


class _ProgressInfo(Protocol):
    @property
    def run_id(self) -> int: ...

    @property
    def artifact_dir(self) -> Path: ...

    @property
    def target_day(self) -> int: ...

    @property
    def last_observed_day(self) -> int: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_owned_save(prepared: _SaveLocation) -> Path:
    path = prepared.final_save_path
    if path.parent != prepared.workspace / "save" or path.suffix != ".sav":
        raise FinalResultError("final save path mismatch")
    try:
        directory = path.parent.lstat()
        metadata = path.lstat()
    except OSError:
        raise FinalResultError("requested final save missing") from None
    if not stat.S_ISDIR(directory.st_mode) or path.parent.is_symlink():
        raise FinalResultError("final save path mismatch")
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise FinalResultError("requested final save is not a regular file")
    if not path.resolve().is_relative_to(prepared.workspace.resolve()):
        raise FinalResultError("final save path mismatch")
    return path


def _publish_raw(prepared: _SaveLocation, destination: Path) -> None:
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        directory_fd = os.open(
            prepared.workspace / "save", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        try:
            source_fd = os.open(
                prepared.final_save_path.name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            with os.fdopen(source_fd, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise FinalResultError("requested final save is not a regular file")
                with temporary_path.open("wb") as target:
                    shutil.copyfileobj(source, target, length=65536)
        finally:
            os.close(directory_fd)
        os.link(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def _validate_source_identity(chunks: dict[str, Any], config: ExperimentConfig) -> None:
    """Check savegame identity fields rather than trusting labels filled by this adapter."""
    try:
        revision_bytes = chunks["GLOG"]["0"]["action"][0]["revision"][0]["revision.text"]
        revision = bytes(revision_bytes).split(b"\0", 1)[0].decode("ascii")
        maps = chunks["MAPS"]["0"]
        scenario = configparser.ConfigParser(interpolation=None)
        scenario.read_string(config.scenario.openttd_config)
        width = 1 << scenario.getint("game_creation", "map_x", fallback=8)
        height = 1 << scenario.getint("game_creation", "map_y", fallback=8)
        if revision != config.openttd_version:
            raise FinalResultError("final save OpenTTD revision mismatch")
        if maps["dim_x"] != width or maps["dim_y"] != height:
            raise FinalResultError("final save map identity mismatch")
        if chunks["AIPL"]["0"]["name"] != config.ai.name:
            raise FinalResultError("final save AI identity mismatch")
    except FinalResultError:
        raise
    except KeyError, IndexError, TypeError, ValueError, configparser.Error:
        raise FinalResultError("final save provenance could not be verified") from None


class FinalResultProcessor:
    """Parse one acknowledged final save; never launch or control OpenTTD."""

    def process(
        self,
        prepared: _SaveLocation,
        progress: _ProgressInfo,
        config: ExperimentConfig,
    ) -> SimulationResult:
        from openttdlab import parse_savegame

        _require_owned_save(prepared)
        raw_path = progress.artifact_dir / f"experiment-{progress.run_id}.sav"
        try:
            progress.artifact_dir.mkdir(parents=True, exist_ok=True)
            _publish_raw(prepared, raw_path)
            raw_hash = _sha256(raw_path)
        except Exception:
            raise FinalResultError("final raw artifact could not be written") from None
        try:
            with raw_path.open("rb") as source:
                game: dict[str, Any] = parse_savegame(iter(lambda: source.read(65536), b""))
            chunks = {tag: chunk["records"] for tag, chunk in game["chunks"].items()}
            if "0" not in chunks["PLYR"]:
                raise FinalResultError("required company 0 missing from final save")
            game_day = chunks["DATE"]["0"]["date"]
            if game_day < progress.target_day:
                raise FinalResultError("final save predates requested target")
            if game_day < progress.last_observed_day:
                raise FinalResultError("final save predates last observed date")
            _validate_source_identity(chunks, config)
            final_date = date(1, 1, 1) + timedelta(days=game_day - 366)
            row = {
                "openttd_version": config.openttd_version,
                "opengfx_version": config.opengfx_version,
                "savegame_version": game["savegame_version"],
                "experiment": {"seed": config.seed, "days": config.duration_days},
                "date": final_date,
                "error": False,
                "output": None,
                "chunks": chunks,
            }
            result = parse_result_row(row, config)
        except FinalResultError:
            raise
        except Exception:
            raise FinalResultError("final save could not be parsed") from None

        try:
            parsed_path = write_parsed_artifact(
                row,
                config,
                result,
                run_id=progress.run_id,
                artifact_dir=progress.artifact_dir,
                replace_existing=False,
            )
            parsed_hash = _sha256(parsed_path)
        except Exception:
            raise FinalResultError("parsed artifact could not be written") from None
        summary = LiveExecutionSummary(
            telemetry_status=TelemetryStatus.INCOMPLETE,
            actual_final_day=game_day,
            raw_save_reference=str(raw_path.resolve()),
            raw_save_sha256=raw_hash,
            parsed_artifact_reference=str(parsed_path.resolve()),
            parsed_artifact_sha256=parsed_hash,
        )
        return result.model_copy(
            update={
                "raw_artifact_reference": str(parsed_path.resolve()),
                "live_summary": summary,
            }
        )

    async def __call__(
        self,
        prepared: PreparedLiveRuntime,
        progress: LiveRunProgress,
        config: ExperimentConfig,
    ) -> SimulationResult:
        _require_owned_save(prepared)
        request = {
            "workspace": str(prepared.workspace),
            "save_path": str(prepared.final_save_path),
            "artifact_dir": str(progress.artifact_dir),
            "run_id": progress.run_id,
            "process_id": progress.process_id,
            "configured_start_day": progress.configured_start_day,
            "observed_start_day": progress.observed_start_day,
            "target_day": progress.target_day,
            "last_observed_day": progress.last_observed_day,
            "config": config.model_dump(mode="json"),
        }
        try:
            child = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.simulation.openttd.final_result_worker",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            raise FinalResultError("final parser could not be started") from None
        try:
            output, _ = await child.communicate(json.dumps(request).encode())
            if child.returncode != 0:
                try:
                    reason = json.loads(output)["error"]
                except ValueError, KeyError, TypeError:
                    reason = "final save could not be parsed"
                raise FinalResultError(reason)
            try:
                return SimulationResult.model_validate_json(output)
            except Exception:
                raise FinalResultError("final parser returned an invalid result") from None
        finally:
            if child.returncode is None:
                child.kill()
                await child.wait()
