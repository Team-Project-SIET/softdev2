"""Isolated preparation lifecycle; runtime injection never implicitly launches OpenTTD."""

import os
import shutil
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, Protocol

from app.planning.domain import Contract, Digest, NonNegativeInt
from app.planning.preparation.canonical import preparation_bytes
from app.planning.preparation.domain import (
    PreparationBundle,
    PreparationRequest,
    SupportedWorldProfile,
)
from app.planning.preparation.failures import PreparationError, fail
from app.planning.preparation.failures import PreparationFailureCode as Code
from app.planning.preparation.probe import (
    MAX_FRAME_BYTES,
    MAX_STREAM_BYTES,
    PROBE_DIRECTORY,
    parse_extraction,
    probe_package_hash,
)
from app.planning.preparation.projection import prepare_world
from app.planning.realized import ArtifactReference
from app.planning.transport import _literal


class PreparationWorldDescriptor(Contract):
    """Pinned generated-world receipt supplied by the preparation runtime adapter.

    Pins/seed/NewGRF absence come from isolated generation, not a guessed save.
    The GameScript independently checks dimensions, climate, date and companies.
    """

    origin: Literal["preparation-compatible-generation-v1"] = "preparation-compatible-generation-v1"
    profile: SupportedWorldProfile
    seed: NonNegativeInt
    company_id: NonNegativeInt


class PreparationSession(Protocol):
    def collect(self) -> Iterable[str]: ...
    def prepared_save(self) -> Path: ...


class PreparationRuntime(Protocol):
    """Caller owns separately authorized real launch; ordinary callers inject a fake.

    start must load the staged compatible world with the probe, pause before
    extraction, and retain the prepared save after terminal completion. close must
    stop/reap any owned process and release resources even when start raised.
    No evaluation, Admin protocol, or P07 metrics belong to this seam.
    """

    def start(self, workspace: Path, source_save: Path, config: dict) -> PreparationSession: ...
    def close(self) -> None: ...


class PreparationArtifactIndex(Contract):
    schema_version: Literal[1] = 1
    scenario_hash: Digest
    manifest_hash: Digest
    provenance_hash: Digest
    artifacts: tuple[ArtifactReference, ...]


class RetainedPreparation(Contract):
    bundle: PreparationBundle
    artifacts: PreparationArtifactIndex


def _retain(data: bytes, directory: Path, name: str) -> ArtifactReference:
    with (directory / name).open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    (directory / name).chmod(0o444)
    return ArtifactReference(sha256=sha256(data).hexdigest(), reference=name)


def prepare_with_runtime(
    request: PreparationRequest,
    source_save: Path,
    descriptor: PreparationWorldDescriptor,
    runtime: PreparationRuntime,
    *,
    workspace_root: Path,
    output_directory: Path,
) -> RetainedPreparation:
    """Cleanup precedes atomic publication. A failed extraction leaves no accepted directory."""
    source_identity = request.expected_source_save_digest
    if output_directory.exists():
        fail(
            Code.INVALID_PREPARATION_OUTPUT,
            "retention",
            source_identity,
            "preparation output directory already exists",
        )
    try:
        request = PreparationRequest.model_validate_json(request.model_dump_json())
        descriptor = PreparationWorldDescriptor.model_validate_json(descriptor.model_dump_json())
        source_data = source_save.read_bytes()
        if sha256(source_data).hexdigest() != source_identity:
            fail(
                Code.WORLD_CHANGED_DURING_PREPARATION,
                "lifecycle",
                source_identity,
                "source save differs from preparation request",
            )
        workspace_root.mkdir(parents=True, exist_ok=True)
        output_directory.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="p08-", dir=workspace_root) as workspace_name:
            workspace = Path(workspace_name)
            staged_source = workspace / "source.sav"
            staged_source.write_bytes(source_data)
            staged_source.chmod(0o444)
            package = workspace / "game" / "P08Preparation"
            package.mkdir(parents=True)
            staged_package_digest = probe_package_hash()
            for name in ("info.nut", "main.nut"):
                shutil.copyfile(PROBE_DIRECTORY / name, package / name)
            config = {
                "profile": descriptor.profile.model_dump(mode="json"),
                "seed": descriptor.seed,
                "company_id": descriptor.company_id,
                "source_save_digest": source_identity,
                "limits": request.limits.model_dump(mode="json"),
            }
            request_nut = ("::P08_REQUEST <- " + _literal(config) + ";\n").encode()
            (package / "request.nut").write_bytes(request_nut)
            try:
                session = runtime.start(workspace, staged_source, config)
                evidence_path = workspace / "extraction.log"

                def collect():
                    total = 0
                    with evidence_path.open("xb") as evidence:
                        for line in session.collect():
                            data = (line.rstrip("\r\n") + "\n").encode()
                            total += len(data)
                            if len(data) > MAX_FRAME_BYTES or total > MAX_STREAM_BYTES:
                                fail(
                                    Code.CANDIDATE_LIMIT_EXCEEDED,
                                    "lifecycle",
                                    source_identity,
                                    "runtime evidence exceeds transport bound",
                                )
                            evidence.write(data)
                            yield line

                # Saving is completed by the session before exposing its save path.
                prepared_path = session.prepared_save()
                if (
                    prepared_path.is_symlink()
                    or not prepared_path.is_file()
                    or not prepared_path.resolve().is_relative_to(workspace.resolve())
                ):
                    fail(
                        Code.EXTRACTION_INCOMPLETE,
                        "lifecycle",
                        source_identity,
                        "prepared save is outside owned preparation workspace",
                    )
                prepared_data = prepared_path.read_bytes()
                prepared_digest = sha256(prepared_data).hexdigest()
                snapshot = parse_extraction(collect(), request, prepared_digest)
                if (
                    sha256(source_save.read_bytes()).hexdigest() != source_identity
                    or sha256(staged_source.read_bytes()).hexdigest() != source_identity
                    or sha256(prepared_path.read_bytes()).hexdigest() != prepared_digest
                ):
                    fail(
                        Code.WORLD_CHANGED_DURING_PREPARATION,
                        "lifecycle",
                        source_identity,
                        "source or prepared save changed while collecting evidence",
                    )
                if (
                    snapshot.profile != descriptor.profile
                    or snapshot.seed != descriptor.seed
                    or snapshot.company_id != descriptor.company_id
                ):
                    fail(
                        Code.CATALOG_IDENTITY_MISMATCH,
                        "lifecycle",
                        source_identity,
                        "extracted world differs from pinned generation receipt",
                    )
                bundle = prepare_world(request, snapshot)
            finally:
                runtime.close()
            if (
                sha256(source_save.read_bytes()).hexdigest() != source_identity
                or sha256(staged_source.read_bytes()).hexdigest() != source_identity
                or sha256(prepared_path.read_bytes()).hexdigest() != prepared_digest
            ):
                fail(
                    Code.WORLD_CHANGED_DURING_PREPARATION,
                    "cleanup",
                    source_identity,
                    "source or prepared save changed during runtime cleanup",
                )
            if staged_package_digest != bundle.provenance.probe_package_hash:
                fail(
                    Code.CATALOG_IDENTITY_MISMATCH,
                    "probe-package",
                    source_identity,
                    "probe package changed during preparation",
                )
            evidence_data = evidence_path.read_bytes()
            staged_package = {
                name: (package / name).read_bytes() for name in ("info.nut", "main.nut")
            }
            if any(
                staged_package[name] != (PROBE_DIRECTORY / name).read_bytes()
                for name in staged_package
            ):
                fail(
                    Code.CATALOG_IDENTITY_MISMATCH,
                    "probe-package",
                    source_identity,
                    "staged probe differs from pinned package",
                )
        # Workspace cleanup has now completed. Publication cannot precede a cleanup failure.
        # Artifacts are linked through existing P07 ArtifactReference and scenario hashes.
        # All writes occur in an unpublished directory on the destination filesystem.
        with TemporaryDirectory(prefix=".p08-retain-", dir=output_directory.parent) as retained:
            directory = Path(retained)
            rows = []
            for name, model in (
                ("request", bundle.request),
                ("snapshot", bundle.snapshot),
                ("report", bundle.report),
                ("scenario", bundle.scenario),
                ("manifest", bundle.manifest),
                ("bindings", bundle.bindings),
                ("provenance", bundle.provenance),
            ):
                rows.append(_retain(preparation_bytes(model), directory, f"p08-{name}.json"))
            for name, data in (
                ("p08-source.sav", source_data),
                ("p08-prepared.sav", prepared_data),
                ("p08-extraction.log", evidence_data),
                ("p08-probe-request.nut", request_nut),
                ("p08-probe-info.nut", staged_package["info.nut"]),
                ("p08-probe-main.nut", staged_package["main.nut"]),
            ):
                rows.append(_retain(data, directory, name))
            index = PreparationArtifactIndex(
                scenario_hash=bundle.provenance.scenario_hash,
                manifest_hash=bundle.provenance.manifest_hash,
                provenance_hash=bundle.provenance_hash,
                artifacts=tuple(rows),
            )
            _retain(preparation_bytes(index), directory, "p08-artifacts.json")
            if output_directory.exists():
                fail(
                    Code.INVALID_PREPARATION_OUTPUT,
                    "retention",
                    source_identity,
                    "preparation output directory already exists",
                )
            directory.rename(output_directory)
        return RetainedPreparation(bundle=bundle, artifacts=index)
    except PreparationError:
        raise
    except OSError, RuntimeError, ValueError, TypeError:
        fail(
            Code.EXTRACTION_INCOMPLETE,
            "lifecycle",
            source_identity,
            "preparation runtime/staging/cleanup failed",
        )
        raise AssertionError("unreachable")
