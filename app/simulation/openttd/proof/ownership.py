"""Persistent input identities and disposable materializations have separate lifetimes."""

import json
from pathlib import Path

from app.simulation.openttd.runtime.ownership import OwnershipGraph, PathClass, PathOwnership


def freeze_materializations(directory, workspace, key_path, graphics, frozen):
    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    from .harness import sha256, write_json

    rows = []
    generated = directory / "materialization-inputs"
    generated.mkdir()
    for path in sorted(workspace.root.rglob("*")):
        if not path.is_file() or path == key_path:
            continue
        relative = path.relative_to(workspace.root)
        digest = sha256(path)
        if relative.parts[0] == "baseset":
            origin = graphics.resolve()
            derivation = "archive-member:opengfx-8.0/" + path.name
            classification = "RUNTIME_COPY"
        elif relative.parts[0] == "game":
            origin = (BRIDGE_DIRECTORY / path.name).resolve()
            derivation = "byte-copy"
            classification = "RUNTIME_COPY"
            if sha256(origin) != digest:
                raise ValueError("Canonical GameScript/runtime copy mismatch")
        else:
            # These generated, public-only launch inputs become immutable templates.
            origin = generated / path.name
            origin.write_bytes(path.read_bytes())
            derivation = "generated-template-copy"
            classification = "GENERATED_RUNTIME"
        frozen[str(origin)] = sha256(origin)
        rows.append(
            dict(
                path=str(path),
                sha256=digest,
                canonical_source=str(origin),
                canonical_sha256=sha256(origin),
                derivation=derivation,
                classification=classification,
            )
        )
    write_json(
        directory / "runtime-materializations.json",
        dict(
            policy="frozen-content-disposable-path-v1", workspace=str(workspace.root), entries=rows
        ),
    )
    frozen[str(directory / "runtime-materializations.json")] = sha256(
        directory / "runtime-materializations.json"
    )


def build_ownership(prepared_directory, root, key_path, destination, frozen, history):
    from .harness import PROJECT
    from .historical_protection import protection_base

    entries = {p: PathOwnership(Path(p), PathClass.IMMUTABLE_SOURCE) for p in frozen}
    base = protection_base(PROJECT, prepared_directory.parent)
    if history.get("policy"):
        for item in history["entries"]:
            p = str(base / item["path"])
            entries[p] = PathOwnership(Path(p), PathClass.PROTECTED_HISTORICAL)
        for item in history["credential_identities"]:
            p = str(base / item["path"])
            entries[p] = PathOwnership(Path(p), PathClass.PROTECTED_HISTORICAL)
    else:
        for name, files in history.items():
            for relative in files:
                p = str(prepared_directory.parent / name / relative)
                entries[p] = PathOwnership(Path(p), PathClass.PROTECTED_HISTORICAL)
    for p in root.rglob("*"):
        if p.is_file():
            if str(p) in entries:
                raise ValueError("Cleanup-owned path also classified as persistent input")
            entries[str(p)] = PathOwnership(
                p, PathClass.RUNTIME_CREDENTIAL if p == key_path else PathClass.RUNTIME_EPHEMERAL
            )
    entries[str(destination)] = PathOwnership(destination, PathClass.GENERATED_EVIDENCE)
    entries[str(prepared_directory / "path-ownership.json")] = PathOwnership(
        prepared_directory / "path-ownership.json", PathClass.IMMUTABLE_SOURCE
    )
    for name in ("source-freeze.json", "artifact-manifest.sha256"):
        path = prepared_directory / name
        entries[str(path)] = PathOwnership(path, PathClass.IMMUTABLE_SOURCE)
    return OwnershipGraph((root,), tuple(entries.values()))


def validate_ownership(prepared, frozen, *, materializations=True):
    from .harness import sha256

    directory = prepared.directory
    graph = OwnershipGraph.from_public(json.loads((directory / "path-ownership.json").read_text()))
    if graph.cleanup_roots != (prepared.spec.workspace.root,):
        raise ValueError("Ownership cleanup root mismatch")
    kinds = {str(e.path): e.kind for e in graph.entries}
    if any(
        kinds.get(p) not in (PathClass.IMMUTABLE_SOURCE, PathClass.PROTECTED_HISTORICAL)
        for p in frozen
    ):
        raise ValueError("Persistent frozen input missing from ownership graph")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    if (
        kinds.get(metadata["attempt_directory"]) != PathClass.GENERATED_EVIDENCE
        or kinds.get(str(prepared.key_path)) != PathClass.RUNTIME_CREDENTIAL
    ):
        raise ValueError("Evidence/credential ownership mismatch")
    content = json.loads((directory / "runtime-materializations.json").read_text())
    if content["policy"] != "frozen-content-disposable-path-v1" or content["workspace"] != str(
        prepared.spec.workspace.root
    ):
        raise ValueError("Materialization ownership mismatch")
    for row in content["entries"]:
        path = Path(row["path"])
        origin = row["canonical_source"]
        if (
            kinds.get(str(path)) != PathClass.RUNTIME_EPHEMERAL
            or origin not in frozen
            or frozen[origin] != row["canonical_sha256"]
        ):
            raise ValueError("Disposable content/canonical source classification mismatch")
        if (
            row["derivation"] in ("byte-copy", "generated-template-copy")
            and row["canonical_sha256"] != row["sha256"]
        ):
            raise ValueError("Materialization copy hash mismatch")
        if materializations and (not path.is_file() or sha256(path) != row["sha256"]):
            raise ValueError("Frozen runtime materialization content changed")
    return graph


def dispose_and_verify(prepared, frozen):
    """All proof kinds can use this final acceptance gate after retaining runtime logs."""
    from .harness import PROJECT, manifest, verify_freeze
    from .historical_protection import protection_base, validate_protection

    graph = validate_ownership(prepared, frozen, materializations=False)
    # Launch inputs were checked immediately before launch; OpenTTD may legitimately
    # rewrite its runtime config. Their paths have no post-run persistence promise.
    graph.validate()
    prepared.dispose()
    if prepared.spec.workspace.root.exists() or prepared.key_path.exists():
        raise ValueError("Workspace/credential disposal not complete")
    verify_freeze(frozen)
    # These two canonical documents bind themselves indirectly: the in-memory
    # input inventory and its public manifest must survive byte-identically.
    expected_inventory = json.dumps(dict(sorted(frozen.items())), sort_keys=True, indent=2) + "\n"
    if (prepared.directory / "source-freeze.json").read_text() != expected_inventory:
        raise ValueError("Persistent frozen input inventory changed after cleanup")
    if (prepared.directory / "artifact-manifest.sha256").read_text() != manifest(
        prepared.directory
    ):
        raise ValueError("Persistent public freeze manifest changed after cleanup")
    history = json.loads((prepared.directory / "historical-integrity.json").read_text())
    if history.get("policy"):
        validate_protection(protection_base(PROJECT, prepared.directory.parent), history)
    else:
        from .preflight import historical_snapshot

        current = historical_snapshot(prepared.directory.parent, prepared.directory)
        if any(current.get(name) != files for name, files in history.items()):
            raise ValueError("Historical postrun integrity changed")
    return dict(workspace_disposed=True, credential_removed=True, postrun_integrity_verified=True)


def finalize_cleanup(prepared, frozen, cleanup):
    """A final success gate shared by every public proof lifecycle."""
    if (
        not cleanup.get("reaped")
        or cleanup.get("remaining_processes")
        or cleanup.get("cleanup_error")
    ):
        raise ValueError("Owned process cleanup incomplete; workspace retained")
    cleanup.update(dispose_and_verify(prepared, frozen))
