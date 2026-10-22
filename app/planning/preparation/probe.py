"""Read-only preparation probe package identity (transport implementation follows)."""

from hashlib import sha256
from pathlib import Path
from typing import Never

PROBE_DIRECTORY = Path(__file__).with_name("probe_package")


def probe_package_hash() -> str:
    digest = sha256()
    for name in ("info.nut", "main.nut"):
        data = (PROBE_DIRECTORY / name).read_bytes()
        digest.update(name.encode() + b"\0" + len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


# Transport bounds are separate from planning limits; enforce before JSON allocation.
MAX_FRAME_BYTES = 8192
MAX_STREAM_BYTES = 64 * 1024 * 1024
MAX_CARGOS = 32
MAX_ENGINES = 256


def parse_extraction(lines, request, prepared_save_digest):
    """Validate raw wire bytes, declared counts and terminal Adler-32, then strict reparse.

    Adler-32 is the probe's wire-integrity marker, not a semantic identity. Accepted
    snapshots and every retained artifact have independent SHA-256 identities.
    """
    import json
    import zlib

    from pydantic import ValidationError

    from app.planning.preparation.canonical import authoritative
    from app.planning.preparation.domain import ExtractedWorldSnapshot
    from app.planning.preparation.failures import PreparationFailureCode as Code
    from app.planning.preparation.failures import fail
    from app.planning.preparation.projection import validate_snapshot

    source = request.expected_source_save_digest
    groups = {"tile": [], "industry": [], "cargo": [], "engine": [], "cost": []}
    max_counts = {
        "tile": request.limits.map_tiles,
        "industry": request.limits.industries,
        "cargo": MAX_CARGOS,
        "engine": MAX_ENGINES,
        "cost": 1,
    }
    declared = None
    meta = None
    terminal = False
    checksum, sequence, total_bytes = 1, 0, 0

    def reject() -> Never:
        fail(
            Code.EXTRACTION_INCOMPLETE,
            "probe-parser",
            source,
            "invalid sequence, count, digest or incomplete extraction frame",
        )
        raise AssertionError("unreachable")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        for line in lines:
            # Even unrelated console output must consume the bounded stream budget.
            raw_bytes = line.encode("utf-8")
            total_bytes += len(raw_bytes)
            if total_bytes > MAX_STREAM_BYTES or len(raw_bytes) > MAX_FRAME_BYTES:
                fail(
                    Code.CANDIDATE_LIMIT_EXCEEDED,
                    "probe-parser",
                    source,
                    "extraction evidence exceeds transport bound",
                )
            if "P08|" not in line:
                continue
            raw = line[line.index("P08|") :].rstrip("\r\n")
            _, seq, kind, payload = raw.split("|", 3)
            if terminal or seq != str(sequence):
                reject()
            body = json.loads(payload, object_pairs_hook=unique_object)
            if not isinstance(body, dict):
                reject()
            if kind == "meta":
                if sequence != 0 or meta is not None:
                    reject()
                declared = body.pop("counts")
                if not isinstance(declared, dict) or set(declared) != set(groups):
                    reject()
                for key, count in declared.items():
                    if type(count) is not int or count < 0:
                        reject()
                    if count > max_counts[key]:
                        fail(
                            Code.CANDIDATE_LIMIT_EXCEEDED,
                            "probe-parser",
                            source,
                            "declared extraction count exceeds transport/profile bound",
                            key,
                        )
                if declared["cost"] != 1:
                    reject()
                meta = body
            elif kind == "failure":
                if (
                    set(body) != {"code", "message", "adler32"}
                    or body["adler32"] != f"{checksum:08x}"
                    or not isinstance(body["message"], str)
                    or not 1 <= len(body["message"]) <= 240
                ):
                    reject()
                code = Code(body["code"])
                if code not in {
                    Code.UNSUPPORTED_WORLD,
                    Code.CANDIDATE_LIMIT_EXCEEDED,
                    Code.EXTRACTION_INCOMPLETE,
                    Code.WORLD_CHANGED_DURING_PREPARATION,
                    Code.CATALOG_IDENTITY_MISMATCH,
                }:
                    reject()
                fail(code, "probe", source, body["message"])
            elif kind == "done":
                if (
                    meta is None
                    or set(body) != {"counts", "adler32"}
                    or (
                        type(body["adler32"]) is not str
                        or body["adler32"] != f"{checksum:08x}"
                        or body["counts"] != declared
                        or {key: len(rows) for key, rows in groups.items()} != declared
                    )
                ):
                    reject()
                terminal = True
            elif kind in groups and declared is not None:
                groups[kind].append(body)
                if len(groups[kind]) > declared[kind]:
                    reject()
            else:
                reject()
            if kind != "done":
                checksum = zlib.adler32((raw + "\n").encode("utf-8"), checksum)
            sequence += 1
        if not terminal or meta is None:
            reject()
        data = {
            **meta,
            **groups["cost"][0],
            "prepared_save_digest": prepared_save_digest,
            "complete": True,
            "tiles": groups["tile"],
            "industries": groups["industry"],
            "cargos": groups["cargo"],
            "engines": groups["engine"],
        }
        snapshot = authoritative(ExtractedWorldSnapshot.model_validate_json(json.dumps(data)))
        validate_snapshot(snapshot, request)
        return snapshot
    except (ValueError, KeyError, TypeError, IndexError, ValidationError) as error:
        from app.planning.preparation.failures import PreparationError

        if isinstance(error, PreparationError):
            raise
        reject()
        raise AssertionError("unreachable") from error
