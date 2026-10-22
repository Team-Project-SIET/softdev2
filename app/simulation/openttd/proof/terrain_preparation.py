"""Review candidates only: no attempt allocation, launch, or native proof issuance."""

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY, PACKAGE_FILES
from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
from app.simulation.openttd.supplemental_planning_facts import Region
from app.simulation.openttd.terrain_bridge import terrain_bridge_source
from app.simulation.openttd.tile_facts import TileFactsRequest

from .graphics import ARCHIVE_SHA256, stage_opengfx, validate_baseset
from .harness import (
    BINARY,
    BINARY_SHA256,
    PROJECT,
    EndpointReservation,
    launch_argv,
    sha256,
    verify_freeze,
    write_json,
)
from .harness import (
    source_freeze as shared_source_freeze,
)
from .structural_contract import StructuralFrameBudget


def source_freeze():
    """Shared runtime inventory plus transitive pure planning DTO dependencies."""
    frozen = shared_source_freeze()
    bridge = (PROJECT / "app/simulation/openttd/terrain_bridge.nut").resolve()
    frozen[str(bridge)] = sha256(bridge)
    for name in ("__init__.py", "domain.py", "canonical.py"):
        path = (PROJECT / "app/planning" / name).resolve()
        frozen[str(path)] = sha256(path)
    return frozen


REQUEST = TileFactsRequest("terrain-single-page-review", Region(x=1, y=1, width=5, height=1), 0)
SOURCE = dict(
    kind="NEW_WORLD_RECIPE",
    seed=42,
    map_x=6,
    map_y=6,
    landscape=0,
    starting_year=1950,
    land_generator=1,
    save_bytes=None,
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class SinglePageFrames(StructuralFrameBudget):
    limits = {"establishment": 2, "setup": 3, "query": 8, "cleanup": 1}
    maximum_frames = 14
    query_phases = ("query",)

    def __init__(self):
        super().__init__()
        self._counts = dict.fromkeys(self.limits, 0)

    def observe(self, direction, frame):
        super().observe(direction, frame)
        category = "cleanup" if direction == "outbound" and frame[2] == 1 else self.phase
        allowed = {
            "establishment": {("inbound", 103), ("inbound", 104)},
            "setup": {("outbound", 2), ("outbound", 7), ("inbound", 126)},
            "query": {("outbound", 6), ("outbound", 7), ("inbound", 124), ("inbound", 126)},
            "cleanup": {("outbound", 1)},
        }
        sequences = {
            "establishment": [("inbound", 103), ("inbound", 104)],
            "setup": [("outbound", 2), ("outbound", 7), ("inbound", 126)],
            "query": [("outbound", 6), ("inbound", 124), ("outbound", 7), ("inbound", 126)],
            "cleanup": [("outbound", 1)],
        }
        observed = [
            (r["direction"], r["packet_type"]) for r in self._frames if r["category"] == category
        ]
        if (direction, frame[2]) not in allowed[category] or observed != sequences[category][
            : len(observed)
        ]:
            self.failed = True
            self._frames[-1]["admitted"] = False
            raise ValueError("Undeclared/out-of-order post-auth packet")

    def enter(self, phase):
        if (
            self.phase in ("establishment", "setup")
            and self._counts[self.phase] != self.limits[self.phase]
        ):
            raise ValueError("Incomplete lifecycle phase")
        super().enter(phase)


@dataclass(frozen=True)
class TerrainCandidate:
    directory: Path
    record: dict

    @property
    def request(self):
        return TileFactsRequest.parse((self.directory / "request.json").read_bytes())

    def preflight(self, *, capture_phase="absent"):
        stored = json.loads((self.directory / "CANDIDATE.json").read_text())
        if (
            stored != self.record
            or stored["state"] != "REVIEW_CANDIDATE"
            or stored["authorized"] is not False
        ):
            raise ValueError("Candidate identity/status changed")
        if "authorization_policy" in stored and (
            stored["authorization_policy"]
            not in ("OPERATOR_ATTENDED_LOCAL_PROOF", "INDEPENDENTLY_AUTHENTICATED_PROOF")
            or stored.get("authorization_state") != "UNAUTHORIZED"
            or type(stored.get("maximum_launches")) is not int
            or stored["maximum_launches"] != 1
        ):
            raise PermissionError("Candidate authorization policy mismatch")
        if stored["attempt_identity"] is not None or stored["native_launches"] != 0:
            raise ValueError("Candidate cannot allocate an attempt")
        verify_freeze(stored["source_integrity"])
        for name, expected in stored["files"].items():
            path = self.directory / name
            if path.is_symlink() or sha256(path) != expected:
                raise ValueError("Candidate materialization changed")
        if sha256(Path(stored["executable"])) != BINARY_SHA256:
            raise ValueError("Executable identity mismatch")
        if sha256(Path(stored["graphics_archive"])) != ARCHIVE_SHA256:
            raise ValueError("Graphics identity mismatch")
        validate_baseset(Path(stored["graphics_directory"]))
        if (
            self.request != REQUEST
            or self.request.to_bytes() != (self.directory / "request.json").read_bytes()
        ):
            raise ValueError("Frozen request serialization mismatch")
        self.request.require_map(64, 64)
        if not 1 <= self.request.region.width * self.request.region.height <= 5:
            raise ValueError("Single page required")
        if stored["source"] != SOURCE or stored["source_digest"] != digest(SOURCE):
            raise ValueError("Source recipe mismatch")
        from .historical_protection import explicit_protection_base, validate_protection

        history = json.loads((self.directory / "historical-integrity.json").read_text())
        if stored.get("historical_base") != str(PROJECT.resolve()):
            raise ValueError("Historical candidate provenance base mismatch")
        validate_protection(explicit_protection_base(history, PROJECT), history)
        from app.simulation.openttd.runtime.ownership import OwnershipGraph

        graph = OwnershipGraph.from_public(
            json.loads((self.directory / "path-ownership.json").read_text())
        )
        root = Path(stored["workspace"])
        rows = json.loads((self.directory / "runtime-materializations.json").read_text())["entries"]
        from .terrain_failure import RuntimeInputMismatch

        for path in [Path(r["path"]) for r in rows] + [Path(stored["key_path"])]:
            if not path.exists() or not stat.S_ISREG(path.lstat().st_mode):
                raise RuntimeInputMismatch(
                    "Missing or invalid runtime input", missing_paths=[str(path)]
                )
        if sha256(root / "openttd.cfg") != stored["configuration_digest"]:
            raise ValueError("Configuration semantic identity mismatch")
        if (
            stored["version"] != "15.3"
            or stored["executable_digest"] != BINARY_SHA256
            or stored["graphics_digest"] != ARCHIVE_SHA256
        ):
            raise ValueError("Runtime metadata identity mismatch")
        if (stored["region"], stored["expected_tiles"], stored["cursor"]) != (
            [1, 1, 5, 1],
            [65, 66, 67, 68, 69],
            0,
        ):
            raise ValueError("Region metadata identity mismatch")
        if stored["environment"] != dict(RuntimeWorkspace.reopen(root).environment):
            raise ValueError("Exact environment identity mismatch")
        rows = json.loads((self.directory / "runtime-materializations.json").read_text())["entries"]
        expected_runtime_paths = {row["path"] for row in rows} | {stored["key_path"]}
        from .terrain_capture import capture_paths, validate_captures

        captures = capture_paths(root)
        if stored.get("capture_outputs") != list(map(str, captures)):
            raise ValueError("Capture output declaration mismatch")
        from app.simulation.openttd.runtime.ownership import PathClass

        kinds = {str(e.path): e.kind for e in graph.entries}
        if any(kinds.get(str(p)) != PathClass.RUNTIME_EPHEMERAL for p in captures):
            raise ValueError("Capture output ownership declaration mismatch")
        validate_captures(root, phase=capture_phase, inputs=expected_runtime_paths)
        allowed_outputs = set(map(str, captures)) if capture_phase != "absent" else set()
        actual_paths = {str(p) for p in root.rglob("*") if not p.is_dir()}
        if actual_paths != expected_runtime_paths | allowed_outputs or any(
            p.is_symlink() for p in root.rglob("*")
        ):
            error = RuntimeInputMismatch(
                "Unexpected runtime cache input",
                expected_runtime_input_count=len(expected_runtime_paths),
                actual_runtime_input_count=len(actual_paths - allowed_outputs),
                unexpected_paths=sorted(actual_paths - expected_runtime_paths - allowed_outputs),
                missing_paths=sorted(expected_runtime_paths - actual_paths),
            )
            raise error
        for row in rows:
            if (
                sha256(Path(row["path"])) != row["sha256"]
                or sha256(Path(row["canonical_source"])) != row["canonical_sha256"]
            ):
                raise RuntimeInputMismatch(
                    "Runtime cache materialization changed",
                    identity_mismatches=[
                        dict(
                            path=row["path"],
                            expected=row["sha256"],
                            actual=sha256(Path(row["path"])),
                        )
                    ],
                )
        key_path = Path(stored["key_path"])
        if (
            key_path.is_symlink()
            or key_path.stat().st_mode & 0o777 != 0o600
            or key_path.stat().st_uid != os.getuid()
        ):
            raise ValueError("Credential ownership/mode mismatch")
        if AuthorizedKey.from_bytes(key_path.read_bytes()).public_hex != stored["public_key"]:
            raise ValueError("Public credential identity mismatch")
        if tuple(stored["argv"]) != launch_argv(
            BINARY, root / "openttd.cfg", stored["endpoints"][0]
        ):
            raise ValueError("Exact argv mismatch")
        package = package_bytes()
        if any((self.directory / "bridge" / n).read_bytes() != b for n, b in package.items()):
            raise ValueError("Missing/shadowed terrain handler")
        if stored["bridge_digest"] != package_digest(package):
            raise ValueError("Bridge package digest mismatch")
        if stored["budget"] != budget() or stored["request_sha256"] != sha256(
            self.directory / "request.json"
        ):
            raise ValueError("Accounting/request identity mismatch")
        return dict(
            status="PREFLIGHT_CANDIDATE_PASS",
            authorized=False,
            launches=0,
            connections=0,
            requests=0,
        )


def package_bytes():
    return {
        "info.nut": (BRIDGE_DIRECTORY / "info.nut").read_bytes(),
        "main.nut": terrain_bridge_source().encode(),
    }


def package_digest(package):
    h = hashlib.sha256()
    for name in sorted(PACKAGE_FILES):
        b = package[name]
        h.update(name.encode() + b"\0" + len(b).to_bytes(8, "big") + b)
    return h.hexdigest()


def budget():
    return dict(
        application_requests=1,
        request_bytes=len(REQUEST.to_bytes()),
        response_bytes=420,
        query_operations=8,
        native_getter_calls=5 * 44 + 6,
        lifecycle_frames=2 + 3 + 1,
        post_auth_frames=14,
        capture_bytes=262144,
        retries=0,
        reconnects=0,
        resumes=0,
    )


def configuration_template() -> str:
    """Exact reviewed public-only recipe; shared by preparation and retention."""
    return (
        "[version]\nversion_string = 15.3\nini_version = 7\n"
        "[network]\nserver_game_type = local\nmin_active_clients = 0\nreload_cfg = false\n"
        "allow_insecure_admin_login = false\n[gui]\nautosave_interval = 0\n"
        "autosave_on_exit = false\nthreaded_saves = false\npause_on_newgame = false\n"
        "[game_creation]\nmap_x = 6\nmap_y = 6\nlandscape = temperate\n"
        "starting_year = 1950\nland_generator = 1\ngeneration_seed = 42\n"
        "[difficulty]\nmax_no_competitors = 0\n[misc]\ngraphicsset = OpenGFX\n"
        "[economy]\ntimekeeping_units = 0\n[game_scripts]\nNoMutationBridge = \n"
    )


def prepare_candidate(directory: Path, *, authorization_policy=None):
    """Owned CACHE_ONLY inputs; no runtime inspection, launch or attempt allocation."""
    if authorization_policy is not None and authorization_policy not in (
        "OPERATOR_ATTENDED_LOCAL_PROOF",
        "INDEPENDENTLY_AUTHENTICATED_PROOF",
    ):
        raise PermissionError("Unsupported candidate authorization policy")
    directory = directory.absolute()
    if directory != directory.resolve() or directory.exists():
        raise ValueError("Fresh nonaliasing candidate root required")
    # Mandatory assets validated before writing anything.
    if sha256(BINARY) != BINARY_SHA256:
        raise ValueError("Pinned OpenTTD executable missing/mismatched")
    graphics = PROJECT / "artifacts/runtime/verified-assets/opengfx-8.0-all.zip"
    gfx = graphics.with_name("OpenGFX-8.0")
    if sha256(graphics) != ARCHIVE_SHA256:
        raise ValueError("Graphics archive mismatch")
    validate_baseset(gfx)
    frozen = source_freeze()
    frozen[str(BINARY)] = BINARY_SHA256
    frozen[str(graphics)] = ARCHIVE_SHA256
    frozen[str((PROJECT / "app/simulation/openttd/terrain_bridge.nut").resolve())] = sha256(
        PROJECT / "app/simulation/openttd/terrain_bridge.nut"
    )
    from .historical_protection import capture_protection, protection_digest

    runtime = PROJECT / "artifacts/runtime"
    history = capture_protection(
        PROJECT, runtime, runtime / "terrain-candidate-pending", runtime / "terrain-attempt-pending"
    )
    history["provenance_base"] = str(PROJECT.resolve())
    history["sha256"] = protection_digest(history)
    for n in gfx.iterdir():
        if n.is_file():
            frozen[str(n.resolve())] = sha256(n)
    package = package_bytes()
    directory.mkdir(parents=True, mode=0o700)
    (directory / "bridge").mkdir(mode=0o700)
    for n, b in package.items():
        (directory / "bridge" / n).write_bytes(b)
    (directory / "request.json").write_bytes(REQUEST.to_bytes())
    write_json(directory / "source.json", SOURCE)
    write_json(directory / "historical-integrity.json", history)
    # Exact reviewed template. Credential and endpoint materialization must be reviewed again.
    config = configuration_template()
    (directory / "config-template.cfg").write_text(config)
    workspace = RuntimeWorkspace.create(directory / "cache", retain=True)
    workspace.logs.chmod(0o700)
    reservation = EndpointReservation.allocate()
    try:
        key = AuthorizedKey.generate()
        key_path = workspace.root / ".admin-secret"
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(key._secret)
        workspace.write_config(
            AdminSettings(
                password="",
                game_port=reservation.game_port,
                port=reservation.admin_port,
                authorized_public_key_hex=key.public_hex,
            )
        )
        # Keep secure endpoints; append reviewed world settings.
        base = workspace.config.read_text().split("[gui]", 1)[0]
        workspace.config.write_text(base + "[gui]" + config.split("[gui]", 1)[1])
        stage_opengfx(graphics, workspace.root / "baseset/OpenGFX", expected_sha256=ARCHIVE_SHA256)
        staged = workspace.game / "NoMutationBridge"
        staged.mkdir(mode=0o700)
        for n, b in package.items():
            (staged / n).write_bytes(b)
        from .ownership import build_ownership, freeze_materializations

        freeze_materializations(
            directory,
            workspace,
            key_path,
            graphics,
            frozen,
            bridge_sources={n: directory / "bridge" / n for n in package},
        )
        for n in (
            "request.json",
            "source.json",
            "historical-integrity.json",
            "config-template.cfg",
        ):
            frozen[str(directory / n)] = sha256(directory / n)
        graph = build_ownership(
            directory,
            workspace.root,
            key_path,
            directory / "proposed-attempt-unassigned",
            frozen,
            {},
            capture_outputs=(workspace.logs / "stdout.log", workspace.logs / "stderr.log"),
        )
        write_json(directory / "path-ownership.json", graph.public())
        frozen[str(directory / "path-ownership.json")] = sha256(directory / "path-ownership.json")
        ports = [reservation.game_port, reservation.admin_port]
        argv = launch_argv(BINARY, workspace.config, ports[0])
    except BaseException as error:
        write_json(
            directory / "PREPARATION-FAILURE.json",
            dict(
                state="PRELAUNCH_FAILED",
                error_type=type(error).__name__,
                launches=0,
                connections=0,
                requests=0,
            ),
        )
        (workspace.root / ".admin-secret").unlink(missing_ok=True)
        workspace.close()
        raise
    finally:
        reservation.close()
    record = dict(
        historical_base=str(PROJECT.resolve()),
        state="REVIEW_CANDIDATE",
        authorized=False,
        attempt_identity=None,
        native_launches=0,
        executable=str(BINARY),
        executable_digest=BINARY_SHA256,
        version="15.3",
        version_authority="prior inspected executable plus exact byte identity",
        graphics_archive=str(graphics),
        graphics_digest=ARCHIVE_SHA256,
        graphics_directory=str(gfx),
        bridge_digest=package_digest(package),
        source=SOURCE,
        source_digest=digest(SOURCE),
        configuration_digest=sha256(workspace.config),
        workspace=str(workspace.root),
        capture_outputs=[str(workspace.logs / n) for n in ("stdout.log", "stderr.log")],
        public_key=key.public_hex,
        key_path=str(key_path),
        endpoints=ports,
        argv=list(argv),
        environment=dict(workspace.environment),
        request_sha256=sha256(directory / "request.json"),
        region=[1, 1, 5, 1],
        expected_tiles=[65, 66, 67, 68, 69],
        cursor=0,
        budget=budget(),
        argv_template=[
            str(BINARY),
            "-D127.0.0.1:<game_port>",
            "-c",
            "<owned_config>",
            "-x",
            "-X",
            "-g",
            "-G",
            "42",
            "-dscript=4,grf=1,net=3",
        ],
        environment_allowlist=["HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"],
        unresolved=[
            "separately reviewed authorization/immutable seal only",
            "separately authorized immutable freeze and fresh attempt destination",
        ],
        source_integrity=frozen,
        files={
            str(p.relative_to(directory)): sha256(p)
            for p in sorted(directory.rglob("*"))
            if p.is_file() and not p.is_relative_to(workspace.root)
        },
    )
    if authorization_policy is not None:
        record.update(
            authorization_policy=authorization_policy,
            authorization_state="UNAUTHORIZED",
            maximum_launches=1,
        )
    write_json(directory / "CANDIDATE.json", record)
    result = TerrainCandidate(directory, record)
    result.preflight()
    return result


def load_terrain_prepared(candidate_directory: Path, sealed_directory: Path):
    """Read inputs only; a separate immutable operator seal is still mandatory."""
    from app.simulation.openttd.runtime.base import LaunchSpecification
    from app.simulation.openttd.runtime.identity import RuntimeIdentity

    from .harness import PreparedProof

    row = json.loads((candidate_directory / "CANDIDATE.json").read_text())
    TerrainCandidate(candidate_directory, row).preflight()
    workspace = RuntimeWorkspace.reopen(Path(row["workspace"]))
    spec = LaunchSpecification(
        workspace,
        RuntimeIdentity(BINARY, "15.3", BINARY_SHA256),
        tuple(row["argv"]),
        workspace.root,
        workspace.environment,
        workspace.logs / "stdout.log",
        workspace.logs / "stderr.log",
    )
    return PreparedProof(
        sealed_directory,
        spec,
        Path(row["key_path"]),
        row["public_key"],
        tuple(row["endpoints"]),
        REQUEST,
    )
