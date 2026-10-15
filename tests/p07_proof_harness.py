"""Canonical input and package freeze for the opt-in P07 proof, never gameplay."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from app.experiments.plan_evaluation import PlanEvaluationInput
from app.planning.canonical import canonical_bytes, plan_hash
from app.planning.transport import (
    MaterializedPlan,
    transport_bytes,
    verify_staged_package,
)


def authoritative_input(raw: bytes | PlanEvaluationInput) -> PlanEvaluationInput:
    data = raw if isinstance(raw, bytes) else raw.model_dump_json().encode()
    parsed = PlanEvaluationInput.model_validate_json(data)
    serialized = canonical_bytes(parsed)
    authoritative = PlanEvaluationInput.model_validate_json(serialized)
    if canonical_bytes(authoritative) != serialized:
        raise ValueError("canonical proof input is not stable")
    return authoritative


def require_authoritative(value: PlanEvaluationInput) -> None:
    if value != PlanEvaluationInput.model_validate_json(canonical_bytes(value)):
        raise ValueError("proof input is not the authoritative canonical object graph")


@dataclass(frozen=True)
class PackageFreeze:
    input_bytes: bytes
    module_sha256: str
    package_sha256: str


def read_package(directory: Path) -> tuple[str, str]:
    if directory.is_symlink() or {p.name for p in directory.iterdir()} != {
        "info.nut",
        "main.nut",
        "plan.nut",
    }:
        raise ValueError("staged AI package shape changed")
    files = [directory / name for name in ("info.nut", "main.nut", "plan.nut")]
    if any(p.is_symlink() or not p.is_file() for p in files):
        raise ValueError("staged AI package file changed")
    contents = [p.read_bytes() for p in files]
    return sha256(contents[2]).hexdigest(), sha256(b"".join(contents)).hexdigest()


def freeze_package(value: PlanEvaluationInput, package: MaterializedPlan) -> PackageFreeze:
    require_authoritative(value)
    verify_staged_package(package)
    module = transport_bytes(value.plan, value.scenario, package.plan_hash, value.bindings)
    if module != package.module_path.read_bytes():
        raise ValueError("staged module was generated from a different input graph")
    module_hash, package_hash = read_package(package.ai_directory)
    return PackageFreeze(canonical_bytes(value), module_hash, package_hash)


def verify_frozen(value: PlanEvaluationInput, directory: Path, frozen: PackageFreeze) -> None:
    require_authoritative(value)
    if canonical_bytes(value) != frozen.input_bytes:
        raise ValueError("proof input changed after freeze")
    if read_package(directory) != (frozen.module_sha256, frozen.package_sha256):
        raise ValueError("launched package differs from frozen package")
    generated = transport_bytes(value.plan, value.scenario, plan_hash(value.plan), value.bindings)
    if sha256(generated).hexdigest() != frozen.module_sha256:
        raise ValueError("frozen module differs from authoritative proof input")
