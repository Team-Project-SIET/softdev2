"""CONTROLLED paired data retention; external digest authority, no native proof."""

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest
from app.simulation.openttd.supplemental_planning_facts import Region
from app.simulation.openttd.terrain_pagination import PaginationBudget
from app.simulation.openttd.terrain_sweeps import (
    TerrainSweepContext,
    TerrainTwoSweep,
    TwoSweepBudget,
    VerifiedTerrainPair,
)
from app.simulation.openttd.tile_facts import TileFactsExchange, TileFactsReceipt, TileFactsRequest

SCHEMA = "terrain-paired-evidence-v1"
MAX_PACKAGE_BYTES = 1048576


class Context(Contract):
    acquisition_id: str
    world_fingerprint: Digest
    map_width: int
    map_height: int
    region: Region

    def runtime(self) -> TerrainSweepContext:
        return TerrainSweepContext(**self.model_dump(exclude={"region"}), region=self.region)


class SweepBudget(Contract):
    max_pages: int
    page_request_bytes: int
    page_response_bytes: int
    max_request_bytes: int
    max_response_bytes: int
    max_operations: int


class CombinedBudget(Contract):
    max_pages: int
    max_request_bytes: int
    max_response_bytes: int
    max_operations: int


class Budgets(Contract):
    per_sweep: SweepBudget
    combined: CombinedBudget


class SweepIdentity(Contract):
    acquisition_id: str
    ordinal: int


class PageIndex(Contract):
    ordinal: int
    request_id: str
    cursor: int
    tile_ids: tuple[int, ...]
    request_artifact: str
    response_artifact: str
    exchange_artifact: str


class SweepIndex(Contract):
    identity: SweepIdentity
    pages: tuple[PageIndex, ...]


class Artifact(Contract):
    path: str
    byte_length: int
    sha256: Digest


class Descriptor(Contract):
    schema_id: Literal["terrain-paired-evidence-v1"] = Field(alias="schema")
    version: Literal[1]
    mode: Literal["CONTROLLED"]
    status: Literal["COMPLETE"]
    context: Context
    budgets: Budgets
    sweeps: tuple[SweepIndex, SweepIndex]
    artifacts: tuple[Artifact, ...]
    failure: None


class Receipt(Contract):
    request_id: str
    request_payload_sha256: Digest
    response_payload_sha256: Digest


class ExchangeRecord(Contract):
    observed_context: Context
    receipt: Receipt
    ordered_sequence: tuple[str, ...]
    protocol_operations: int
    requests_sent: int
    matching_responses: int
    retries: int


class PageMetadata(Contract):
    request_id: str
    cursor: int
    tile_ids: tuple[int, ...]
    request_sha256: Digest
    response_sha256: Digest
    request_bytes: int
    response_bytes: int
    query_operations: int


class SweepMetadata(Contract):
    complete: bool
    map: tuple[int, int]
    mode: str
    region: tuple[int, int, int, int]
    tile_count: int
    request_bytes: int
    response_bytes: int
    query_operations: int
    rows_sha256: Digest
    pages: tuple[PageMetadata, ...]
    expected_pages: tuple[str, ...]
    received_pages: tuple[str, ...]


class PairMetadata(Contract):
    mode: str
    world_fingerprint: Digest
    acquisition_id: str
    complete: bool
    sweeps: tuple[SweepMetadata, SweepMetadata]
    pages: int
    request_bytes: int
    response_bytes: int
    query_operations: int


class DatasetIdentity(Contract):
    policy: Literal["terrain-paired-dataset-v1"]
    context: Context
    rows_sha256: Digest


class Summary(Contract):
    dataset_identity: Digest
    pair_metadata: PairMetadata


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _parse[Model: Contract](raw: bytes, model: type[Model]) -> Model:
    json.loads(raw, object_pairs_hook=_duplicates)
    value = model.model_validate_json(raw)
    encoded = _descriptor_bytes(value) if isinstance(value, Descriptor) else canonical_bytes(value)
    if encoded != raw:
        raise ValueError("Noncanonical metadata bytes")
    return value


def _descriptor_bytes(value: Descriptor) -> bytes:
    # The shared canonical encoder uses Python field names, not Pydantic aliases.
    fields = json.loads(canonical_bytes(value))
    fields["schema"] = fields.pop("schema_id")
    return json.dumps(
        fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _model[Model: Contract](value: object, model: type[Model]) -> Model:
    # JSON mode admits arrays as immutable tuples while retaining strict scalar types.
    return model.model_validate_json(json.dumps(value, allow_nan=False))


def _summary(pair: VerifiedTerrainPair, context: Context) -> Summary:
    identity = DatasetIdentity(
        policy="terrain-paired-dataset-v1",
        context=context,
        rows_sha256=pair.sweeps[0].metadata["rows_sha256"],
    )
    return Summary(
        dataset_identity=_sha(canonical_bytes(identity)),
        pair_metadata=_model(pair.metadata, PairMetadata),
    )


def _page(q: TileFactsRequest, sweep: int, ordinal: int, width: int) -> PageIndex:
    root = f"pages/s{sweep}/p{ordinal:03d}"
    region = q.region
    ids = tuple(
        (region.y + i // region.width) * width + region.x + i % region.width
        for i in range(q.cursor, min(q.cursor + 5, region.width * region.height))
    )
    return PageIndex(
        ordinal=ordinal,
        request_id=q.request_id,
        cursor=q.cursor,
        tile_ids=ids,
        request_artifact=root + "/request.json",
        response_artifact=root + "/response.json",
        exchange_artifact=root + "/exchange.json",
    )


def _plans(pair: TerrainTwoSweep, context: Context) -> tuple[SweepIndex, SweepIndex]:
    # Both plans share geometry, differing only in the explicit sweep request prefix.
    first = pair.requests
    result = []
    for sweep in (1, 2):
        pages = tuple(
            _page(
                TileFactsRequest(f"{context.acquisition_id}-s{sweep}-p{i:03d}", q.region, q.cursor),
                sweep,
                i,
                context.map_width,
            )
            for i, q in enumerate(first, 1)
        )
        result.append(
            SweepIndex(
                identity=SweepIdentity(acquisition_id=context.acquisition_id, ordinal=sweep),
                pages=pages,
            )
        )
    return result[0], result[1]


def _limits(sweeps: tuple[SweepIndex, SweepIndex]) -> dict[str, int]:
    result = {"summary.json": 65536, "package.json": 131072, "artifact-manifest.sha256": 65536}
    for sweep in sweeps:
        for page in sweep.pages:
            result[page.request_artifact] = 159
            result[page.response_artifact] = 508
            result[page.exchange_artifact] = 4096
    return result


def _manifest(content: dict[str, bytes]) -> bytes:
    return "".join(
        f"{_sha(raw)}  {path}\n"
        for path, raw in sorted(content.items())
        if path != "artifact-manifest.sha256"
    ).encode("ascii")


def _root(directory: Path) -> int:
    absolute = directory.absolute()
    if ".." in absolute.parts or any(p.is_symlink() for p in (absolute, *absolute.parents)):
        raise ValueError("inventory: Aliased or traversing package root")
    try:
        return os.open(absolute, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise ValueError("inventory: Unreadable package root") from error


def _read(root: int, path: str, limit: int) -> bytes:
    fd = os.dup(root)
    try:
        parts = path.split("/")
        for part in parts[:-1]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        file = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
                raise ValueError("inventory: Invalid file type, alias or size")
            raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise ValueError("bytes: Artifact read ceiling")
            return raw
    finally:
        os.close(fd)


def _inventory(root: int, files: set[str]) -> None:
    directories = {
        parent.as_posix() for path in files for parent in Path(path).parents if str(parent) != "."
    }
    seen_files, seen_directories, inodes = set(), set(), set()

    def visit(fd: int, prefix: str) -> None:
        for name in os.listdir(fd):
            path = prefix + name
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            identity = info.st_dev, info.st_ino
            if identity in inodes:
                raise ValueError("inventory: Aliased artifact identity")
            inodes.add(identity)
            if stat.S_ISDIR(info.st_mode) and path in directories:
                seen_directories.add(path)
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    visit(child, path + "/")
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode) and path in files and info.st_nlink == 1:
                seen_files.add(path)
            else:
                raise ValueError("inventory: Unexpected or invalid artifact")

    visit(root, "")
    if seen_files != files or seen_directories != directories:
        raise ValueError("inventory: Missing required artifact")


def write_paired_package(pair: VerifiedTerrainPair, directory: Path) -> str:
    """Write a new complete package; returned digest is not independent authority."""
    pair.verify()
    context = Context(**asdict(pair.context))
    budgets = Budgets(
        per_sweep=_model(asdict(pair.per_sweep_budget), SweepBudget),
        combined=_model(asdict(pair.combined_budget), CombinedBudget),
    )
    replay = TerrainTwoSweep(
        pair.context, per_sweep_budget=pair.per_sweep_budget, combined_budget=pair.combined_budget
    )
    sweeps = _plans(replay, context)
    content = {"summary.json": canonical_bytes(_summary(pair, context))}
    for index, sweep in enumerate(sweeps):
        for page, exchange in zip(sweep.pages, pair.sweeps[index].exchanges, strict=True):
            record = ExchangeRecord(
                observed_context=context,
                receipt=_model(asdict(exchange.receipt), Receipt),
                ordered_sequence=exchange.ordered_sequence,
                protocol_operations=exchange.protocol_operations,
                requests_sent=exchange.requests_sent,
                matching_responses=exchange.matching_responses,
                retries=exchange.retries,
            )
            content[page.request_artifact] = exchange.request_payload
            content[page.response_artifact] = exchange.response_payload
            content[page.exchange_artifact] = canonical_bytes(record)
    descriptor = Descriptor(
        schema=SCHEMA,
        version=1,
        mode="CONTROLLED",
        status="COMPLETE",
        context=context,
        budgets=budgets,
        sweeps=sweeps,
        artifacts=tuple(
            Artifact(path=p, byte_length=len(raw), sha256=_sha(raw))
            for p, raw in sorted(content.items())
        ),
        failure=None,
    )
    content["package.json"] = _descriptor_bytes(descriptor)
    content["artifact-manifest.sha256"] = _manifest(content)
    limits = _limits(sweeps)
    if (
        any(len(raw) > limits[p] for p, raw in content.items())
        or sum(map(len, content.values())) > MAX_PACKAGE_BYTES
    ):
        raise ValueError("bytes: Package write ceiling")
    directory.mkdir(exist_ok=True)
    root = _root(directory)
    try:
        if os.listdir(root):
            raise ValueError("inventory: Output directory must be empty")
        for path, raw in content.items():
            target = directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
    finally:
        os.close(root)
    return _sha(content["package.json"])


def verify_paired_package(
    directory: Path, *, expected_descriptor_sha256: str
) -> VerifiedTerrainPair:
    """Verify a quiescent package against caller-pinned authority and replay all pages."""
    if not isinstance(expected_descriptor_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_descriptor_sha256
    ):
        raise ValueError("commitment: Missing or invalid external descriptor digest")
    root = _root(directory)
    try:
        raw = _read(root, "package.json", 131072)
        if _sha(raw) != expected_descriptor_sha256:
            raise ValueError("commitment: Descriptor digest mismatch")
        try:
            descriptor = _parse(raw, Descriptor)
        except ValueError as error:
            raise ValueError(
                "schema: Invalid descriptor or unsupported version/mode/status"
            ) from error
        try:
            replay = TerrainTwoSweep(
                descriptor.context.runtime(),
                per_sweep_budget=PaginationBudget(**descriptor.budgets.per_sweep.model_dump()),
                combined_budget=TwoSweepBudget(**descriptor.budgets.combined.model_dump()),
            )
        except ValueError as error:
            raise ValueError("replay: Invalid context or budgets") from error
        plans = _plans(replay, descriptor.context)
        if descriptor.sweeps != plans:
            raise ValueError("inventory: Page identity or coverage index mismatch")
        limits = _limits(plans)
        expected_artifacts = sorted(set(limits) - {"package.json", "artifact-manifest.sha256"})
        if [a.path for a in descriptor.artifacts] != expected_artifacts:
            raise ValueError("inventory: Artifact commitment identities mismatch")
        _inventory(root, set(limits))
        content = {"package.json": raw}
        for artifact in descriptor.artifacts:
            payload = _read(root, artifact.path, limits[artifact.path])
            if len(payload) != artifact.byte_length or _sha(payload) != artifact.sha256:
                raise ValueError("bytes: Retained artifact commitment mismatch")
            content[artifact.path] = payload
        manifest = _read(root, "artifact-manifest.sha256", 65536)
        if sum(map(len, content.values())) + len(manifest) > MAX_PACKAGE_BYTES:
            raise ValueError("bytes: Package read ceiling")
        if manifest != _manifest(content):
            raise ValueError("bytes: Manifest mismatch")
        for sweep in plans:
            for page in sweep.pages:
                try:
                    record = _parse(content[page.exchange_artifact], ExchangeRecord)
                    exchange = TileFactsExchange(
                        content[page.request_artifact],
                        content[page.response_artifact],
                        TileFactsReceipt(**record.receipt.model_dump()),
                        record.ordered_sequence,
                        record.protocol_operations,
                        record.requests_sent,
                        record.matching_responses,
                        record.retries,
                    )
                    exchange.validate()
                except ValueError as error:
                    raise ValueError("exchange: Invalid retained exchange") from error
                try:
                    replay.accept(
                        (sweep.identity.acquisition_id, sweep.identity.ordinal),
                        record.observed_context.runtime(),
                        exchange,
                    )
                except ValueError as error:
                    raise ValueError("replay: Page admission rejected") from error
            try:
                replay.complete_sweep()
            except ValueError as error:
                raise ValueError("replay: Sweep completion rejected") from error
        result = replay.finish()
        try:
            summary = _parse(content["summary.json"], Summary)
        except ValueError as error:
            raise ValueError("summary: Invalid summary schema") from error
        if summary != _summary(result, descriptor.context):
            raise ValueError("summary: Replayed outcome differs from recorded summary")
        return result
    except OSError as error:
        raise ValueError("inventory: Unreadable retained package") from error
    finally:
        os.close(root)
