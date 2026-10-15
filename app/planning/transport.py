"""Deterministic, data-only transport into an isolated OpenTTD AI workspace."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.planning.execution import ExecutionBindings

from app.planning.domain import ExecutionPlan, PlanningScenario
from app.planning.serialization import plan_artifact_bytes, verify_plan_hash
from app.planning.validation import validate_execution_plan

TRANSPORT_VERSION = 1
GENERATOR_VERSION = "1"
AI_NAME = "P03ThinExecutor"
AI_VERSION = 1
MAX_MODULE_BYTES = 1024 * 1024


class PlanTransportError(ValueError):
    """A validated plan could not be safely staged for the thin AI."""


@dataclass(frozen=True)
class MaterializedPlan:
    plan_hash: str
    world_fingerprint: str
    artifact_sha256: str
    module_sha256: str
    package_sha256: str
    artifact_path: Path
    module_path: Path
    ai_directory: Path


def _literal(value: object, depth: int = 0) -> str:
    if depth > 48:
        raise PlanTransportError("transport nesting limit exceeded")
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # JSON escapes quotes, backslashes and controls; ASCII escapes keep the
        # generated Squirrel source independent of source-file encoding.
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, list):
        return "[" + ",".join(_literal(item, depth + 1) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise PlanTransportError("transport keys must be strings")
        return (
            "{"
            + ",".join(
                f"[{_literal(key)}]={_literal(value[key], depth + 1)}" for key in sorted(value)
            )
            + "}"
        )
    raise PlanTransportError("transport value is not a JSON literal")


def transport_bytes(
    plan: ExecutionPlan,
    scenario: PlanningScenario,
    declared_hash: str,
    execution: ExecutionBindings | None = None,
) -> bytes:
    """Validate before rendering an immutable schema-v1 Squirrel data module."""
    verify_plan_hash(plan, declared_hash)
    validate_execution_plan(plan, scenario)
    if scenario.openttd_version != "13.4" or (
        scenario.base_set_name,
        scenario.base_set_version,
    ) != ("OpenGFX", "7.1"):
        raise PlanTransportError("unsupported pinned world runtime")
    artifact = json.loads(plan_artifact_bytes(plan))
    sites = [
        {
            "location_id": site.location_id,
            "x": site.tile.x,
            "y": site.tile.y,
            "world_kind": site.world_kind,
            "world_id": site.world_id,
        }
        for site in scenario.world_manifest.resolved_sites
    ]
    payload = {
        "transport_version": TRANSPORT_VERSION,
        "generator_version": GENERATOR_VERSION,
        "plan_hash": declared_hash,
        "schema_version": plan.schema_version,
        "scenario_id": scenario.scenario_id,
        "scenario_version": scenario.scenario_version,
        "world_fingerprint": scenario.world_fingerprint,
        "world_source_digest": scenario.world_manifest.source_digest,
        "world_width": scenario.width_tiles,
        "world_height": scenario.height_tiles,
        "world_seed": scenario.seed,
        "sites": sites,
        "route_ids": [route["route_id"] for route in artifact["plan"]["routes"]],
        "fleet_group_ids": [
            group["fleet_group_id"] for group in artifact["plan"]["fleet"]["groups"]
        ],
        "infrastructure_action_ids": [
            action.construction_id for action in plan.infrastructure.actions
        ],
        "artifact": artifact,
    }
    if execution is not None:
        from app.planning.execution import execution_payload

        payload["execution"] = execution_payload(plan, scenario, execution)
    receipt_length = (
        sum(
            len(identifier) + 1
            for group in (
                payload["route_ids"],
                payload["fleet_group_ids"],
                payload["infrastructure_action_ids"],
            )
            for identifier in group
        )
        + len(declared_hash)
        + len(scenario.world_fingerprint)
        + len(scenario.scenario_id)
        + len(scenario.scenario_version)
        + 128
    )
    if receipt_length > 4096:
        raise PlanTransportError("setup evidence would exceed v1 size limit")
    result = ("::P03_TRANSPORT <- " + _literal(payload) + ";\n").encode("ascii")
    if len(result) > MAX_MODULE_BYTES:
        raise PlanTransportError("transport module exceeds v1 size limit")
    return result


def verify_world_source(scenario: PlanningScenario, world_source: Path) -> None:
    """Bind a prepared save/scenario artifact to the manifest before staging."""
    if world_source.is_symlink() or not world_source.is_file():
        raise PlanTransportError("prepared world source must be a regular file")
    digest = hashlib.sha256()
    with world_source.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != scenario.world_manifest.source_digest:
        raise PlanTransportError("prepared world source digest mismatch")


def verify_staged_package(receipt: MaterializedPlan) -> None:
    """Detect edits or stale files between materialization and process launch."""
    ai_dir = receipt.ai_directory
    expected = {"info.nut", "main.nut", "plan.nut"}
    if ai_dir.is_symlink() or {path.name for path in ai_dir.iterdir()} != expected:
        raise PlanTransportError("thin AI package shape changed")
    contents: list[bytes] = []
    for name in ("info.nut", "main.nut", "plan.nut"):
        path = ai_dir / name
        if path.is_symlink() or not path.is_file():
            raise PlanTransportError("thin AI package file changed")
        contents.append(path.read_bytes())
    if (
        hashlib.sha256(contents[2]).hexdigest() != receipt.module_sha256
        or hashlib.sha256(b"".join(contents)).hexdigest() != receipt.package_sha256
    ):
        raise PlanTransportError("thin AI package digest changed")
    artifact = receipt.artifact_path
    if (
        artifact.is_symlink()
        or not artifact.is_file()
        or hashlib.sha256(artifact.read_bytes()).hexdigest() != receipt.artifact_sha256
    ):
        raise PlanTransportError("retained plan artifact changed")


def _write_exclusive(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def materialize_plan(
    plan: ExecutionPlan,
    scenario: PlanningScenario,
    declared_hash: str,
    workspace: Path,
    world_source: Path,
    execution: ExecutionBindings | None = None,
) -> MaterializedPlan:
    """Create one package in a new, owned 0700 workspace; never overwrite."""
    verify_world_source(scenario, world_source)
    module = transport_bytes(plan, scenario, declared_hash, execution)
    artifact = plan_artifact_bytes(plan)
    if (
        ".." in workspace.parts
        or any(part.is_symlink() for part in (workspace, *workspace.parents))
        or not workspace.is_dir()
    ):
        raise PlanTransportError("workspace must be an existing directory")
    workspace_stat = workspace.stat()
    if workspace_stat.st_uid != os.getuid() or stat.S_IMODE(workspace_stat.st_mode) != 0o700:
        raise PlanTransportError("workspace must be privately owned")
    if any(workspace.iterdir()):
        raise PlanTransportError("workspace must be fresh and empty")
    ai_root = workspace / "ai"
    ai_dir = ai_root / AI_NAME
    ai_root.mkdir(mode=0o700)
    ai_dir.mkdir(mode=0o700)
    sources = Path(__file__).parent / "thin_ai"
    info = (sources / "info.nut").read_bytes()
    main = (sources / "main.nut").read_bytes()
    if execution is not None:
        main += b"\n" + (sources / "execution.nut").read_bytes()
    _write_exclusive(workspace / "execution-plan.json", artifact)
    _write_exclusive(ai_dir / "info.nut", info)
    _write_exclusive(ai_dir / "main.nut", main)
    module_path = ai_dir / "plan.nut"
    _write_exclusive(module_path, module)
    package_digest = hashlib.sha256(info + main + module).hexdigest()
    return MaterializedPlan(
        plan_hash=declared_hash,
        world_fingerprint=scenario.world_fingerprint,
        artifact_sha256=hashlib.sha256(artifact).hexdigest(),
        module_sha256=hashlib.sha256(module).hexdigest(),
        package_sha256=package_digest,
        artifact_path=workspace / "execution-plan.json",
        module_path=module_path,
        ai_directory=ai_dir,
    )
