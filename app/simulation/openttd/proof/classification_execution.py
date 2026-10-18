"""Executable runtime staging for ONE Tile Classification V2 capture attempt.

The frozen prepared candidate (``artifacts/demos/classification-seed17-*/``)
staged a launch *template* whose variables were never materialized: no reviewed
procedure produced the isolated runtime, the composed classification package,
the configuration, endpoints, credential or executable argv. This module closes
exactly that seam offline (no launch, no AdminPort connection, no authorization
consumption, no mutation of the frozen source candidate):

- it re-verifies the frozen source candidate and its retained references,
- it stages a fresh, owned isolated OpenTTD 15.3 runtime workspace with the
  composed classification GameScript package, — for source-save
  correspondence — the retained ``before.sav``'s stored AI package
  (``RoadProofCompany``/version 1; without a staged AI the engine substitutes a
  random AI and falls back to an instant-dying dummy AI, the
  ``The savegame has an AI by the name … which is no longer available`` fallback
  observed in the consumed ``classification-exec-seed17-e71c95a3`` attempt), the
  exact Seed 17 world recipe,
  pinned OpenGFX assets, freshly reserved loopback endpoints and a private
  Admin credential, and
- it records the complete executable path — exact final argv, config digest,
  package digests, source-save binding and budgets — as a NEW sealed
  ``PENDING_AUTHORIZATION`` candidate whose one-launch claim is written only by
  the capture runner after preflight (never by this preparation).

Correspondence modes (:mod:`proof.world_correspondence`): the bound mode is
``SOURCE_SAVE_FUSION`` — the capture process loads the byte-verified retained
``before.sav``, so the census runs against the retained qualified world state
and no same-session facts bank is required. The fallback
``SAME_SESSION_CENSUS`` schedule is recorded for review; binding it to an
executable attempt needs its own fresh reviewed candidate. The staged
composition announces the save's stored GameScript identity (the retained
``RoadFreightProof`` info identity) so the save's GameScript reference can
resolve; the classification handler bytes remain byte-identical to the frozen
additive composition.
"""

import argparse
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from app.demo_random import RandomWorldSettings

from ..admin_crypto import AuthorizedKey
from ..gamescript_bridge import BRIDGE_DIRECTORY
from ..runtime.base import LaunchSpecification
from ..runtime.config import AdminSettings, RuntimeWorkspace
from ..runtime.identity import RuntimeIdentity
from ..terrain_classification_bridge import (
    classification_package_bytes,
    classification_package_digest,
)
from ..tile_classification import (
    CLASSIFICATION_PAGE_LIMIT,
    CLASSIFICATION_SCHEMA_VERSION,
    CLASSIFICATION_TOTAL_RESPONSE_BYTES_LIMIT,
    TileClassificationRequest,
)
from .graphics import ARCHIVE_SHA256, GraphicsIdentity, stage_opengfx
from .harness import (
    BINARY,
    BINARY_SHA256,
    PROJECT,
    EndpointReservation,
    PreparedProof,
    manifest,
    sha256,
    source_freeze,
    verify_freeze,
    write_json,
)
from .native import matching_processes
from .terrain_classification_preparation import (
    ARTIFACT_ROOT,
    CAPTURE_KIND,
    CLASSIFICATION_REQUEST_ID,
    GSADMIN_BYTES,
    OBSERVATION_SECONDS,
    SEED17_RUN,
    WELCOME_IDENTITY_KEYS,
    cleanup_procedure,
    request_plan,
    retained_facts,
    retained_welcome,
    validate_staging_seams,
)
from .world_correspondence import (
    CORRESPONDENCE_MODES,
    FRESH_GENERATION_MODE,
    SOURCE_SAVE_GS_NAME,
    SOURCE_SAVE_MODE,
    persist_same_session_schedule,
    retained_save_binding,
    verify_staged_source_save,
)

EXEC_KIND = "tile-classification-execution"
EXEC_STATE = "PENDING_AUTHORIZATION"
PRELAUNCH_SCHEMA = "tile-classification-execution-prelaunch-v1"
LAUNCH_DEBUG_FLAGS = "-dscript=4,grf=1,net=3"
EXECUTION_SEED = 17
REQUEST_BYTES_LIMIT = 159
FRESH_TABLE_KEY = "NoMutationBridge"
GRAPHICS_ARCHIVE = PROJECT / "artifacts/runtime/verified-assets/opengfx-8.0-all.zip"
STAGED_SAVE_NAME = "source.sav"
SECRET_NAME = ".admin-secret"
AI_PACKAGE_PROJECT = PROJECT / "app/simulation/openttd/road_company_package"
# The retained save stores the AI identity `RoadProofCompany`/version 1
# (saveload/ai_sl.cpp resolution). Staging exactly this package restores that
# stored identity natively; without it, OpenTTD 15.3 prints the
# "which is no longer available" fallback, substitutes a random AI and — with
# no AI installed — falls back to the instant-dying dummy AI.
AI_PACKAGE_NAME = "RoadProofCompany"


def staged_ai_package_bytes() -> dict[str, bytes]:
    """The retained save's stored AI package (never compiled or executed here)."""
    files = {path.name: path.read_bytes() for path in sorted(AI_PACKAGE_PROJECT.glob("*.nut"))}
    if not files:
        raise ValueError(f"Retained AI package source missing: {AI_PACKAGE_PROJECT}")
    validate_staged_ai_identity(files)
    return files


def validate_staged_ai_identity(files: dict[str, bytes]) -> None:
    """Fail staging when the staged AI identity contradicts the retained save."""
    info = files.get("info.nut", b"").decode()
    main = files.get("main.nut", b"").decode()
    if 'function GetName() { return "RoadProofCompany"; }' not in info:
        raise ValueError("staged AI package lost the retained RoadProofCompany identity")
    if "function GetVersion() { return 1; }" not in info:
        raise ValueError("staged AI package lost the retained version 1 identity")
    if "class RoadProofCompany extends AIController" not in main:
        raise ValueError("staged AI package lost the retained controller class")


def staged_ai_digest(files: dict[str, bytes]) -> str:
    """Same digest convention as the GameScript package binding (name\\0len\\0bytes)."""
    digest = hashlib.sha256()
    for name in sorted(files):
        data = files[name]
        digest.update(name.encode() + b"\0" + len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def staged_ai_identity(files: dict[str, bytes]) -> dict:
    """Sealed AI-package facts for the candidate/prelaunch records."""
    return {
        "name": AI_PACKAGE_NAME,
        "digest": staged_ai_digest(files),
        "files": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(files.items())
        },
        "statement": (
            "the staged RoadProofCompany/package restores the retained save's "
            "stored AI identity; without it the engine substitutes a random AI "
            "(save-load fallback) and falls back to an instant-dying dummy AI"
        ),
    }


def source_candidate_binding() -> tuple[Path, dict]:
    """Re-verify the frozen prepared candidate's task-meaningful artifacts.

    The historical candidate records the complete pre-execution source tree it
    proposed to launch with. Those byte snapshots are a historical record —
    this additive task extends runtime modules by design, so the active
    binding re-derives the load-bearing artifacts instead of re-hashing the
    historical snapshot:

    - the deterministic 450-tile request plan (payload digest for every page;
      the plan bytes are verified collection-by-collection against the
      retained region),
    - the composed classification package digest (composition seams included),
    - the retained Seed 17 references and welcome identity,
    - the unconsumed one-shot state (no launch recorded, no claim written,
      no request sent).

    The execution candidate's own frozen inventory pins the CURRENT source
    tree, so any further source drift stops its preflight.
    """
    stored_candidates = sorted(ARTIFACT_ROOT.glob("classification-seed17-*/CANDIDATE.json"))
    if len(stored_candidates) != 1:
        raise ValueError(
            "expected exactly one frozen prepared classification candidate, "
            f"found {len(stored_candidates)}"
        )
    stored = json.loads(stored_candidates[0].read_bytes())
    if stored.get("kind") != CAPTURE_KIND or stored.get("state") != "PENDING_AUTHORIZATION":
        raise ValueError("frozen candidate record changed")
    if stored.get("authorized") is not False:
        raise ValueError("frozen candidate authorization state changed")
    if stored.get("native_launches") != 0 or stored.get("requests_sent") != 0:
        raise PermissionError("frozen prepared candidate cannot consume launches itself")
    if (stored_candidates[0].parent / "CLAIM.json").is_file():
        raise ValueError("frozen prepared candidate claim record exists")
    plan = request_plan()
    if [hashlib.sha256(payload).hexdigest() for payload in plan] != [
        item["request_payload_sha256"] for item in stored["plan"]["pages"]
    ]:
        raise ValueError("frozen candidate request plan drifted")
    if (
        len(plan) != stored["plan"]["pages_count"]
        or len(stored["plan"]["pages"]) != stored["plan"]["pages_count"]
    ):
        raise ValueError("frozen candidate page count contradicts the plan")
    seams = validate_staging_seams()
    if seams["classification_package_digest"] != stored["package"]["digest"]:
        raise ValueError("frozen candidate package composition drifted")
    for name, entry in stored["retained_reference"].items():
        path = SEED17_RUN / name
        if not path.is_file() or sha256(path) != entry["sha256"]:
            raise ValueError(f"retained reference changed or missing: {name}")
    facts = retained_facts()
    if (
        facts.region.x,
        facts.region.y,
        facts.region.width,
        facts.region.height,
    ) != tuple(stored["plan"]["region"]):
        raise ValueError("frozen candidate classification region drifted")
    if len(facts.tiles) != stored["plan"]["tiles"]:
        raise ValueError("frozen candidate tile count drifted")
    welcome = retained_welcome()
    identity_requirements = stored["world_identity_requirements"]
    if {
        key: welcome.get(key) for key in identity_requirements["retained_welcome"]
    } != identity_requirements["retained_welcome"]:
        raise ValueError("frozen candidate welcome identity drifted")
    return stored_candidates[0].parent, stored


def load_execution(directory: Path) -> PreparedExecution:
    """Reopen a staged execution candidate from its sealed records."""
    stored = json.loads((directory / "CANDIDATE.json").read_bytes())
    if stored.get("kind") != EXEC_KIND:
        raise ValueError("candidate directory is not a staged execution")
    return PreparedExecution(
        directory=directory,
        attempt_identity=stored["attempt_identity"],
        package_digest=stored["package"]["digest"],
        pages=stored["plan"]["pages_count"],
        tiles=stored["plan"]["tiles"],
        mode=stored["correspondence_mode"],
    )


def _authority(source: str, anchors: dict[str, str]) -> str:
    """Asserted-anchored composition: every anchor must occur exactly once."""
    for anchor, replacement in anchors.items():
        if source.count(anchor) != 1:
            raise ValueError("composition authority drifted")
        source = source.replace(anchor, replacement)
    return source


def save_compatible_info_bytes() -> bytes:
    """Base bridge info adapted to the retained save's stored GameScript identity.

    OpenTTD resolves a savegame's GameScript by the name (and version) stored
    inside the save, so the source-save composition announces exactly the
    retained staged identity (``RoadFreightProof``/version 1). Author, API
    version, CreateInstance class and registration stay byte-identical to the
    frozen base composition.
    """
    adapted = _authority(
        (BRIDGE_DIRECTORY / "info.nut").read_text(),
        {
            'function GetName() { return "NoMutationBridge"; }': (
                f'function GetName() {{ return "{SOURCE_SAVE_GS_NAME}"; }}'
            ),
            "function GetVersion() { return 2; }": "function GetVersion() { return 1; }",
            'function GetShortName() { return "NMBA"; }': (
                'function GetShortName() { return "RFP1"; }'
            ),
            "function GetDescription() "
            '{ return "Protocol-one AdminPort ping/ACK and read-only world_info"; }': (
                "function GetDescription() { return "
                '"Tile Classification V2 composition staged for source-save '
                'correspondence"; }'
            ),
        },
    )
    if adapted.count('function CreateInstance() { return "NoMutationBridge"; }') != 1:
        raise ValueError("save-compatible composition lost its controller identity")
    if f'function GetName() {{ return "{SOURCE_SAVE_GS_NAME}"; }}' not in adapted:
        raise ValueError("save-compatible composition lost the save GameScript identity")
    return adapted.encode()


def save_compatible_package_bytes() -> dict[str, bytes]:
    """Composed classification main.nut plus the save-compatible info identity."""
    package = classification_package_bytes()
    return {"info.nut": save_compatible_info_bytes(), "main.nut": package["main.nut"]}


def execution_package(mode: str) -> dict[str, bytes]:
    if mode == SOURCE_SAVE_MODE:
        return save_compatible_package_bytes()
    if mode == FRESH_GENERATION_MODE:
        return classification_package_bytes()
    raise ValueError("unknown correspondence mode")


def execution_package_digest(package: dict[str, bytes]) -> str:
    """Same convention as the frozen candidate's package binding (name\\0len\\0bytes)."""
    return classification_package_digest(package)


def validate_execution_package(mode: str) -> dict:
    """Fail staging on a drifted or contradictory staged composition."""
    package = execution_package(mode)
    composed = package["main.nut"].decode()
    info = package["info.nut"].decode()
    if not composed or not info:
        raise ValueError("staged execution package is empty")
    # The composed main bytes stay identical to the frozen classification
    # composition for every mode: only the info identity may differ, and only
    # for the source-save correspondence.
    if composed != classification_package_bytes()["main.nut"].decode():
        raise ValueError("executed composition drifted from the frozen classification main")
    if composed.count("class NoMutationBridge extends TerrainClassificationBridge {}") != 1:
        raise ValueError("classification handler seam missing from the staged package")
    if composed.count("class RawObservationBridge extends GSController") != 1:
        raise ValueError("raw bridge marker rename drifted in the staged package")
    for prohibited in ("RaiseTile", "LowerTile", "LevelTiles"):
        if prohibited in composed:
            raise ValueError(f"staged package carries a prohibited mutation seam: {prohibited}")
    if "BRIDGE_STARTED protocol=1 api=15" not in composed:
        raise ValueError("staged package lost the bridge readiness marker")
    expected_name = SOURCE_SAVE_GS_NAME if mode == SOURCE_SAVE_MODE else FRESH_TABLE_KEY
    if info.count(f'function GetName() {{ return "{expected_name}"; }}') != 1:
        raise ValueError("staged info identity does not match the correspondence mode")
    if mode == SOURCE_SAVE_MODE and info.count("function GetVersion() { return 1; }") != 1:
        raise ValueError("save-compatible info version drifted")
    if mode == FRESH_GENERATION_MODE and (
        (BRIDGE_DIRECTORY / "info.nut").read_bytes() != package["info.nut"]
    ):
        raise ValueError("fresh-generation info identity drifted from the frozen base")
    return {
        "package_digest": execution_package_digest(package),
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in sorted(package.items())
        },
    }


def staged_package_name(mode: str) -> str:
    """The GameScript directory/config key of the staged composition."""
    return SOURCE_SAVE_GS_NAME if mode == SOURCE_SAVE_MODE else FRESH_TABLE_KEY


def execution_argv(
    mode: str, config: Path, game_port: int, source_save: Path | None = None
) -> tuple[str, ...]:
    """Exact final argv; the reserved endpoints are the only runtime variable.

    Mirrors the retained Seed 17 record bitwise for the fresh-generation shape
    (``-G 17 -g``) and the established loaded-save shape (``-g <save>``) for
    the source-save correspondence.
    """
    base = [str(BINARY), f"-D127.0.0.1:{game_port}", "-c", str(config), "-x", "-X"]
    if mode == SOURCE_SAVE_MODE:
        if source_save is None:
            raise ValueError("source-save correspondence requires a staged save")
        return tuple(base + ["-g", str(source_save), LAUNCH_DEBUG_FLAGS])
    return tuple(base + ["-G", str(EXECUTION_SEED), "-g", LAUNCH_DEBUG_FLAGS])


def budgets(mode: str) -> dict:
    """Sealed capture budgets for the bound mode (never silently grown)."""
    if mode != SOURCE_SAVE_MODE:
        raise ValueError("only the source-save correspondence is bound for execution")
    request_count = len(request_plan())
    return dict(
        pages_limit=CLASSIFICATION_PAGE_LIMIT,
        requests=request_count,
        session_requests=request_count,
        total_response_bytes_limit=CLASSIFICATION_TOTAL_RESPONSE_BYTES_LIMIT,
        gsadmin_bytes_per_page=GSADMIN_BYTES,
        request_bytes_limit=REQUEST_BYTES_LIMIT,
        observation_seconds=OBSERVATION_SECONDS,
        launches=1,
        connections=1,
        retries=0,
        reconnects=0,
        mutations=0,
        construction_actions=0,
        tile_facts_requests=0,
    )


def execution_world_settings() -> str:
    """The exact retained Seed 17 native-generator recipe (staged, never launched)."""
    source = RandomWorldSettings.model_validate(
        {
            "seed": EXECUTION_SEED,
            "map_size": 256,
            "climate": "temperate",
            "terrain": 0,
            "towns": 1,
            "industries": 2,
        }
    ).config()
    expected = "[economy]\ntimekeeping_units = 0\n[newgrf]\n"
    retained_variant = (
        "[economy]\ntimekeeping_units = 0\nmultiple_industry_per_town = true\n[newgrf]\n"
    )
    if source.count(expected) != 1:
        raise ValueError("native generator recipe drifted")
    return source.replace(expected, retained_variant)


CONFIG_FRAGMENTS = (
    "version_string = 15.3",
    "[network]",
    "[misc]",
    "graphicsset = OpenGFX",
    "[ai]",
    "ai_in_multiplayer = true",
    "[game_scripts]",
    "map_x = 8",
    "map_y = 8",
    "landscape = temperate",
    "starting_year = 1950",
    "land_generator = 1",
    "[difficulty]",
    "terrain_type = 0",
    "number_towns = 1",
    "industry_density = 2",
    "max_no_competitors = 0",
    "infinite_money = false",
    "vehicle_breakdowns = 0",
    "disasters = false",
    "[economy]",
    "timekeeping_units = 0",
    "multiple_industry_per_town = true",
    "[newgrf]",
    "pause_on_newgame = false",
)


@dataclass(frozen=True)
class StagedRuntime:
    """Everything the executable path depends on, freshly materialized."""

    workspace: RuntimeWorkspace
    argv: tuple[str, ...]
    secret_path: Path
    public_key: str
    package: dict[str, bytes]
    package_digest: str
    game_port: int
    admin_port: int
    config_sha256: str
    source_save: Path | None
    graphics: GraphicsIdentity
    ai_package: dict[str, bytes]

    def dispose(self) -> None:
        if self.workspace.root.exists():
            shutil.rmtree(self.workspace.root)


def stage_runtime(directory: Path, *, mode: str) -> StagedRuntime:
    """Create the owned isolated runtime for the capture (offline staging only)."""
    if mode not in CORRESPONDENCE_MODES:
        raise ValueError("unknown correspondence mode")
    workspace = RuntimeWorkspace.create(directory / "isolated", retain=True)
    try:
        reservation = EndpointReservation.allocate()
        try:
            name = staged_package_name(mode)
            key = AuthorizedKey.generate()
            secret = workspace.root / SECRET_NAME
            # A restricted credential, never part of any evidence/manifest/source hash.
            with os.fdopen(
                os.open(secret, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
            ) as stream:
                stream.write(key._secret)
            workspace.write_config(
                AdminSettings(
                    password="",
                    port=reservation.admin_port,
                    game_port=reservation.game_port,
                    authorized_public_key_hex=key.public_hex,
                )
            )
            config = workspace.config.read_text().replace(
                "pause_on_newgame = true", "pause_on_newgame = false"
            )
            config += (
                "\n[misc]\ngraphicsset = OpenGFX\n[ai]\nai_in_multiplayer = true\n"
                f"[game_scripts]\n{name} = \n"
            ) + execution_world_settings()
            workspace.config.write_text(config)
            package = execution_package(mode)
            staged = workspace.game / name
            staged.mkdir(mode=0o700)
            for file_name, data in package.items():
                with (staged / file_name).open("xb") as output:
                    output.write(data)
            ai_package: dict[str, bytes] = {}
            if mode == SOURCE_SAVE_MODE:
                # The retained save stores the RoadProofCompany/version 1 AI
                # identity. Staging exactly that package resolves it natively;
                # a missing AI makes the engine substitute a random AI and
                # fall back to the instant-dying dummy AI (OpenTTD 15.3
                # save-load fallback). Fresh-generation modes stage no AI.
                ai_package = staged_ai_package_bytes()
                ai_directory = workspace.ai / AI_PACKAGE_NAME
                ai_directory.mkdir(mode=0o700)
                for file_name, data in ai_package.items():
                    with (ai_directory / file_name).open("xb") as output:
                        output.write(data)
            graphics = stage_opengfx(GRAPHICS_ARCHIVE, workspace.root / "baseset/OpenGFX")
            source_save = None
            if mode == SOURCE_SAVE_MODE:
                binding = retained_save_binding()
                source_save = workspace.root / STAGED_SAVE_NAME
                shutil.copyfile(SEED17_RUN / binding["save"], source_save)
                verify_staged_source_save(binding, source_save)
            return StagedRuntime(
                workspace=workspace,
                argv=execution_argv(mode, workspace.config, reservation.game_port, source_save),
                secret_path=secret,
                public_key=key.public_hex,
                package=package,
                package_digest=execution_package_digest(package),
                game_port=reservation.game_port,
                admin_port=reservation.admin_port,
                config_sha256=sha256(workspace.config),
                source_save=source_save,
                graphics=graphics,
                ai_package=ai_package,
            )
        finally:
            reservation.close()
    except BaseException:
        shutil.rmtree(workspace.root, ignore_errors=True)
        raise


@dataclass(frozen=True)
class PreparedExecution:
    """A freshly staged, sealed, executable capture candidate (no launch)."""

    directory: Path
    attempt_identity: str
    package_digest: str
    pages: int
    tiles: int
    mode: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "directory", self.directory.resolve())

    def candidate(self) -> dict:
        stored = json.loads((self.directory / "CANDIDATE.json").read_bytes())
        if (
            stored.get("kind") != EXEC_KIND
            or stored.get("state") != EXEC_STATE
            or stored.get("authorized") is not False
            or stored.get("attempt_identity") != self.attempt_identity
            or stored.get("correspondence_mode") != self.mode
            or stored.get("package", {}).get("digest") != self.package_digest
            or stored.get("plan", {}).get("pages_count") != self.pages
            or stored.get("plan", {}).get("tiles") != self.tiles
        ):
            raise ValueError("Prepared execution candidate changed")
        return stored

    def metadata(self) -> dict:
        """Sealed staged-execution state (the complete launch record)."""
        self.candidate()
        metadata_path = self.directory / "PRELAUNCH.json"
        metadata = json.loads(metadata_path.read_bytes())
        if sha256(metadata_path) != (self.directory / "PRELAUNCH.sha256").read_text().strip():
            raise ValueError("execution prelaunch seal mismatch")
        if metadata.get("attempt_identity") != self.attempt_identity:
            raise ValueError("prelaunch identity mismatch")
        return metadata

    def expected_argv(self, metadata: dict, config_path: Path) -> tuple[str, ...]:
        """Recompute the exact final argv from the staged identities."""
        workspace_root = Path(metadata["workspace"])
        return execution_argv(
            self.mode,
            config_path,
            metadata["game_port"],
            workspace_root / STAGED_SAVE_NAME if self.mode == SOURCE_SAVE_MODE else None,
        )

    def spec(self) -> PreparedProof:
        """The launch-ready specification the runner opens (no launch here)."""
        metadata = self.metadata()
        workspace = RuntimeWorkspace.reopen(Path(metadata["workspace"]))
        if not workspace.root.is_relative_to(self.directory / "isolated"):
            raise ValueError("Workspace outside preparation")
        return PreparedProof(
            self.directory,
            LaunchSpecification(
                workspace,
                RuntimeIdentity(BINARY.resolve(), "15.3", BINARY_SHA256),
                tuple(metadata["argv"]),
                workspace.root,
                workspace.environment,
                workspace.logs / "stdout.log",
                workspace.logs / "stderr.log",
            ),
            workspace.root / SECRET_NAME,
            metadata["public_key"],
            (metadata["game_port"], metadata["admin_port"]),
        )

    def preflight(self) -> dict:
        """Re-verify every staged seam before any authorization or launch."""
        candidate = self.candidate()
        if candidate.get("native_launches") != 0 or candidate.get("requests_sent") != 0:
            raise PermissionError("An execution candidate must not record its own launch")
        if (self.directory / "CLAIM.json").exists():
            raise ValueError("one-shot claim already written for this execution")
        source_candidate_binding()
        metadata = self.metadata()
        verify_freeze(metadata["frozen"])
        if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
            raise ValueError("Pinned executable/process ownership mismatch")
        mode = self.mode
        if mode not in CORRESPONDENCE_MODES:
            raise ValueError("unknown correspondence mode")
        seams = validate_execution_package(mode)
        if seams["package_digest"] != self.package_digest:
            raise ValueError("Staged execution package composition drifted")
        if seams["package_digest"] != candidate["package"]["digest"]:
            raise ValueError("Candidate package binding drifted")
        workspace = RuntimeWorkspace.reopen(Path(metadata["workspace"]))
        if not workspace.root.is_relative_to(self.directory / "isolated"):
            raise ValueError("Workspace outside preparation")
        name = staged_package_name(mode)
        staged_directory = workspace.game / name
        for file_name, data in execution_package(mode).items():
            if (
                not (staged_directory / file_name).is_file()
                or (staged_directory / file_name).read_bytes() != data
            ):
                raise ValueError(f"Staged package file drift: {file_name}")
        ai_identity = metadata.get("ai_package")
        if ai_identity is not None:
            # A SOURCE_SAVE runtime must reproduce the save's stored AI
            # identity byte-exactly; a drifted staged AI is a corrupted
            # world identity (fail closed like the game package).
            ai_directory = workspace.ai / ai_identity["name"]
            for file_name, entry in sorted(ai_identity["files"].items()):
                staged_file = ai_directory / file_name
                if not staged_file.is_file() or sha256(staged_file) != entry["sha256"]:
                    raise ValueError(f"Staged AI package drift: {file_name}")
        config_path = workspace.config
        if config_path != Path(metadata["config"]):
            raise ValueError("Configured path identity mismatch")
        if sha256(config_path) != metadata["config_sha256"]:
            raise ValueError("Staged configuration digest drift")
        config_text = config_path.read_text()
        for fragment in CONFIG_FRAGMENTS + (
            f"server_admin_port = {metadata['admin_port']}",
            f"server_port = {metadata['game_port']}",
            f"{name} = \n",
        ):
            if fragment not in config_text:
                raise ValueError(f"Missing runtime configuration parameter: {fragment}")
        key_path = workspace.root / SECRET_NAME
        if (
            key_path.is_symlink()
            or key_path.stat().st_mode & 0o777 != 0o600
            or key_path.stat().st_uid != os.getuid()
        ):
            raise ValueError("Private key permissions invalid")
        key = AuthorizedKey.from_bytes(key_path.read_bytes())
        if key.public_hex != metadata["public_key"]:
            raise ValueError("Staged credential identity mismatch")
        graphics = json.loads((self.directory / "graphics-identity.json").read_bytes())
        if graphics["archive_sha256"] != ARCHIVE_SHA256:
            raise ValueError("Official graphics identity mismatch")
        if not (workspace.root / "baseset/OpenGFX").is_dir():
            raise ValueError("Staged graphics assets missing")
        if mode == SOURCE_SAVE_MODE:
            binding = retained_save_binding()
            verify_staged_source_save(binding, workspace.root / STAGED_SAVE_NAME)
            if binding["save_sha256"] != metadata["source"]["save_sha256"]:
                raise ValueError("Staged source-save binding mismatch")
            if json.loads((self.directory / "save-correspondence.json").read_bytes()) != binding:
                raise ValueError("Save correspondence record drifted")
        endpoints = (metadata["game_port"], metadata["admin_port"])
        reservation = EndpointReservation.allocate(*endpoints)
        reservation.close()
        if list(metadata["argv"]) != list(self.expected_argv(metadata, config_path)):
            raise ValueError("Final argv drifted from the sealed executable path")
        plan = request_plan()
        if [hashlib.sha256(payload).hexdigest() for payload in plan] != [
            page["request_payload_sha256"] for page in candidate["plan"]["pages"]
        ]:
            raise ValueError("Classification request plan drifted")
        if len(plan) != self.pages:
            raise ValueError("Prepared page count contradicts the plan")
        return metadata


def _freeze_execution(staged: StagedRuntime, original: Path) -> dict[str, str]:
    """Runtime inventory + staged tree + executable + pinned graphics archive."""
    frozen = source_freeze()
    frozen[str(BINARY.resolve())] = sha256(BINARY)
    frozen[str(GRAPHICS_ARCHIVE.resolve())] = sha256(GRAPHICS_ARCHIVE)
    for path in staged.workspace.root.rglob("*"):
        if path.is_file() and path.name != SECRET_NAME:
            frozen[str(path)] = sha256(path)
    for path in sorted(original.iterdir()):
        if path.is_file():
            frozen[str(path)] = sha256(path)
    return frozen


def prepare_execution(
    directory: Path | None = None, *, mode: str = SOURCE_SAVE_MODE
) -> PreparedExecution:
    """Materialize the executable PENDING_AUTHORIZATION capture candidate."""
    if mode not in CORRESPONDENCE_MODES:
        raise ValueError("unknown correspondence mode")
    if mode != SOURCE_SAVE_MODE:
        raise ValueError("bind the fallback correspondence only with a new reviewed candidate")
    original_directory, stored = source_candidate_binding()
    binding = retained_save_binding()
    seams = validate_execution_package(mode)
    facts = retained_facts()
    welcome = retained_welcome()
    for key in WELCOME_IDENTITY_KEYS:
        if key not in welcome:
            raise ValueError(f"retained welcome record lacks {key!r}")
    plan = request_plan()
    bands: list[list[int]] = []
    for payload in plan:
        request = TileClassificationRequest.parse(payload)
        band = [request.region.x, request.region.y, request.region.width, request.region.height]
        if not bands or bands[-1] != band:
            bands.append(band)
    region = [facts.region.x, facts.region.y, facts.region.width, facts.region.height]
    page_digests = [hashlib.sha256(payload).hexdigest() for payload in plan]
    # The staged AI package is part of the source-save composition identity:
    # it is what lets the engine resolve the save's stored AI natively.
    ai_identity = staged_ai_identity(staged_ai_package_bytes())
    composition_payload = {
        "kind": EXEC_KIND,
        "mode": mode,
        "wire_schema": CLASSIFICATION_SCHEMA_VERSION,
        "package": {"files": seams["files"], "digest": seams["package_digest"]},
        "ai_package": ai_identity,
        "plan": {
            "request_id": CLASSIFICATION_REQUEST_ID,
            "region": region,
            "bands": bands,
            "pages_count": len(plan),
            "tiles": len(facts.tiles),
            "pages": [
                {
                    "index": index,
                    "request_bytes_limit": REQUEST_BYTES_LIMIT,
                    "request_payload_sha256": digest,
                }
                for index, digest in enumerate(page_digests)
            ],
        },
        "retained": {
            "facts_sha256": sha256(SEED17_RUN / "network-facts-0.json"),
            "welcome": {key: welcome[key] for key in WELCOME_IDENTITY_KEYS},
        },
        "source": {
            "directory": str(original_directory),
            "attempt_identity": stored["attempt_identity"],
            "save": {
                "save": binding["save"],
                "save_sha256": binding["save_sha256"],
                "prelaunch_digest": binding["prelaunch_digest"],
                "binary_sha256": binding["binary_sha256"],
                "game_script_name": binding["game_script_name"],
            },
        },
        "binary_sha256": BINARY_SHA256,
        "budgets": budgets(mode),
    }
    composition_identity = hashlib.sha256(
        json.dumps(composition_payload, sort_keys=True).encode()
    ).hexdigest()
    directory = directory or (
        ARTIFACT_ROOT / f"classification-exec-seed17-{composition_identity[:8]}"
    )
    if (directory / "CANDIDATE.json").is_file():
        raise ValueError("execution candidate directory already belongs to a staged attempt")
    directory.mkdir(parents=True, exist_ok=False)
    staged = None
    try:
        staged = stage_runtime(directory, mode=mode)
        arena = {
            **composition_payload,
            "workspace": str(staged.workspace.root),
            "argv": list(staged.argv),
            "game_port": staged.game_port,
            "admin_port": staged.admin_port,
            "config": str(staged.workspace.config),
            "config_sha256": staged.config_sha256,
        }
        attempt_identity = hashlib.sha256(json.dumps(arena, sort_keys=True).encode()).hexdigest()
        candidate = {
            "schema_version": 1,
            "kind": EXEC_KIND,
            "attempt_identity": attempt_identity,
            "composition_identity": composition_identity,
            "state": EXEC_STATE,
            "authorized": False,
            "maximum_launches": 1,
            "native_launches": 0,
            "requests_sent": 0,
            "authorization": (
                "requires ONE fresh operator authorization after preflight; offline staging "
                "consumed no claim and every retained/frozen reference stays untouched"
            ),
            "correspondence_mode": mode,
            "correspondence_rule": (
                "the capture process loads the byte-verified retained source save "
                "(before.sav); the staged composition announces the save's stored "
                "GameScript identity; the observed welcome identity must match the "
                "retained welcome and every classified tile must agree with the retained "
                "TileFact projection before any observation is fused"
            ),
            "alternative_correspondence": persist_same_session_schedule(directory),
            "package": {"files": seams["files"], "digest": staged.package_digest},
            "ai_package": ai_identity,
            "plan": dict(arena["plan"]),
            "budgets": budgets(mode),
            "world_identity_requirements": {
                "welcome_keys": list(WELCOME_IDENTITY_KEYS),
                "retained_welcome": dict(arena["retained"]["welcome"]),
                "retained_facts_sha256": arena["retained"]["facts_sha256"],
            },
            "receipts_required": [
                "one correlation receipt per page binding request bytes to response bytes",
                "one per-page envelope inside the 508-byte response budget",
                "complete in-order page set with no gaps, duplicates or reorderings",
                "complete census bound against the retained TileFact projection "
                "(coherence with every shared predicate bit)",
                "machine-readable completeness summary plus correspondence verdict",
            ],
            "retained_reference": {
                name: {"sha256": sha256(SEED17_RUN / name)}
                for name in (
                    "network-facts-0.json",
                    "runtime-identity.json",
                    "world-planning-observation.json",
                    "random-generation-request.json",
                )
            },
            "launch": {
                "binary": str(BINARY),
                "binary_sha256": BINARY_SHA256,
                "argv": list(staged.argv),
                "config": str(staged.workspace.config),
                "config_sha256": staged.config_sha256,
                "workspace": str(staged.workspace.root),
            },
            "cleanup": list(cleanup_procedure()),
            "connection_requirements": (
                "dedicated server (-D) on freshly reserved localhost endpoints; the "
                "reserved endpoints are sealed into the staged argv and re-verified free "
                "at the preflight",
                "one AdminPort connection; no retries and no reconnects",
                "GameScript bridge exchange only through the staged classification package",
                "no interactive GUI required",
            ),
        }
        write_json(directory / "CANDIDATE.json", candidate)
        write_json(
            directory / "classification-requests.json",
            {
                "request_id": CLASSIFICATION_REQUEST_ID,
                "pages": [
                    {"index": index, "request": payload.decode()}
                    for index, payload in enumerate(plan)
                ],
            },
        )
        write_json(
            directory / "receipts-required.json",
            {
                "pages": len(plan),
                "request_bytes_limit": REQUEST_BYTES_LIMIT,
                "response_bytes_limit": CLASSIFICATION_TOTAL_RESPONSE_BYTES_LIMIT,
                "gsadmin_bytes_per_page": GSADMIN_BYTES,
                "required": candidate["receipts_required"],
            },
        )
        write_json(
            directory / "AUTHORIZATION_REQUIRED.json",
            {
                "state": EXEC_STATE,
                "kind": EXEC_KIND,
                "attempt_identity": attempt_identity,
                "statement": candidate["authorization"],
            },
        )
        save_binding = dict(binding)
        write_json(directory / "save-correspondence.json", save_binding)
        graphics = dict(asdict(staged.graphics), directory=str(staged.graphics.directory))
        write_json(directory / "graphics-identity.json", graphics)
        frozen = _freeze_execution(staged, original_directory)
        write_json(
            directory / "PRELAUNCH.json",
            {
                "schema": PRELAUNCH_SCHEMA,
                "kind": EXEC_KIND,
                "attempt_identity": attempt_identity,
                "correspondence_mode": mode,
                "workspace": str(staged.workspace.root),
                "binary": str(BINARY),
                "binary_sha256": BINARY_SHA256,
                "argv": list(staged.argv),
                "public_key": staged.public_key,
                "game_port": staged.game_port,
                "admin_port": staged.admin_port,
                "config": str(staged.workspace.config),
                "config_sha256": staged.config_sha256,
                "ai_package": ai_identity,
                "plan": {"region": region, "pages_count": len(plan), "tiles": len(facts.tiles)},
                "source": {
                    "save": str(staged.source_save) if staged.source_save else None,
                    "save_sha256": binding["save_sha256"],
                },
                "budgets": budgets(mode),
                "cleanup": list(cleanup_procedure()),
                "authorization": candidate["authorization"],
                "correspondence": {
                    "mode": mode,
                    "statement": (
                        "census runs against the byte-verified retained world state; the "
                        "only accepted deviations are reported, never repaired"
                    ),
                    "save_binding": save_binding,
                },
                "world": {
                    "seed": EXECUTION_SEED,
                    "width": 256,
                    "height": 256,
                    "source": "COPIED_NATIVE_SAVE"
                    if mode == SOURCE_SAVE_MODE
                    else "NATIVE_GENERATION",
                },
                "frozen": frozen,
                "note": "Ports re-verified free before launch; not held across sessions.",
            },
        )
        (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")
        (directory / "artifact-manifest.sha256").write_text(manifest(directory) + "\n")
        return PreparedExecution(
            directory=directory,
            attempt_identity=attempt_identity,
            package_digest=staged.package_digest,
            pages=len(plan),
            tiles=len(facts.tiles),
            mode=mode,
        )
    except BaseException:
        if staged is not None:
            staged.dispose()
        shutil.rmtree(directory, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="stage or re-verify the executable capture candidate"
    )
    parser.add_argument("command", choices=("prepare", "preflight"))
    parser.add_argument("directory")
    args = parser.parse_args()
    directory = Path(args.directory)
    if args.command == "prepare":
        prepared = prepare_execution(directory)
    else:
        prepared = load_execution(directory)
        prepared.preflight()
    print(prepared.attempt_identity)


if __name__ == "__main__":
    main()
