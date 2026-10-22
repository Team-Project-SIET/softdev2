"""D2 bounded clearing native-proof preparation (offline staging only).

Stages ONE fresh save-load clearing composition against the byte-verified
retained Seed 17 source save, pins the clearing target to the sealed census
evidence, and prepares the runner, budgets, receipt contract and cleanup
requirements for ONE future operator-authorized native attempt. Nothing here
launches OpenTTD, connects to any port, or mutates any tile; the staged
pre-launch claim is never written, so nothing can launch until a separate
operator authorization creates it.
"""

import argparse
import ast
import asyncio
import functools
import importlib.machinery
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import sysconfig
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.admin_protocol import AdminFrameDecoder, encode_admin_quit
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptTransport,
    decode_gamescript,
    encode_gamescript,
    gamescript_subscription,
)
from app.simulation.openttd.proof.classification_capture import script_log_health_findings
from app.simulation.openttd.proof.endpoints import kernel_socket_rows, verify_cleanup_endpoints
from app.simulation.openttd.proof.graphics import stage_opengfx
from app.simulation.openttd.proof.harness import (
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
from app.simulation.openttd.proof.native import NativeBackend, matching_processes
from app.simulation.openttd.proof.operator_authorization import (
    AUTHORIZATION_FILE_NAME,
    CLAIM_AUTHORIZATION_EVIDENCE_SCHEMA,
    FORBIDDEN_ENV_KEYS,
    SAFE_ENV_BASELINES,
    ClearingAuthorizationError,
    LaunchGrant,
    grant_launch,
    reverify_launch_grant,
    verify_authorization,
)
from app.simulation.openttd.proof.road_mutation import console, save, wait_log
from app.simulation.openttd.proof.terrain_classification_preparation import SEED17_RUN
from app.simulation.openttd.proof.world_correspondence import (
    SOURCE_SAVE_GS_NAME,
    retained_save_binding,
    verify_staged_source_save,
)
from app.simulation.openttd.runtime.base import LaunchSpecification
from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.secure_admin import AuthState, SecureAdminSession
from app.simulation.openttd.terrain_clearing import (
    ClearingIntent,
    ClearingReadback,
    ClearingRequest,
    admit_clearing,
    verify_clearing,
)
from app.simulation.openttd.tile_classification import TileClassificationResponse

PACKAGES = Path(__file__).resolve().parents[1]
PACK = PACKAGES / "terrain_clearing_package"
CENSUS_DIRECTORY = PROJECT / "artifacts/demos/classification-exec-seed17-3a8f9e46"
CENSUS_TARGET_PAGE = "classification-p034-response.json"
# One independently classified eligible tree tile from the SEALED census page
# of the retained Seed 17 world; the second clear set is never combined here.
TARGET_TILE = 46769
STAGED_GS_DIRECTORY = SOURCE_SAVE_GS_NAME
STAGED_AI_DIRECTORY = "RoadProofCompany"
MAX_CLEARING_COST = 10000

# The staged session uses four sealed exchanges (read, inspect, clear, read)
# plus bounded diagnostic read slack; the handler's own budget stays at 24.
REQUEST_BUDGET = 8

WELCOME_ORDER = ("revision", "dedicated", "seed", "landscape", "start_day", "width", "height")

# Evidence contract version of the staged prelaunch record (BLOCKER 6): the
# v2 schema makes launch authorization evidence (the exact verified
# AUTHORIZATION.json bytes' digest and the operator key identity) part of
# every claim and subject to independent replay verification.
NATIVE_PRELAUNCH_SCHEMA = "d2-clearing-native-prelaunch-v2"

# BLOCKER 6: the staged PRELAUNCH.json digests explicitly pinned as
# historical immutable replay evidence. A candidate that predates the v2
# authorization evidence replays verifiably only when its exact staged
# prelaunch bytes are pinned here in a reviewed change — never through any
# caller-controlled schema string in a candidate directory.
PINNED_HISTORICAL_PRELAUNCH_DIGESTS: frozenset[str] = frozenset()


class ClearingStagingError(ValueError):
    """Offline staging or pin derivation failed; nothing was launched."""


class StopNoMutation(ValueError):
    """The retained world no longer matches its pinned expectation."""


def verify_directory_manifest(directory: Path) -> None:
    for path in sorted(directory.glob("*")):
        if not path.is_file() or path.name == "artifact-manifest.sha256":
            continue
        if sha256(path) not in (directory / "artifact-manifest.sha256").read_text():
            raise ClearingStagingError(f"sealed artifact digest mismatch: {path.name}")


def pinned_target() -> dict:
    """Derive the clearing pin from the sealed census page, proving its seal.

    The pin is evidence, not assume-and-clear: the native runner re-observes
    the tile immediately before admission and stops without any command when
    the live tile does not match this pinned classification and geometry.
    """
    verify_directory_manifest(CENSUS_DIRECTORY)
    page_path = CENSUS_DIRECTORY / CENSUS_TARGET_PAGE
    response = TileClassificationResponse.parse(page_path.read_bytes())
    classes = {
        tile: (tile_class, industry, owner)
        for tile, tile_class, industry, owner in response.classification
    }
    if TARGET_TILE not in response.geometry or TARGET_TILE not in classes:
        raise ClearingStagingError("pinned clearing tile absent from the census page")
    elevation, slope, flags = response.geometry[TARGET_TILE]
    tile_class, industry, owner = classes[TARGET_TILE]
    if tile_class.value != "TREES":
        raise ClearingStagingError("pinned clearing target is not an eligible tree tile")
    if industry is not None or owner != -1:
        raise ClearingStagingError("pinned clearing tile is occupied or owned")
    return dict(
        tile=TARGET_TILE,
        classification=tile_class.value,
        flags=flags,
        elevation=elevation,
        slope=slope,
        owner=owner,
        page=34,
        page_sha256=sha256(page_path),
        verification="sealed census classification-p034 byte evidence",
    )


def retained_welcome() -> dict:
    """The retained world identity requirements from the sealed census record."""
    verify_directory_manifest(CENSUS_DIRECTORY)
    candidate = json.loads((CENSUS_DIRECTORY / "CANDIDATE.json").read_text())
    welcome = candidate["world_identity_requirements"]["retained_welcome"]
    return dict(
        seed=welcome["seed"],
        width=welcome["width"],
        height=welcome["height"],
        landscape=welcome["landscape"],
        revision=welcome["revision"],
        start_day=welcome["start_day"],
    )


def staged_composition() -> tuple[dict[str, bytes], str, int]:
    """Byte-exact save-restore composition for the clearing session.

    The retained staged ``info.nut`` announces the save's stored GameScript
    identity (name/version); the staged main is the D2 clearing handler with
    the save-restore bridge class (NetworkFreightProof) defined inline after
    TerrainClearingProof. No separate identity.nut is needed.
    """
    with zipfile.ZipFile(SEED17_RUN / "frozen-source.zip") as archive:
        info_bytes = archive.read("staged/info.nut")
    text = info_bytes.decode()
    create_instance = re.search(r'CreateInstance\(\)\s*\{\s*return\s+"([^"]+)"', text)
    version = re.search(r"GetVersion\(\)\s*\{\s*return\s+(\d+)", text)
    if create_instance is None or version is None or SOURCE_SAVE_GS_NAME not in text:
        raise ClearingStagingError("retained staged GameScript identity incomplete")
    # Verify the staged main.nut contains the required bridge class.
    main_text = (PACK / "main.nut").read_text()
    bridge_class = create_instance.group(1)
    if f"class {bridge_class} extends TerrainClearingProof" not in main_text:
        raise ClearingStagingError(f"staged main.nut missing required bridge class {bridge_class}")
    return (
        {
            "info.nut": info_bytes,
            "main.nut": (PACK / "main.nut").read_bytes(),
        },
        create_instance.group(1),
        int(version.group(1)),
    )


def staged_save_binding() -> dict:
    if not (SEED17_RUN / "before.sav").is_file():
        raise ClearingStagingError("retained source save missing")
    return retained_save_binding()


D2_CLOSURE_ROOT = "app.simulation.openttd.proof.terrain_clearing"


class D2ClosureError(ValueError):
    """The D2 runtime source closure cannot be enumerated exactly (fail closed)."""


def _d2_effective_closure_root(closure_root: str | None) -> str:
    """None means the module-global D2 closure root, read at call time.

    A default argument would pin the root at import time and break the
    sandboxed closure probes that monkeypatch D2_CLOSURE_ROOT; the sentinel
    keeps the historical no-argument behavior call-time-global while every
    sibling ceremony can pass its own explicit root.
    """
    return D2_CLOSURE_ROOT if closure_root is None else closure_root


def _d2_local_source(path: Path) -> bool:
    """Project-local Python source: under PROJECT, never .venv, never data.

    The historical app/ filter missed project-local roots outside app/
    (BLOCKER counterexample), so the membership test is the whole project
    root with the environment (virtualenv) excluded.
    """
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if resolved.suffix != ".py":
        return False
    if not resolved.is_relative_to(PROJECT):
        return False
    return ".venv" not in resolved.parts


def _d2_dynamic_import_literals(node: ast.AST) -> list[str]:
    """Constant-name dynamic imports: import_module('x') and __import__('x')."""
    if not isinstance(node, ast.Call):
        return []
    function = node.func
    if isinstance(function, ast.Attribute):
        if function.attr != "import_module":
            return []
    elif isinstance(function, ast.Name):
        if function.id not in ("import_module", "__import__"):
            return []
    else:
        return []
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return [node.args[0].value]
    return []


def _d2_computed_dynamic_import(node: ast.AST) -> bool:
    """A dynamic import whose module name is not a constant string (BLOCKER 3).

    ``importlib.import_module<computed>`` and ``__import__<computed>`` sites
    cannot be enumerated; the completed closure would silently omit whatever
    they load, so every one of them must be accounted for by refusal.
    """
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    if isinstance(function, ast.Attribute):
        if function.attr != "import_module":
            return False
    elif isinstance(function, ast.Name):
        if function.id not in ("import_module", "__import__"):
            return False
    else:
        return False
    first = (
        node.args[0]
        if node.args
        else next((keyword.value for keyword in node.keywords if keyword.arg == "name"), None)
    )
    return not (isinstance(first, ast.Constant) and isinstance(first.value, str))


def _d2_filesystem_spec(name: str):
    """Resolve a module name against PROJECT directly, ignoring import state.

    importlib.util.find_spec consults sys.modules and parent ``__path__``
    caches; a stale same-named package left from earlier process state (for
    example sandbox sweeps in a test suite) would hide the files that exist
    now. Project names are therefore resolved here against the project root's
    exact file layout, which is the source of truth for closure membership;
    only names with no such file fall through to the import machinery.
    """
    parts = name.split(".")
    candidate = PROJECT.joinpath(*parts)
    module_file = candidate.with_suffix(".py")
    if module_file.is_file():
        return importlib.machinery.ModuleSpec(name, None, origin=str(module_file.resolve()))
    package_init = candidate / "__init__.py"
    if package_init.is_file():
        return importlib.machinery.ModuleSpec(
            name, None, origin=str(package_init.resolve()), is_package=True
        )
    return None


def _d2_module_spec(name: str):
    """Resolve a module name for the closure walk; None means unresolvable."""
    try:
        return _d2_filesystem_spec(name) or importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None


def _resolve_import_spec(module_spec, node) -> list[str]:
    """Absolute module-name candidates for one AST import node (relative-aware)."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    names = [alias.name for alias in node.names if alias.name != "*"]
    if node.level == 0:
        if not node.module:
            return []
        candidates = [node.module]
        candidates.extend(f"{node.module}.{name}" for name in names)
        return candidates
    if module_spec.submodule_search_locations is not None and module_spec.origin.endswith(
        "__init__.py"
    ):
        # A package's `from . import x` resolves against the package itself.
        base_parts = module_spec.name.split(".")
    else:
        # A plain module's level-1 relative import resolves against the
        # containing package.
        base_parts = module_spec.name.split(".")[:-1]
    for _ in range(node.level - 1):
        base_parts = base_parts[:-1] if base_parts else base_parts
    prefix = f"{'.'.join(base_parts)}." if base_parts else ""
    if node.module:
        return [f"{prefix}{node.module}", *(f"{prefix}{node.module}.{name}" for name in names)]
    return [f"{prefix}{name}" for name in names]


# Observation program for a clean interpreter import of the closure entry.
# Project-local .py files and third-party top-level names are reported; the
# venv is third-party identity and stdlib is ignored entirely.
_D2_OBSERVE_CHILD = """
import json, os, sys
__import__(os.environ["D2_OBSERVE_ENTRY"])
root = os.path.realpath(os.environ["D2_OBSERVE_PROJECT"]) + os.sep
local, third = [], set()
for name, module in sorted(sys.modules.items()):
    file = getattr(module, "__file__", None)
    if not file or not str(file).endswith(".py"):
        continue
    path = os.path.realpath(file)
    if os.sep + ".venv" + os.sep in path:
        third.add(name.split(".")[0])
    elif path.startswith(root):
        local.append(path)
print(json.dumps({"local": sorted(set(local)), "third": sorted(third)}))
"""


@functools.lru_cache(maxsize=8)
def _d2_runtime_observed(cwd: str, closure_root: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Observe one clean interpreter importing the closure entry.

    The subprocess starts with nothing loaded, so its executed module set is
    the true runtime closure (executed parent initializers, dynamic imports)
    plus the third-party tops it actually loaded — the ground truth for
    executable dependency identity (BLOCKER 4). Writes no bytecode caches and
    refuses staging when the entry cannot be imported.
    """
    observation = subprocess.run(
        [sys.executable, "-B", "-c", _D2_OBSERVE_CHILD],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=240,
        env={
            **os.environ,
            "D2_OBSERVE_ENTRY": closure_root,
            "D2_OBSERVE_PROJECT": cwd,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=False,
    )
    if observation.returncode != 0:
        tail = observation.stderr.strip().splitlines()
        raise D2ClosureError(
            f"runtime closure observation failed: {tail[-1] if tail else 'unknown error'}"
        )
    try:
        payload = json.loads(observation.stdout.strip().splitlines()[-1])
        return tuple(payload["local"]), tuple(payload["third"])
    except (ValueError, KeyError) as error:
        raise D2ClosureError(f"unreadable runtime closure observation: {error}") from None


def _d2_initializer_binds(origin: str | Path, attr: str) -> bool:
    """Statically check whether a package's initializer places ``attr``.

    ``from package import attr`` binds a module ``package.attr`` or an object
    already placed in the package namespace. Binding evidence is: a name,
    alias, definition, attribute access or exception target anywhere in the
    initializer, a ``*`` re-export, membership in the initializer's
    ``__all__``, or a module-level ``__getattr__`` (dynamic binding site,
    e.g. pydantic's migration shim). With none of those the from-import is
    required and unresolved, and the closure refuses it.
    """
    try:
        tree = ast.parse(Path(origin).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as error:
        raise D2ClosureError(f"unreadable package initializer {origin}: {error}") from None
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == attr:
            return True
        if isinstance(node, ast.Attribute) and node.attr == attr:
            return True
        if isinstance(node, ast.alias):
            if node.name == "*":
                return True
            bound = node.asname or node.name
            if attr in (bound.split(".")[0], bound.split(".")[-1]):
                return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == attr or node.name == "__getattr__":
                return True
        if isinstance(node, ast.ExceptHandler) and node.name == attr:
            return True
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            in_all = any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in statement.targets
            )
        elif isinstance(statement, ast.AnnAssign):
            in_all = isinstance(statement.target, ast.Name) and statement.target.id == "__all__"
        else:
            continue
        if in_all and any(
            isinstance(element, ast.Constant) and element.value == attr
            for element in ast.walk(statement.value)
        ):
            return True
    return False


def _d2_from_import_targets(module_spec, node) -> tuple[list[str], list[tuple[str, str]]]:
    """Module-name parts plus ``(parent, attr)`` pairs for one from-import."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names], []
    names = [alias.name for alias in node.names if alias.name != "*"]
    if module_spec.submodule_search_locations is not None and module_spec.origin.endswith(
        "__init__.py"
    ):
        base_parts = module_spec.name.split(".")
    else:
        base_parts = module_spec.name.split(".")[:-1]
    for _ in range(node.level - 1):
        base_parts = base_parts[:-1] if base_parts else base_parts
    if node.level == 0:
        if not node.module:
            return [], []
        parts = node.module.split(".")
    else:
        if node.module:
            parts = [*base_parts, *node.module.split(".")]
        else:
            parts = base_parts
    parent = ".".join(parts)
    if not parent:
        return list(names), []
    # Only the parent module is a required target here; each `from parent
    # import attr` site resolves through the attribute/submodule rule in
    # _d2_require_from_import_attr, never through a generic candidate.
    return [parent], [(parent, name) for name in names]


def _d2_require_from_import_attr(parent: str, attr: str, queue: list) -> None:
    """BLOCKER 3: resolve ``from parent import attr`` or refuse the closure.

    ``attr`` must name a submodule of ``parent`` or something the parent's
    Deterministically-positioned initializer actually binds; anything else is
    a required import the closure can neither load nor enumerate, and it
    refuses here — including at deferred (function-scoped) import sites the
    runtime observation never executes.
    """
    parent_spec = _d2_module_spec(parent)
    if parent_spec is None:
        return  # the parent itself is unresolved and fails closed when dequeued
    child = f"{parent}.{attr}"
    if _d2_module_spec(child) is not None:
        queue.append((child, True))
        return
    locations = getattr(parent_spec, "submodule_search_locations", None)
    origin = parent_spec.origin or ""
    if not locations and not origin.endswith("__init__.py"):
        return  # attribute import against a plain module: not a module name
    if not origin:
        raise D2ClosureError(
            f"required import cannot be resolved: {attr!r} in namespace package {parent!r}"
        )
    if _d2_initializer_binds(origin, attr):
        return
    raise D2ClosureError(f"required import cannot be resolved: {child}")


def _d2_import_walk(
    closure_root: str | None = None,
) -> tuple[dict[str, Path], list[str], set[str]]:
    """Iterative AST closure walk from the runner entry module.

    Queues every locally-resolved import — transitive, conditional (nested
    inside functions and guards) and constant-name dynamic literals
    (import_module/`__import__`) — plus every executed parent package
    initializer of each reached module, because importing `a.b.c` executes
    `a`, `a.b` and `a.b.c`'s initializer. Each locally-resolved import that
    lives outside this project is recorded as an external dependency name;
    a dynamic import literal that resolves nowhere fails closed. BLOCKER 3:
    every required static import (top-level or deferred) must resolve, every
    from-import must name a real submodule or an initializer binding, and a
    dynamic import site with a computed name refuses the whole walk.
    """
    closure_root = _d2_effective_closure_root(closure_root)
    seen: dict[str, Path] = {}
    flagged: list[str] = []
    externals: set[str] = set()
    dynamic_literals: set[str] = set()
    queue: list[tuple[str, bool]] = [(closure_root, True)]
    while queue:
        name, required = queue.pop()
        if name in seen:
            continue
        spec = _d2_filesystem_spec(name)
        if spec is None:
            try:
                spec = importlib.util.find_spec(name)
            except (ImportError, ValueError):
                spec = None
        if spec is None or not spec.origin:
            if spec is None:
                if name in dynamic_literals:
                    raise D2ClosureError(f"unresolvable dynamic import: {name}")
                if required:
                    raise D2ClosureError(f"required import cannot be resolved: {name}")
                continue
            continue  # resolvable namespace package: no file origin to enumerate
        path = Path(spec.origin).resolve()
        if not _d2_local_source(path):
            externals.add(name)
            continue
        seen[name] = path
        parts = name.split(".")
        queue.extend((".".join(parts[:index]), True) for index in range(1, len(parts)))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            attr_sites: list[tuple[str, str]] = []
            candidates: list[str]
            dynamic = False
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                candidates, attr_sites = _d2_from_import_targets(spec, node)
            elif isinstance(node, ast.Call):
                candidates = _d2_dynamic_import_literals(node)
                dynamic = bool(candidates)
                if not candidates and _d2_computed_dynamic_import(node):
                    raise D2ClosureError(
                        "computed dynamic import must be accounted for: "
                        f"{spec.origin}:{node.lineno}"
                    )
                dynamic_literals.update(candidates)
            else:
                continue
            if node.col_offset > 0:
                flagged.extend(candidates)
                flagged.extend(f"{parent}.{attr}" for parent, attr in attr_sites)
            for parent, attr in attr_sites:
                _d2_require_from_import_attr(parent, attr, queue)
            queue.extend((candidate, not dynamic) for candidate in candidates if candidate)
    return seen, flagged, externals


def d2_source_closure(closure_root: str | None = None) -> dict[str, str]:
    """SHA-256 inventory of every local module the D2 execution path executes.

    The static walk (transitive, conditional and dynamic-literal imports, and
    every executed parent package initializer) is unioned with the executed
    module set observed in a clean interpreter import of the entry, so both
    documented incompleteness modes are covered. The historical shared
    source_freeze() contract is untouched and only extended here, and
    verify_freeze keeps verifying byte-exact content of every listed path.
    Stdlib, site-packages and data artifacts stay environment identity.
    """
    closure_root = _d2_effective_closure_root(closure_root)
    seen, _, _ = _d2_import_walk(closure_root)
    observed_local, _ = _d2_runtime_observed(str(PROJECT), closure_root)
    paths = {*(path for path in seen.values()), *(Path(path) for path in observed_local)}
    selected = sorted({path for path in paths if _d2_local_source(path)})
    return {str(path): sha256(path) for path in selected}


def d2_conditionally_imported(closure_root: str | None = None) -> set[str]:
    """Local modules imported below module top level in the closure."""
    closure_root = _d2_effective_closure_root(closure_root)
    _, flagged, _ = _d2_import_walk(closure_root)
    resolved: set[str] = set()
    for name in flagged:
        spec = _d2_module_spec(name)
        if spec is None or not spec.origin:
            continue
        path = Path(spec.origin).resolve()
        if not _d2_local_source(path):
            continue
        resolved.add(name)
    return resolved


def require_frozen_d2_closure(
    frozen: dict[str, str], closure_root: str | None = None
) -> None:
    """Refuse anything whose staged freeze misses the exact runtime closure."""
    missing = [
        module_path for module_path in d2_source_closure(closure_root) if module_path not in frozen
    ]
    if missing:
        lacking = ", ".join(Path(module_path).name for module_path in sorted(missing))
        raise ValueError(f"D2 runtime source closure is not frozen: {lacking}")


# BLOCKER 4: imports determine names; distributions determine executable
# bytes. These top-level modules are the independently confirmed loaded
# implementations (pydantic validation, pydantic_core native extension and
# the ortools solver stack with protobuf and abseil reachable from the
# planning optimizer); every other runtime-observed or statically imported
# third-party top — including the native transitive loads a deferred import
# independently triggers (numpy, pandas through the ortools solver stack) —
# joins the set through the same recording mechanism.
PINNED_EXECUTION_DEPENDENCY_TOPS = ("pydantic", "pydantic_core", "ortools", "google", "absl")

# Observation program for the native dependency surface (BLOCKER 4): every
# third-party module the static walk resolved but the entry import did not
# execute is imported here in a clean interpreter, and the native extension
# (.so) tops its loads actually implement are reported — the transitive
# native dependency identity no import-level recording reaches on its own.
_D2_NATIVE_OBSERVE_CHILD = """
import importlib, json, os, sys
for name in json.loads(os.environ["D2_OBSERVE_THIRDS"]):
    importlib.import_module(name)
native_tops = set()
for name, module in list(sys.modules.items()):
    file = getattr(module, "__file__", None)
    if file and str(file).endswith(".so"):
        native_tops.add(name.split(".")[0])
print(json.dumps({"native_tops": sorted(native_tops)}))
"""


@functools.lru_cache(maxsize=8)
def _d2_dependency_native_observation(cwd: str, closure_root: str) -> tuple[str, ...]:
    """Independently observe the native extensions the closure can load.

    A clean child interpreter imports every third-party module name the
    static walk resolved that the runtime observation did not execute
    (deferred imports such as the ortools solver modules), and reports the
    native extension tops those loads implement (numpy, pandas and their
    transitive loads). Failing the probe — an unloadable third-party module
    among the resolved ones — is an environment the dependency identity of
    which cannot be verified, so staging refuses (fail closed).
    """
    _, _, externals = _d2_import_walk(closure_root)
    _, observed_third = _d2_runtime_observed(cwd, closure_root)
    stdlib = set(sys.stdlib_module_names)
    executed = set(observed_third)
    probe = sorted(
        name
        for name in externals
        if name.split(".")[0] not in stdlib and name.split(".")[0] not in executed
    )
    if not probe:
        return ()
    observation = subprocess.run(
        [sys.executable, "-B", "-c", _D2_NATIVE_OBSERVE_CHILD],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=240,
        env={
            **os.environ,
            "D2_OBSERVE_THIRDS": json.dumps(probe),
            "D2_OBSERVE_PROJECT": cwd,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=False,
    )
    if observation.returncode != 0:
        tail = observation.stderr.strip().splitlines()
        raise D2ClosureError(
            f"native dependency observation failed: {tail[-1] if tail else 'unknown error'}"
        )
    try:
        payload = json.loads(observation.stdout.strip().splitlines()[-1])
        return tuple(payload["native_tops"])
    except (ValueError, KeyError) as error:
        raise D2ClosureError(f"unreadable native dependency observation: {error}") from None


def _d2_unowned_top_files(top: str) -> set[Path]:
    """Pin the installed files of a third-party top no RECORD dist owns.

    Ownership metadata is best-effort: an observed dependency top without an
    owning distribution (a private native alias, the venv bootstrap module)
    cannot be trusted as covered-by-RECORD, so its exact installed bytes
    join the freeze instead. A top that cannot be located or enumerated at
    all is an unresolvable ownership gap and refuses staging (fail closed).
    """
    spec = _d2_module_spec(top)
    files: set[Path] = set()
    if spec is not None and spec.submodule_search_locations:
        for location in spec.submodule_search_locations:
            for path in Path(location).rglob("*"):
                if path.is_file() and path.suffix != ".pyc":
                    files.add(path.resolve())
    elif spec is not None and spec.origin:
        files.add(Path(spec.origin).resolve())
    if not files:
        raise ClearingStagingError(f"unowned dependency top cannot be pinned: {top}")
    return files


@functools.lru_cache(maxsize=8)
def _d2_dependency_distributions(
    cwd: str, closure_root: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Third-party distributions owning the closure's executable imports.

    Returns the owned distribution names and the unowned third-party tops:
    a dependency top that no distribution RECORD owns (a private native
    alias such as `_cyutility`, or the venv bootstrap module) is an
    ownership gap, never silently skipped — BLOCKER 4 pins its files
    directly instead, refusing staging when that fails.
    """
    tops = set(PINNED_EXECUTION_DEPENDENCY_TOPS)
    _, _, externals = _d2_import_walk(closure_root)
    stdlib = set(sys.stdlib_module_names)
    tops.update(name.split(".")[0] for name in externals if name.split(".")[0] not in stdlib)
    _, observed_third = _d2_runtime_observed(cwd, closure_root)
    tops.update(observed_third)
    tops.update(_d2_dependency_native_observation(cwd, closure_root))
    distributions_to_tops = importlib.metadata.packages_distributions()
    distributions: set[str] = set()
    unowned: set[str] = set()
    for top in sorted(tops):
        owners = distributions_to_tops.get(top)
        if owners:
            distributions.update(owners)
        else:
            unowned.add(top)
    return tuple(sorted(distributions)), tuple(sorted(unowned))


def d2_dependency_inventory(closure_root: str | None = None) -> dict[str, str]:
    """SHA-256 of the exact executable bytes of every owned distribution.

    Every file a distribution's RECORD declares (bytecode caches excluded)
    joins the staged freeze: pydantic and the pydantic_core native extension,
    the ortools solver stack with protobuf and abseil, the pinned monocypher
    binding's distribution companions, every other distribution the D2
    execution path actually imports (statically or at runtime or through the
    independently observed transitive native loads: numpy, pandas), the
    loadable unowned extension modules and every importable native
    ``.so`` file at the site-packages root. Package names and versions are
    not identity: the exact installed bytes are hashed, and any distribution
    whose RECORD is missing, whose declared installed file identity is
    absent, or whose owned top cannot be pinned refuses staging (BLOCKER 4).
    """
    closure_root = _d2_effective_closure_root(closure_root)
    paths: set[Path] = set()
    distributions, unowned = _d2_dependency_distributions(str(PROJECT), closure_root)
    for name in distributions:
        dist = importlib.metadata.distribution(name)
        if dist.files is None:
            raise ClearingStagingError(f"distribution RECORD missing for {name}")
        for declared in dist.files:
            if declared.name.endswith(".pyc"):
                continue
            path = Path(dist.locate_file(declared)).resolve()
            if not path.is_file():
                raise ClearingStagingError(
                    f"installed-file identity missing for {name}: {declared}"
                )
            paths.add(path)
    for top in unowned:
        paths.update(_d2_unowned_top_files(top))
    root = Path(sysconfig.get_paths()["purelib"])
    if root.is_dir():
        paths.update(loose.resolve() for loose in root.glob("*.so"))
    return {str(path): sha256(path) for path in sorted(paths)}


def require_frozen_d2_dependencies(
    frozen: dict[str, str], closure_root: str | None = None
) -> None:
    """Refuse any staged freeze missing exact installed dependency bytes."""
    missing = [path for path in d2_dependency_inventory(closure_root) if path not in frozen]
    if missing:
        lacking = ", ".join(Path(path).name for path in sorted(missing)[:8])
        raise ValueError(f"D2 execution dependencies are not frozen: {lacking}")


def admit_pinned_target(
    before: ClearingReadback,
    *,
    pinned: dict,
    prelaunch_digest: str,
    source_save_digest: str,
    max_cost: int,
):
    """Admission against the immediate native re-observation of the pin.

    Guards the live readback against the pinned classification/geometry byte
    facts before delegating to the D2 admission contract. Any mismatch stops
    the attempt without a demolition command.
    """
    if (
        before.op != "inspect"
        or before.tile != pinned["tile"]
        or before.classification.value != pinned["classification"]
        or before.flags != pinned["flags"]
        or (before.elevation, before.slope) != (pinned["elevation"], pinned["slope"])
        or before.owner != pinned["owner"]
    ):
        raise StopNoMutation(
            "target no longer matches its pinned expected classification: "
            f"live={before.classification.value} flags={before.flags} "
            f"geometry=({before.elevation},{before.slope}) owner={before.owner} "
            f"pinned={pinned!r}"
        )
    return admit_clearing(
        before,
        prelaunch_digest=prelaunch_digest,
        source_save_digest=source_save_digest,
        max_cost=max_cost,
    )


class ClearingSecureSession(SecureAdminSession):
    """Only the three clearing operations extend the secure write policy."""

    def validate_outbound(self, frame: bytes) -> None:
        if self.state is not AuthState.ACTIVE:
            raise ValueError("encrypted ACTIVE stream required")
        if len(frame) < 3 or struct.unpack_from("<H", frame)[0] != len(frame):
            raise ValueError("invalid frame")
        if frame[2] == ADMIN_GAMESCRIPT:
            request = ClearingRequest.model_validate_json(decode_gamescript(frame[3:]))
            request.to_bytes()
        elif frame not in (gamescript_subscription(), encode_admin_quit()):
            super().validate_outbound(frame)


class ClearingNativeBackend(NativeBackend):
    """One-launch backend whose launch boundary is the staged clearing argv."""

    # The lineage schema string written into the LAUNCH-CONSUMED.json marker
    # (call-time class attribute; sibling ceremonies override it, the
    # historical D2 backend keeps the unchanged default below).
    launch_marker_schema = "d2-clearing-native-launch-consumed"

    def validate_launch(self, prepared: PreparedProof) -> None:
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        if prepared.spec.argv != tuple(metadata["argv"]):
            raise ClearingAuthorizationError("clearing launch argv drifted from its seal")
        if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
            raise ClearingAuthorizationError("pinned executable/process ownership mismatch")

    async def launch(self, prepared: PreparedProof, *, authorization=None) -> None:
        """BLOCKER 1/5: the sole boundary immediately before the process seam.

        Nothing at this seam is trusted: the grant must exist and be minted by
        verify_authorization, must bind exactly this candidate identity and
        seal, must match the retained claim's authorization story, must still
        verify byte-for-byte against the currently anchored operator key, and
        the staged runtime identity (frozen bytes, launch-critical stat
        identity, argv, working directory, clean environment) must equal what
        was authorized. Only then is the one-shot grant consumed and the real
        launch performed with the exact authorized environment — never an
        inherited host environment.
        """
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        seal = sha256(prepared.directory / "PRELAUNCH.json")
        if not isinstance(authorization, LaunchGrant):
            raise ClearingAuthorizationError(
                "the process boundary requires an operator-issued launch grant"
            )
        if (
            Path(prepared.directory).resolve() != authorization.directory
            or authorization.prelaunch_sha256 != seal
        ):
            raise ClearingAuthorizationError("the launch grant never authorized this candidate")
        claim = json.loads((prepared.directory / "CLAIM.json").read_text())
        if (
            claim.get("prelaunch_digest") != seal
            or claim.get("consumed") is not True
            or claim.get("authorization_schema") != CLAIM_AUTHORIZATION_EVIDENCE_SCHEMA
            or claim.get("authorization_sha256") != authorization.authorization_sha256
            or claim.get("operator_key_identity") != authorization.operator_key_identity
        ):
            raise ClearingAuthorizationError(
                "the retained claim does not carry this grant's authorization story"
            )
        # BLOCKER 6 at the boundary: the claim must also be the complete
        # one-shot record the ceremony writes; missing consumption flags or
        # expanded launch/retry allowances refuse the launch.
        one_shot_state = incomplete_one_shot_state(claim)
        if one_shot_state is not None:
            raise ClearingAuthorizationError(
                f"the retained claim is not a complete one-shot claim: {one_shot_state}"
            )
        # The exact verified record bytes re-verify here; a rotated, removed
        # or swapped anchor, a replaced payload or a broken signature refuses
        # everything a second time.
        reverify_launch_grant(prepared.directory, authorization, metadata, seal)
        self.validate_launch(prepared)
        # Verification-to-launch gap: the frozen staged bytes are re-hashed at
        # this exact seam and the stat identity (mode, size, mtime, owner) of
        # every launch-critical file must equal the snapshot bound at grant
        # time — no staged substitution survives either check.
        verify_freeze(metadata["frozen"])
        identity = launch_critical_identity(prepared, metadata)
        if authorization.launch_identity is None or identity != authorization.launch_identity:
            raise ClearingAuthorizationError(
                "launch-critical files changed after authorization was verified"
            )
        working = Path(prepared.spec.cwd).resolve()
        if working != Path(prepared.spec.workspace.root).resolve():
            raise ClearingAuthorizationError(
                "the launch working directory is not the owned staged workspace"
            )
        if working != Path(metadata["workspace"]).resolve():
            raise ClearingAuthorizationError(
                "the launch working directory drifted from the sealed workspace"
            )
        # BLOCKER 5: the approved launch environment is sealed in the staged
        # prelaunch facts and therefore operator-authorized through the
        # prelaunch digest the record binds. The authorization-bound launch
        # never falls back to an assembled environment: the exact approved
        # environment hands off to the seam, so no host drift, no unapproved
        # variable and no replacement can survive this gate.
        approved_environment = metadata.get("environment")
        approved_overrides = metadata.get("environment_overrides")
        if not isinstance(approved_environment, dict) or not isinstance(approved_overrides, dict):
            raise ClearingAuthorizationError(
                "the staged approval does not seal a launch environment"
            )
        if any(
            not isinstance(name, str) or not isinstance(value, str)
            for name, value in (*approved_environment.items(), *approved_overrides.items())
        ):
            raise ClearingAuthorizationError("the sealed launch environment is malformed")
        if sorted(set(approved_environment) & FORBIDDEN_ENV_KEYS):
            raise ClearingAuthorizationError("the sealed launch environment carries injection keys")
        if dict(prepared.spec.environment) != approved_overrides:
            raise ClearingAuthorizationError(
                "launch environment overrides are not exactly the approved overrides"
            )
        require_clean_launch_environment()
        # BLOCKER 1: candidate-wide one-launch consumption. The attempt is
        # consumed here — atomically, across every grant, backend instance
        # and process on the candidate directory — and never by an
        # incidental output-file collision downstream.
        record_boundary_consumption(
            prepared, authorization, seal, marker_schema=self.launch_marker_schema
        )
        authorization.consume()
        await super().launch(prepared, env={**approved_environment})

    async def connect(self, prepared: PreparedProof, *, frame_observer) -> ClearingSecureSession:
        """Bind the staged runtime's Admin listener to one owned secure session."""
        if not any(
            r["table"] == "tcp" and r["local_port"] == prepared.endpoints[1] and r["state"] == 10
            for r in kernel_socket_rows()
        ):
            raise ValueError("native Admin listener readiness absent")
        key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
        session = await ClearingSecureSession.connect_secure(
            "127.0.0.1",
            prepared.endpoints[1],
            5,
            key=key,
            frame_observer=frame_observer,
        )
        self.session = session
        return session


def prepare_candidate(directory: Path) -> PreparedProof:
    """Stage the fresh save-load clearing composition; no process or connection."""
    if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
        raise ClearingStagingError("pinned binary / exclusive runtime gate failed")
    directory = directory.resolve()
    pin = pinned_target()
    binding = staged_save_binding()
    retention = SEED17_RUN / "before.sav"
    if sha256(retention) != binding["save_sha256"]:
        raise ClearingStagingError("retained source save digest mismatch")
    welcome = retained_welcome()
    directory.mkdir(parents=True, exist_ok=False)
    workspace = RuntimeWorkspace.create(directory / "isolated", retain=True)
    reservation = EndpointReservation.allocate()
    try:
        key = AuthorizedKey.generate()
        key_path = workspace.root / ".admin-secret"
        with os.fdopen(os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as f:
            f.write(key._secret)
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
        # Save-load composition: no [game_creation] block; the queued source
        # save provides the world. Staged scripts announce retained identities.
        config += (
            "\n[ai]\nai_in_multiplayer = true\n[misc]\ngraphicsset = OpenGFX\n"
            f"[game_scripts]\n{STAGED_GS_DIRECTORY} = \n"
        )
        workspace.config.write_text(config)
        graphics = stage_opengfx(
            PROJECT / "artifacts/runtime/verified-assets/opengfx-8.0-all.zip",
            workspace.root / "baseset/OpenGFX",
        )
        write_json(
            directory / "graphics-identity.json",
            dict(asdict(graphics), directory=str(graphics.directory)),
        )
        staged_save = workspace.root / "source.sav"
        shutil.copyfile(retention, staged_save)
        verify_staged_source_save(binding, staged_save)
        (workspace.game / STAGED_GS_DIRECTORY).mkdir()
        composition, create_instance, version = staged_composition()
        for name in ("info.nut", "main.nut"):
            (workspace.game / STAGED_GS_DIRECTORY / name).write_bytes(composition[name])
        (workspace.ai / STAGED_AI_DIRECTORY).mkdir()
        for name in ("info.nut", "main.nut"):
            shutil.copyfile(
                PACKAGES / "road_company_package" / name,
                workspace.ai / STAGED_AI_DIRECTORY / name,
            )
        argv = (
            str(BINARY),
            f"-D127.0.0.1:{reservation.game_port}",
            "-c",
            str(workspace.config),
            "-x",
            "-X",
            "-g",
            str(staged_save),
            "-dscript=4,grf=1,net=3",
        )
        spec = LaunchSpecification(
            workspace,
            RuntimeIdentity(BINARY.resolve(), "15.3", BINARY_SHA256),
            argv,
            workspace.root,
            workspace.environment,
            workspace.logs / "stdout.log",
            workspace.logs / "stderr.log",
        )
        frozen = source_freeze()
        for source in (PACKAGES / "terrain_clearing_package", PACKAGES / "road_company_package"):
            for path in source.glob("*.nut"):
                frozen[str(path.resolve())] = sha256(path)
        frozen.update(
            {
                str(p): sha256(p)
                for p in workspace.root.rglob("*")
                if p.is_file() and p.name != ".admin-secret"
            }
        )
        # BLOCKER 3 + 4: the D2 runtime source closure (planning DTOs, the
        # canonicalization module, the retained world generation module,
        # every executed package initializer, dynamic and conditional
        # imports) and the exact installed dependency bytes (pydantic,
        # pydantic_core, ortools and every other runtime-reachable third
        # party distribution) join the shared historical source_freeze()
        # contract, never weakening it.
        frozen.update(d2_source_closure())
        frozen.update(d2_dependency_inventory())
        prepared = PreparedProof(
            directory,
            spec,
            key_path,
            key.public_hex,
            (reservation.game_port, reservation.admin_port),
        )
        metadata = dict(
            schema=NATIVE_PRELAUNCH_SCHEMA,
            attempt="D2-CLEARING-1",
            workspace=str(workspace.root),
            binary_sha256=BINARY_SHA256,
            argv=list(argv),
            public_key=key.public_hex,
            game_port=reservation.game_port,
            admin_port=reservation.admin_port,
            world=dict(
                mode="RETAINED_SOURCE_SAVE_LOAD",
                retained_directory=str(SEED17_RUN),
                source_save="before.sav",
                save_sha256=binding["save_sha256"],
                qualified_save_sha256=binding.get("qualified_save_sha256"),
                expected_welcome=welcome,
            ),
            game_script_identity=dict(
                name=SOURCE_SAVE_GS_NAME,
                version=version,
                create_instance=create_instance,
                statement=(
                    "the staged composition announces the save's stored GameScript "
                    "name/version from the retained frozen-source evidence; the "
                    "D2 clearing handler runs as the retained CreateInstance subclass"
                ),
            ),
            save_policy=(
                "owned session-before.sav and after.sav only; the retained "
                "source save and every historical artifact stay untouched"
            ),
            plan_policy=dict(
                company=0,
                target_tile=TARGET_TILE,
                pinned=pin,
                max_cost=MAX_CLEARING_COST,
                command="GSTile.DemolishTile(tile)",
                stale_rule=(
                    "re-observe the target immediately before admission; any "
                    "pin mismatch stops the attempt without any command"
                ),
                identity=(
                    "wire contract v2: the clear request plan must equal the "
                    "inspect plan that latched its admission; the handler "
                    "compares it at the mutation boundary before DemolishTile"
                ),
            ),
            expected_readback=dict(
                before=(
                    "read-0 observes; inspect-1 returns READY with the pinned "
                    "TREES classification, geometry and unowned owner"
                ),
                after=(
                    "read-2 returns READ with CLEAR classification, unchanged "
                    "geometry, unowned owner and no industry pointer"
                ),
                independent_query="read operation after the single clear request",
                receipt="plan-bound only after the clear result and independent readback agree",
            ),
            bootstrap_command=f"start_ai {STAGED_AI_DIRECTORY}",
            execution_command=[
                str(PROJECT / ".venv/bin/python"),
                "-m",
                "app.simulation.openttd.proof.terrain_clearing",
                "run",
                str(directory),
            ],
            budgets=dict(
                launches=1,
                connection_attempts=1,
                requests=REQUEST_BUDGET,
                real_clears=1,
                response_bytes=512,
                gsadmin_bytes=1450,
                retries=0,
                reconnects=0,
                readiness_seconds=45,
                request_seconds=10,
                total_seconds=180,
            ),
            cleanup=[
                "close secure session",
                "quit and reap process",
                "verify endpoints",
                "retain session logs and saves",
                "remove credential",
                "dispose owned workspace",
                "never modify the retained save or any historical artifact",
            ],
            authorization=(
                "PENDING — requires ONE fresh operator authorization after all "
                "preflight gates; offline staging consumed no claim and no "
                "authorization file exists"
            ),
            pin_provenance=dict(
                source=CENSUS_DIRECTORY.name,
                manifest_verified=True,
                statement=(
                    "pin derives from the sealed census classification page; "
                    "the second Seed 17 clear set is not part of this candidate"
                ),
            ),
            # BLOCKER 5: the approved launch environment joins the sealed
            # prelaunch facts — the exact baseline-plus-override environment
            # computed from the stage itself and the exact approved spec
            # overrides. The operator authorization binds the prelaunch
            # digest, so these keys are operator-authorized too, and the
            # launch boundary refuses any drift or replacement of either.
            environment=launch_environment(prepared),
            environment_overrides=dict(spec.environment),
            frozen=frozen,
        )
        write_json(directory / "PRELAUNCH.json", metadata)
        (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")
        return prepared
    finally:
        reservation.close()


def reopen(directory: Path) -> PreparedProof:
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    workspace = RuntimeWorkspace.reopen(Path(metadata["workspace"]))
    spec = LaunchSpecification(
        workspace,
        RuntimeIdentity(BINARY.resolve(), "15.3", BINARY_SHA256),
        tuple(metadata["argv"]),
        workspace.root,
        workspace.environment,
        workspace.logs / "stdout.log",
        workspace.logs / "stderr.log",
    )
    return PreparedProof(
        directory,
        spec,
        workspace.root / ".admin-secret",
        metadata["public_key"],
        (metadata["game_port"], metadata["admin_port"]),
    )


def preflight(prepared: PreparedProof) -> dict:
    """Offline launch-boundary rehearsal; opens nothing, consumes nothing."""
    directory = prepared.directory
    if sha256(directory / "PRELAUNCH.json") != (directory / "PRELAUNCH.sha256").read_text().strip():
        raise ValueError("prelaunch seal mismatch")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    if (directory / "CLAIM.json").exists():
        raise ValueError("one native attempt already consumed")
    verify_freeze(metadata["frozen"])
    require_frozen_d2_closure(metadata["frozen"])
    require_frozen_d2_dependencies(metadata["frozen"])
    if metadata["plan_policy"]["pinned"] != pinned_target():
        raise ValueError("sealed clearing pin drifted from the census evidence")
    if metadata["world"]["expected_welcome"] != retained_welcome():
        raise ValueError("retained world identity requirements drifted")
    binding = staged_save_binding()
    if metadata["world"]["save_sha256"] != binding["save_sha256"]:
        raise ValueError("retained source save binding drifted")
    verify_staged_source_save(binding, Path(metadata["workspace"]) / "source.sav")
    composition, _, _ = staged_composition()
    staged_info = Path(metadata["workspace"]) / "game" / STAGED_GS_DIRECTORY / "info.nut"
    if staged_info.read_bytes() != composition["info.nut"]:
        raise ValueError("staged GameScript identity drifted from the retained composition")
    if not prepared.spec.workspace.root.is_relative_to(directory / "isolated"):
        raise ValueError("workspace ownership mismatch")
    ClearingNativeBackend(authorized_one_launch=True).preflight(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    reservation.close()
    return metadata


def launch_critical_identity(
    prepared: PreparedProof, metadata: dict
) -> dict[str, tuple[int, int, int, int]]:
    """Stat identity of every launch-critical staged byte (BLOCKER 5).

    Content is verified by digest at the launch boundary; the stat identity
    additionally pins mode, size, mtime and owner of every frozen path and
    the executable, so a substitution between verification and launch —
    including an ownership transfer — is detectable at the exact Popen seam.
    """
    identity: dict[str, tuple[int, int, int, int]] = {}
    candidates = {BINARY, *(Path(path) for path in metadata["frozen"])}
    for path in sorted(candidates, key=str):
        try:
            stat = path.stat()
        except OSError:
            raise ClearingAuthorizationError(f"launch-critical file missing: {path}") from None
        identity[str(path.resolve())] = (
            stat.st_mode,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_uid,
        )
    return identity


def require_clean_launch_environment() -> None:
    """The runner environment must not carry loader/interpreter injection."""
    injected = sorted(set(os.environ) & FORBIDDEN_ENV_KEYS)
    if injected:
        raise ClearingAuthorizationError(
            f"injected environment present at launch: {', '.join(injected)}"
        )


def launch_environment(prepared: PreparedProof) -> dict[str, str]:
    """The exact authorized launch environment: allowlist plus overrides.

    The process gets nothing inherited except the safe baseline (PATH, LANG,
    LC_ALL, LC_CTYPE, TMPDIR) merged with the owned workspace overrides —
    LD_PRELOAD-class injection keys are refused before anything is spawned.
    """
    require_clean_launch_environment()
    environment = {name: os.environ[name] for name in sorted(set(os.environ) & SAFE_ENV_BASELINES)}
    for name, value in prepared.spec.environment:
        environment[name] = value
    injected = sorted(set(environment) & FORBIDDEN_ENV_KEYS)
    if injected:
        raise ClearingAuthorizationError(f"launch environment is not clean: {', '.join(injected)}")
    return environment


def incomplete_one_shot_state(claims: dict) -> str | None:
    """BLOCKER 6: the retained claim must be complete, consumed and one-shot.

    Returns the refusal state the claim carries — missing or false
    consumption, missing allowance fields, or any expansion of the single
    launch and zero-retry allowance — or None when the claim is the exact
    record the launch ceremony writes.
    """
    if claims.get("consumed") is not True:
        return "NOT_CONSUMED"
    if "launches_allowed" not in claims or "retries" not in claims:
        return "INCOMPLETE_CLAIM"
    if claims.get("launches_allowed") != 1 or claims.get("retries") != 0:
        return "ONE_SHOT_ALLOWANCE_EXPANDED"
    return None


def record_boundary_consumption(
    prepared: PreparedProof,
    authorization: LaunchGrant,
    seal: str,
    *,
    marker_schema: str = "d2-clearing-native-launch-consumed",
) -> None:
    """Atomically consume the candidate's single native launch (BLOCKER 1).

    The launch marker's exclusive creation is the candidate-wide gate: any
    second grant on any second backend instance — or any second process on
    the same staged directory — refuses here, at the designed process
    boundary, instead of racing to the Popen seam. The retained marker
    records which grant consumed the launch. The marker schema defaults to
    the historical D2 lineage string; sibling ceremonies carry their own
    lineage marker through :attr:`ClearingNativeBackend.launch_marker_schema`.
    """
    marker = prepared.directory / "LAUNCH-CONSUMED.json"
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ClearingAuthorizationError(
            "this candidate's single native launch was already consumed at the process boundary"
        ) from None
    with os.fdopen(fd, "w") as stream:
        stream.write(
            json.dumps(
                dict(
                    schema=marker_schema,
                    prelaunch_digest=seal,
                    authorization_sha256=authorization.authorization_sha256,
                    operator_key_identity=authorization.operator_key_identity,
                ),
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )


def claim_status(directory: Path) -> str:
    path = directory / "CLAIM.json"
    if not path.exists():
        return "ABSENT"
    claim = json.loads(path.read_text())
    if (
        claim.get("prelaunch_digest") == sha256(directory / "PRELAUNCH.json")
        and claim.get("consumed") is True
    ):
        return "CONSUMED"
    raise ValueError("retained claim does not match the staged prelaunch seal")


async def exchange(session, request, directory: Path, *, response_type=ClearingReadback):
    raw = request.to_bytes()
    (directory / (request.request_id + "-request.json")).write_bytes(raw)
    await session.send(encode_gamescript(raw))
    decoder = AdminFrameDecoder()
    async with asyncio.timeout(10):
        while True:
            chunk = await session.receive()
            if not chunk:
                raise ConnectionError("clearing proof stream disconnected")
            for kind, payload in decoder.feed_frames(chunk):
                if kind != SERVER_GAMESCRIPT:
                    raise ValueError("unexpected clearing-proof packet")
                response = decode_gamescript(payload)
                (directory / (request.request_id + "-response.json")).write_bytes(response)
                return response_type.parse_for(request, response)


async def run(prepared: PreparedProof) -> dict:
    """Execute the authorized one-attempt clearing ceremony (never run offline)."""
    backend = ClearingNativeBackend(authorized_one_launch=True)
    return await execute_attempt(prepared, backend)


async def execute_attempt(prepared: PreparedProof, backend, *, preflight_fn=None) -> dict:
    """Bounded clearing ceremony against an authorized backend seam.

    Mirrors the execute_capture seam pattern: the native runner binds the
    one-launch backend; a controlled backend rehearses the identical ceremony
    offline against explicitly controlled evidence directories. No opening or
    closing claim here is exempt: preflight, claim consumption, budgets,
    cleanup, manifests and verdicts follow the sealed candidate path, and
    nothing reaches a launch-capable step without independently issued,
    verified operator authorization.

    The attempt scope (preflight gate, target tile, cost ceiling and session
    identity) resolves from the candidate's own staged facts: ``preflight_fn``
    selects the offline launch-boundary rehearsal (``None`` keeps the
    historical D2 preflight; sibling ceremonies pass their own), and the
    staged ``plan_policy`` carries the authorized tile, ceiling and attempt
    name, so the D2 candidate's values are byte-identical to the constants
    they replace.
    """
    directory = prepared.directory
    (preflight if preflight_fn is None else preflight_fn)(prepared)
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    # BLOCKER 1/5 gate: an operator-issued authorization must verify against
    # the seeded trust anchor and bind this exact candidate identity before
    # the one-shot claim is consumed. The verified record's exact bytes are
    # pinned once in the grant — the claim and the launch boundary reference
    # the same digest, so no later reread can substitute different bytes.
    grant = grant_launch(directory, metadata, seal)
    grant.launch_identity = launch_critical_identity(prepared, metadata)
    write_json(
        directory / "CLAIM.json",
        dict(
            prelaunch_digest=seal,
            consumed=True,
            launches_allowed=1,
            retries=0,
            authorization_schema=CLAIM_AUTHORIZATION_EVIDENCE_SCHEMA,
            authorization_sha256=grant.authorization_sha256,
            operator_key_identity=grant.operator_key_identity,
        ),
    )
    backend.preflight(prepared)
    pin = metadata["plan_policy"]["pinned"]
    result: dict[str, Any] = dict(
        preflight="PASS",
        native_launches=0,
        connections=0,
        requests=0,
        clearing="NOT_DISPATCHED",
        command_accepted=False,
        state_changed=False,
        verified=False,
        status="FAILED",
        pin=pin,
    )
    frames = []
    try:
        async with asyncio.timeout(metadata["budgets"]["total_seconds"]):
            await backend.launch(prepared, authorization=grant)
            result["native_launches"] = 1
            await wait_log(backend, prepared, "TERRAIN_CLEARING_READY")
            console(backend, metadata["bootstrap_command"])
            await wait_log(backend, prepared, "ROAD_PROOF_COMPANY_READY")
            session = await backend.connect(
                prepared, frame_observer=lambda d, f: frames.append((d, f.hex()))
            )
            result["connections"] = 1
            await session.authenticate(metadata["attempt"], "1", timeout=10)
            welcome = session.welcome
            expected = metadata["world"]["expected_welcome"]
            received = None
            if welcome is not None:
                received = tuple(getattr(welcome, field) for field in WELCOME_ORDER)
            wanted = (
                expected["revision"],
                True,
                expected["seed"],
                expected["landscape"],
                expected["start_day"],
                expected["width"],
                expected["height"],
            )
            if session.protocol is None or welcome is None or received != wanted:
                raise ValueError("retained world identity mismatch")
            write_json(
                directory / "runtime-identity.json",
                dict(
                    auth="X25519_AuthorizedKey",
                    encrypted=session.state is AuthState.ACTIVE,
                    welcome=asdict(welcome),
                    pid=backend.process.pid if backend.process else None,
                ),
            )
            await GameScriptTransport(session, session.protocol).subscribe()
            before_save = await save(backend, prepared, "session-before")
            write_json(directory / "session-before-identity.json", dict(sha256=before_save))

            def request(op: str, request_id: str, plan: str) -> ClearingRequest:
                return ClearingRequest(
                    op=op,
                    request_id=request_id,
                    plan=plan,
                    company=0,
                    tile=pin["tile"],
                    max_cost=metadata["plan_policy"]["max_cost"],
                )

            await exchange(session, request("read", "read-0", seal), directory)
            result["requests"] += 1
            before = await exchange(session, request("inspect", "inspect-1", seal), directory)
            result["requests"] += 1
            if before.status != "READY":
                raise StopNoMutation(
                    f"inspect did not authorize a clearing command: {before.status}"
                )
            intent = admit_pinned_target(
                before,
                pinned=pin,
                prelaunch_digest=seal,
                source_save_digest=before_save,
                max_cost=MAX_CLEARING_COST,
            )
            write_json(directory / "plan.json", intent.model_dump(mode="json"))

            # Record dispatch state before sending the clear command.
            # Wire contract v2 dispatch enforcement, before anything is sent:
            # the executing clear must present the admission plan identity its
            # inspect latched (the prelaunch seal). The GameScript mutation
            # boundary re-checks the equality before any DemolishTile.
            clear_req = request("clear", "clear-1", seal)
            if clear_req.plan != intent.prelaunch_digest:
                raise ValueError("dispatch refused: the clear plan does not bind this admission")
            result["dispatch_state"] = "DISPATCHED_UNKNOWN"
            result["dispatched_request_id"] = clear_req.request_id
            result["dispatched_plan"] = clear_req.plan
            built = await exchange(session, clear_req, directory)
            result["requests"] += 1
            result["dispatch_state"] = "CONFIRMED"
            result["clearing"] = built.status
            result["command_accepted"] = built.status in ("CLEARED", "READBACK_MISMATCH")
            after = await exchange(session, request("read", "read-2", intent.digest), directory)
            result["requests"] += 1
            result["state_changed"] = after.classification.value == "CLEAR"
            receipt = verify_clearing(intent, before, built, after)
            receipt["before_save_sha256"] = before_save
            receipt["after_save_sha256"] = await save(backend, prepared, "after")
            result["cost_attribution"] = dict(
                method="GSAccounting command-scoped native cost",
                test_quote=intent.native_test_cost,
                command_cost=built.cost,
                funds_at_inspect=before.funds,
                funds_at_exec=built.funds,
                company_cash_delta=before.funds - built.funds,
                statement=(
                    "the accounting cost is scoped to the demolition command by the "
                    "engine; the company cash delta agreeing with it is a redundant "
                    "cross-check, and an unexplained mismatch fails the receipt"
                ),
            )
            write_json(directory / "receipt.json", receipt)
            result["verified"] = True
            result["status"] = "NATIVE_STATE_VERIFIED"
    except StopNoMutation as stop:
        result["stop_reason"] = str(stop)
        result["status"] = "STOPPED_NO_MUTATION"
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
        # Always attempt after.sav capture if a command was possibly dispatched.
        if result.get("dispatch_state") in ("DISPATCHED_UNKNOWN", "CONFIRMED"):
            try:
                if "after_save_sha256" not in result:
                    result["after_save_sha256"] = await save(backend, prepared, "after-diagnostic")
            except Exception as save_err:
                result["after_save_error"] = type(save_err).__name__ + ": " + str(save_err)
        write_json(directory / "frames.json", frames)
        cleanup = await backend.cleanup(prepared)
        # Abnormal process termination belongs to the retained result: an
        # attempt that claimed anything while its runtime exited abnormally is
        # never a verified receipt (verified by the replay verifier).
        result["returncode"] = cleanup.get("returncode")
        for name in ("stdout.log", "stderr.log"):
            path = prepared.spec.workspace.logs / name
            if path.is_file():
                shutil.copyfile(path, directory / name)
        # Retained script health (BLOCKER 3): the copied logs are replayed
        # through the production log-health implementation. The failure-safe
        # diagnostic save already ran above; a fatal GameScript finding in
        # the retained logs denies any verified receipt this attempt could
        # claim, and the evidence (logs, receipt file, result) is preserved.
        findings = script_log_health_findings(
            "".join(
                (directory / name).read_text()
                for name in ("stdout.log", "stderr.log")
                if (directory / name).is_file()
            )
        )
        if findings:
            result["script_log_findings"] = findings
            if result["status"] == "NATIVE_STATE_VERIFIED":
                result["verified"] = False
                result["status"] = "FAILED"
                result["error"] = (
                    "ValueError: retained script log health findings deny the verified receipt"
                )
        # Explicit normal process termination is part of verified success
        # (BLOCKER 4): a runtime that reaped abnormally denies its own
        # receipt here, keeping every piece of evidence (receipt file,
        # diagnostics, logs) preserved for operator review. This never turns
        # a crash into a no-mutation verdict: mutation-possible evidence
        # stands (the dispatch state is untouched).
        if result["returncode"] not in (None, 0):
            if result["status"] == "NATIVE_STATE_VERIFIED":
                result["verified"] = False
                result["status"] = "FAILED"
                result["error"] = (
                    "ValueError: native runtime exited abnormally after receipt "
                    f"(return code {result['returncode']})"
                )
        try:
            cleanup.update(verify_cleanup_endpoints(prepared, cleanup))
            if not cleanup["reaped"] or cleanup["cleanup_error"]:
                raise ValueError("cleanup incomplete")
            prepared.spec.workspace.close()
            cleanup["workspace_disposed"] = not prepared.spec.workspace.root.exists()
            cleanup["credential_removed"] = not prepared.key_path.exists()
        except Exception as error:
            cleanup["verification_error"] = str(error)
            result["status"] = "FAILED_CLEANUP"
        write_json(directory / "cleanup.json", cleanup)
        write_json(directory / "result.json", result)
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    return result


def replay_authorization_state(
    directory: Path, metadata: dict, seal: str, claims: dict
) -> str | None:
    """BLOCKER 6: independently re-establish the retained authorization story.

    Returns ``None`` only when the candidate's retained evidence re-verifies
    against the currently anchored operator key: required claim fields present,
    the retained AUTHORIZATION.json byte-for-byte matches the digest the claim
    pinned, and a fresh verification (payload binding + RFC 8032 signature)
    agrees with the recorded operator key identity. Otherwise the
    classification state named in the failure table is returned for an
    AUTHORIZATION_UNVERIFIED verdict — a success label alone can never vouch
    for authorization at replay time.
    """
    digest = claims.get("authorization_sha256")
    if not isinstance(digest, str):
        return "MISSING"
    identity = claims.get("operator_key_identity")
    if not isinstance(identity, str):
        return "KEY_IDENTITY_MISSING"
    schema = claims.get("authorization_schema")
    if not isinstance(schema, str):
        return "MISSING"
    if schema != CLAIM_AUTHORIZATION_EVIDENCE_SCHEMA:
        return "SCHEMA_MISMATCH"
    # BLOCKER 6: the claim must be the complete, consumed, exact one-shot
    # record: an unconsumed claim, a missing consumption flag or an expanded
    # launch/retry allowance can never carry a verified receipt.
    one_shot_state = incomplete_one_shot_state(claims)
    if one_shot_state is not None:
        return one_shot_state
    if not (directory / AUTHORIZATION_FILE_NAME).is_file():
        return "MISSING"
    try:
        verified = verify_authorization(directory, metadata, seal)
    except ClearingAuthorizationError:
        return "FORGED"
    if verified.authorization_sha256 != digest:
        return "TAMPERED"
    if verified.operator_key_identity != identity:
        return "FORGED"
    return None


def verify_attempt(
    directory: Path,
    *,
    lineage_schema: str | None = None,
    sealed_pin: dict | None = None,
) -> dict:
    """Replay retained request/response semantics; never trust a success label.

    The lineage and pin parameters resolve shared-machinery reuse for sibling
    ceremonies at call time: ``None`` keeps the historical D2 replay exactly
    (the D2 prelaunch lineage gate and the pinned census clearing pin).
    """
    directory = directory.resolve()
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    seal = sha256(directory / "PRELAUNCH.json")
    claims = json.loads((directory / "CLAIM.json").read_text())
    if claims.get("prelaunch_digest") != seal:
        raise ValueError("attempt claim does not match its prelaunch seal")
    for line in (directory / "artifact-manifest.sha256").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if Path(name).name != name or not (directory / name).is_file():
            raise ValueError("artifact manifest mismatch")
        if sha256(directory / name) != digest:
            raise ValueError("artifact manifest mismatch")
    # BLOCKER 6: authorization evidence is replay-verified before anything
    # else in the retained attempt is interpreted. A v2 candidate whose claim
    # does not independently re-verify (missing, forged, tampered or
    # identity-rotated evidence) can never produce a verified receipt; it
    # stands recorded as one. A candidate whose staged prelaunch schema is
    # not the launch-capable lineage can only replay through an explicitly
    # pinned immutable freeze of its exact staged bytes — the schema string
    # inside a candidate directory is caller-controlled and never trusted.
    if lineage_schema is not None:
        if metadata.get("schema") != lineage_schema:
            return dict(
                verification="AUTHORIZATION_UNVERIFIED",
                authorization_state="UNKNOWN_PRELAUNCH_SCHEMA",
                statement=(
                    "the prelaunch record is not the launch-capable "
                    f"{lineage_schema} lineage; no verified receipt is possible"
                ),
            )
        authorization_state = replay_authorization_state(directory, metadata, seal, claims)
        if authorization_state is not None:
            return dict(
                verification="AUTHORIZATION_UNVERIFIED",
                authorization_state=authorization_state,
                statement=(
                    "the retained authorization evidence does not match the "
                    "operator-verified record; no verified receipt is possible"
                ),
            )
    elif metadata.get("schema") == NATIVE_PRELAUNCH_SCHEMA:
        authorization_state = replay_authorization_state(directory, metadata, seal, claims)
        if authorization_state is not None:
            return dict(
                verification="AUTHORIZATION_UNVERIFIED",
                authorization_state=authorization_state,
                statement=(
                    "the retained authorization evidence does not match the "
                    "operator-verified record; no verified receipt is possible"
                ),
            )
    elif seal not in PINNED_HISTORICAL_PRELAUNCH_DIGESTS:
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state="UNKNOWN_PRELAUNCH_SCHEMA",
            statement=(
                "the prelaunch record is neither the launch-capable D2 lineage "
                "nor an explicitly pinned historical freeze; no verified "
                "receipt is possible"
            ),
        )
    pin_gate = sealed_pin if sealed_pin is not None else pinned_target()
    if metadata["plan_policy"]["pinned"] != pin_gate:
        raise ValueError("sealed clearing pin drifted from the census evidence")
    result = json.loads((directory / "result.json").read_text())
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    if runtime["encrypted"] is not True or runtime["welcome"]["revision"] != "15.3":
        raise ValueError("owned single-runtime encrypted execution evidence missing")
    frames = json.loads((directory / "frames.json").read_text())
    outbound = []
    inbound = []
    replies = []
    # Authoritative-chronology position tracking: the retained frame order is
    # the evidence of what the one owned secure session actually sent and
    # received, across both directions. A multiset or sorted-payload equality
    # can never stand in for it (BLOCKER 2).
    request_positions: dict[bytes, int] = {}
    reply_positions: dict[bytes, int] = {}
    outbound_requests = []
    for index, (direction, frame_hex) in enumerate(frames):
        frame = bytes.fromhex(frame_hex)
        if direction == "outbound":
            outbound.append(frame)
            if frame[2] != ADMIN_GAMESCRIPT:
                continue
            payload = decode_gamescript(frame[3:])
            try:
                query = ClearingRequest.model_validate_json(payload)
            except Exception:
                raise ValueError("outbound frame contains invalid ClearingRequest")
            outbound_requests.append(query)
            request_positions[payload] = index
        else:
            inbound.append(frame)
            for kind, body in AdminFrameDecoder().feed_frames(frame):
                if kind != SERVER_GAMESCRIPT:
                    continue
                reply = decode_gamescript(body)
                if reply not in reply_positions:
                    reply_positions[reply] = index
                replies.append(reply)

    # Load request files for cross-reference.
    paths = sorted(directory.glob("*-request.json"))
    file_queries = [ClearingRequest.model_validate_json(path.read_bytes()) for path in paths]
    # Retained file identity: a request or response file must carry the request
    # id its filename claims. Swapping file contents defeats any name-agnostic
    # multiset comparison, so identity is bound here before anything else.
    for path, query in zip(paths, file_queries, strict=True):
        if query.request_id != path.name[: -len("-request.json")]:
            raise ValueError("retained request file identity does not match its payload")
    for path in sorted(directory.glob("*-response.json")):
        try:
            readback = ClearingReadback.model_validate_json(path.read_bytes())
        except ValueError:
            # A retained but unparseable gateway response cannot bind identity;
            # verify_executed_attempt has the fail-closed classification here
            # (unparseable responses never become verified receipts).
            continue
        if readback.request_id != path.name[: -len("-response.json")]:
            raise ValueError("retained response file identity does not match its payload")

    # Budget enforcement against the authoritative outbound stream.
    if len(outbound_requests) > metadata["budgets"]["requests"]:
        raise ValueError("clearing request budget exceeded (outbound frames)")

    # Check frame count: fewer outbound frames = incomplete evidence (transport failure)
    # More outbound frames than request files = invalid evidence (tampering)
    if len(outbound_requests) < len(file_queries):
        # Incomplete evidence - some requests were sent but frames lost
        # This is a transport failure, classify as unresolved
        return dict(
            verification="UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED",
            command_accepted=result.get("command_accepted", False),
            state_changed=result.get("state_changed", False),
            result_status=result["status"],
            statement="incomplete retained exchange (fewer outbound frames); no receipt claimed",
        )
    if len(outbound_requests) > len(file_queries):
        raise ValueError("outbound frame count exceeds request file count (tampering)")

    # Check that each outbound request matches exactly one request file (by payload)
    # and vice versa. This prevents swapped/mismatched payloads.
    # The outbound frames are admin frames containing game script payloads.
    # We need to compare the game script payloads, not the full admin frames.
    outbound_payloads = []
    for frame in outbound:
        if frame[2] == ADMIN_GAMESCRIPT:
            payload = decode_gamescript(frame[3:])
            outbound_payloads.append(payload)
    file_payloads = [q.to_bytes() for q in file_queries]
    # Sort both for comparison
    if sorted(outbound_payloads) != sorted(file_payloads):
        raise ValueError("outbound frame payloads do not match request file payloads")

    # Check for duplicate request IDs in outbound stream.
    seen_ids = set()
    for q in outbound_requests:
        if q.request_id in seen_ids:
            raise ValueError(f"duplicate request_id in outbound frames: {q.request_id}")
        seen_ids.add(q.request_id)

    # Check ordering: clear must not precede its inspect.
    # The inspect uses the prelaunch seal as plan; the clear uses the intent digest.
    clear_requests = [q for q in outbound_requests if q.op == "clear"]
    if len(clear_requests) > 1:
        raise ValueError("more than one clearing command in outbound frames")
    if len(clear_requests) == 1:
        clear = clear_requests[0]
        # The prelaunch seal is the plan used for read/inspect.
        inspects = [q for q in outbound_requests if q.op == "inspect" and q.plan == seal]
        if not inspects:
            # Fallback: any inspect that precedes the clear.
            inspects = [q for q in outbound_requests if q.op == "inspect"]
        if not inspects:
            raise ValueError("clear request has no matching inspect in outbound frames")
        # Verify inspect appears before clear in the frame sequence.
        clear_idx = outbound_requests.index(clear)
        inspect_idx = outbound_requests.index(inspects[0])
        if inspect_idx >= clear_idx:
            raise ValueError("clear request precedes its inspect in outbound frames")
        single_clear = (clear, inspects[0])
        # Chronology: the independent post-mutation read must observe the tile
        # only after the clear command it is supposed to independently confirm.
        # The serial owned session produces one strictly ordered stream: every
        # read sits before the inspect (pre-mutation observation) or after the
        # dispatch (post-mutation independent read). Wire contract v2 note:
        # plan-based identification is not used here — the clear's plan is the
        # admission plan and reads keep their own intent-scoped plans, so a
        # tampered clear plan cannot confound this gate. Sorted payload
        # equality proves multiset identity, never chronology.
        for q in outbound_requests:
            if q.op != "read":
                continue
            if not (
                outbound_requests.index(q) < inspect_idx or outbound_requests.index(q) > clear_idx
            ):
                raise ValueError("independent read precedes the clearing command it observes")

    # Build response map from retained files (may be incomplete).
    response_map = {}
    for path in paths:
        response_path = path.with_name(path.name.replace("-request.json", "-response.json"))
        if response_path.is_file():
            response_map[path.read_bytes()] = response_path.read_bytes()

    # Validate unique frame evidence for each exchange that has both sides.
    for path in paths:
        raw = path.read_bytes()
        response = response_map.get(raw)
        if response is not None:
            if outbound.count(encode_gamescript(raw)) != 1 or replies.count(response) != 1:
                raise ValueError("retained exchange lacks unique secure-session frame evidence")

    # Complete chronology (BLOCKER 2) over the authoritative stream position
    # of every retained event: a response is never accepted ahead of its own
    # request, the dispatch is never accepted ahead of the inspect response
    # that latched its admission, and no read can appear inside the
    # dispatch-to-response window of the serial owned session.
    if len(clear_requests) == 1:
        _clear, _inspect = single_clear
        _inspect_reply = response_map.get(_inspect.to_bytes())
        if (
            _inspect_reply is not None
            and reply_positions[_inspect_reply] > request_positions[_clear.to_bytes()]
        ):
            raise ValueError(
                "clear command precedes the inspect response that latches its admission"
            )
    for raw, response in response_map.items():
        if reply_positions[response] < request_positions[raw]:
            raise ValueError("a retained response precedes its own request in the frame stream")
    if len(clear_requests) == 1:
        _clear = clear_requests[0]
        _clear_reply = response_map.get(_clear.to_bytes())
        if _clear_reply is not None:
            _dispatch_pos = request_positions[_clear.to_bytes()]
            _dispatch_reply_pos = reply_positions[_clear_reply]
            for _q in outbound_requests:
                if _q.op != "read":
                    continue
                _read_pos = request_positions[_q.to_bytes()]
                if _dispatch_pos < _read_pos < _dispatch_reply_pos:
                    raise ValueError(
                        "a read request arrives between the clearing command and its response"
                    )

    # Evidence contradiction: every retained inbound gateway reply must have
    # its durable retained response file. Deleting the response file while the
    # gateway frame survives is evidence tampering, not a transport failure
    # (a genuinely lost response loses both the file and the frame).
    retained_responses = set(response_map.values())
    for reply in replies:
        if reply not in retained_responses:
            raise ValueError("retained gateway response lacks its durable response file")

    # Load clears from the authoritative outbound stream.
    clears = [q for q in outbound_requests if q.op == "clear"]

    if len(clears) == 1 and result["status"] == "STOPPED_NO_MUTATION":
        raise ValueError("stopped attempt contradicts a retained command request")
    if not clears and (
        result.get("command_accepted")
        or result.get("state_changed")
        or result.get("verified")
        or result["status"] == "NATIVE_STATE_VERIFIED"
        or (directory / "receipt.json").exists()
    ):
        raise ValueError("mutation claim without a retained clear request")

    # Check for process crash / abnormal termination (BLOCKER 4): the exit
    # evidence is cross-checked across result.json and cleanup.json — a
    # missing or contradictory abnormal code in either retained record
    # prevents a verified receipt, and mutation-possible evidence stands.
    cleanup_record = json.loads((directory / "cleanup.json").read_text())
    exit_codes = (result.get("returncode"), cleanup_record.get("returncode"))
    if (
        result.get("process_crash")
        or result.get("process_exited_abnormally")
        or any(code not in (None, 0) for code in exit_codes)
    ):
        # Process crashed - cannot claim verified success
        return dict(
            verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
            result_status=result.get("status", "UNKNOWN"),
            error=result.get("error", "process exited abnormally"),
            exit_evidence=dict(result_returncode=exit_codes[0], cleanup_returncode=exit_codes[1]),
        )

    # Retained script health (BLOCKER 3) is validated independently during
    # replay through the same production log-health implementation used at
    # execution: a fatal GameScript finding in the retained logs — or the
    # absence of any retained log at all — denies a claimed verified receipt
    # outright, even where the attempt record disagrees.
    if result.get("verified") or result["status"] == "NATIVE_STATE_VERIFIED":
        log_names = ("stdout.log", "stderr.log")
        retained_logs = [name for name in log_names if (directory / name).is_file()]
        health_findings = script_log_health_findings(
            "\n".join((directory / name).read_text() for name in retained_logs)
        )
        if not retained_logs or health_findings:
            return dict(
                verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
                result_status=result.get("status", "UNKNOWN"),
                error=(
                    "retained script health does not support the verified receipt (missing logs)"
                    if not retained_logs
                    else "retained script log health findings deny the verified receipt"
                ),
                script_log_findings=health_findings,
            )

    if len(clears) == 1:
        return verify_executed_attempt(
            directory,
            metadata,
            seal,
            clears[0],
            result,
            response_map,
            outbound,
            request_positions,
            reply_positions,
            cleanup_record,
        )
    return verify_stopped_attempt(directory, metadata, seal, result, response_map, outbound)


def verify_executed_attempt(
    directory: Path,
    metadata: dict,
    seal: str,
    clear: ClearingRequest,
    result: dict,
    response_map: dict,
    outbound: list[bytes],
    request_positions: dict[bytes, int],
    reply_positions: dict[bytes, int],
    cleanup_record: dict,
):
    plan_path = directory / "plan.json"
    if not plan_path.is_file():
        return dict(
            verification="UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED",
            command_accepted=result.get("command_accepted", False),
            state_change_uncertain=True,
            result_status=result["status"],
            statement="the latched intent record is missing; no receipt is claimed",
        )
    intent = ClearingIntent.model_validate_json(plan_path.read_bytes())
    matches = [
        path
        for path in directory.glob("inspect-*-response.json")
        if ClearingReadback.model_validate_json(path.read_bytes()).digest == intent.before_digest
    ]
    # Check for missing clear outbound frame (clear was dispatched but no outbound frame)
    clear_req_bytes = clear.to_bytes()
    clear_response_bytes = response_map.get(clear_req_bytes)
    clear_outbound_count = outbound.count(encode_gamescript(clear_req_bytes))
    if clear_outbound_count == 0:
        return dict(
            verification="UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED",
            command_accepted=result.get("command_accepted", False),
            state_changed=result.get("state_changed", False),
            result_status=result["status"],
            statement="clear command was dispatched but no outbound frame recorded",
        )
    if not matches or clear_response_bytes is None:
        return dict(
            verification="UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED",
            command_accepted=result.get("command_accepted", False),
            state_changed=result.get("state_changed", False),
            result_status=result["status"],
            statement=(
                "incomplete retained exchange (missing inspect or clear response); "
                "no independently verified clearing receipt exists"
            ),
        )
    before = ClearingReadback.model_validate_json(matches[0].read_bytes())
    admit_pinned_target(
        before,
        pinned=metadata["plan_policy"]["pinned"],
        prelaunch_digest=seal,
        source_save_digest=intent.source_save_digest,
        max_cost=intent.max_cost,
    )
    try:
        built = ClearingReadback.parse_for(clear, clear_response_bytes)
    except ValueError as parse_error:
        # A genuine gateway may return unparseable or uncorrelated bytes; the
        # exchange then preserves evidence of a possibly executed command that
        # can never be read as a verified receipt.
        return dict(
            verification="UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED",
            command_accepted=result.get("command_accepted", False),
            state_changed=result.get("state_changed", False),
            result_status=result["status"],
            statement=(
                "the retained clearing response is unparseable or uncorrelated "
                f"({type(parse_error).__name__}: {parse_error}); no independently "
                "verified clearing receipt exists"
            ),
        )
    if (built.plan, built.company, built.tile) != (
        intent.prelaunch_digest,
        intent.company,
        intent.tile,
    ):
        raise ValueError("clearing execution evidence does not correlate to its intent")
    # Find the independent read request with matching plan.
    read_query = None
    for path in directory.glob("*-request.json"):
        query = ClearingRequest.model_validate_json(path.read_bytes())
        if query.op == "read" and query.plan == intent.digest:
            read_query = query
            break
    read_response_bytes = response_map.get(read_query.to_bytes()) if read_query else None
    if read_query is None or read_response_bytes is None:
        return dict(
            verification="UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED",
            command_accepted=result.get("command_accepted", False),
            state_change_uncertain=built.status == "CLEARED",
            result_status=result["status"],
            statement="the independent read exchange is missing; no receipt is claimed",
        )
    after = ClearingReadback.parse_for(read_query, read_response_bytes)
    # Complete chronological chain of the verified success (BLOCKER 2): the
    # inspect request, its latching response, the dispatch, its response, the
    # independent read request and its response must appear in exactly this
    # order in the authoritative stream. Reordered-but-intact multisets are
    # tampering, never a receipt.
    inspect_query = ClearingRequest.model_validate_json(
        (directory / f"{before.request_id}-request.json").read_bytes()
    )
    chain = [
        request_positions[inspect_query.to_bytes()],
        reply_positions[matches[0].read_bytes()],
        request_positions[clear.to_bytes()],
        reply_positions[clear_response_bytes],
        request_positions[read_query.to_bytes()],
        reply_positions[read_response_bytes],
    ]
    if chain != sorted(chain):
        raise ValueError("verified receipt lacks its chronological exchange chain")
    receipt_path = directory / "receipt.json"
    if not receipt_path.exists() or result["status"] != "NATIVE_STATE_VERIFIED":
        return dict(
            verification="UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED",
            command_accepted=result.get("command_accepted", False),
            state_changed=result.get("state_changed", False),
            clear_status=built.status,
            result_status=result["status"],
            statement=(
                "no verified clearing receipt exists; execution evidence is "
                "preserved for operator review and must never be read as success"
            ),
        )
    # Verified success requires explicit, consistent, normal process
    # termination on BOTH retained exit records (BLOCKER 4). Missing exit
    # evidence is never promoted.
    if result.get("returncode") != 0 or cleanup_record.get("returncode") != 0:
        raise ValueError("verified receipt lacks explicit consistent normal process exit evidence")
    expected = verify_clearing(intent, before, built, after)
    expected["before_save_sha256"] = sha256(directory / "session-before.sav")
    expected["after_save_sha256"] = sha256(directory / "after.sav")
    if intent.source_save_digest != expected["before_save_sha256"]:
        raise ValueError("intent source save mismatch")
    if json.loads(receipt_path.read_text()) != expected:
        raise ValueError("retained clearing receipt replay mismatch")
    if (result.get("native_launches"), result.get("connections")) != (
        metadata["budgets"]["launches"],
        metadata["budgets"]["connection_attempts"],
    ):
        raise ValueError("verified receipt contradicts its launch/connection seal")
    if not (result.get("command_accepted") and result.get("state_changed")):
        raise ValueError("verified receipt contradicts its retained attempt record")
    attribution = result.get("cost_attribution")
    replay = dict(
        method="GSAccounting command-scoped native cost",
        test_quote=intent.native_test_cost,
        command_cost=built.cost,
        funds_at_inspect=before.funds,
        funds_at_exec=built.funds,
        company_cash_delta=before.funds - built.funds,
    )
    if not isinstance(attribution, dict) or {key: attribution.get(key) for key in replay} != replay:
        raise ValueError("retained cost attribution does not replay the native evidence")
    if seal != intent.prelaunch_digest:
        raise ValueError("attempt plan does not bind its prelaunch seal")
    cleanup = json.loads((directory / "cleanup.json").read_text())
    if not all(
        cleanup.get(k) is True
        for k in ("reaped", "sockets_closed", "workspace_disposed", "credential_removed")
    ):
        raise ValueError("receipt cleanup incomplete")
    return dict(verification="RECEIPT_VERIFIED", receipt=expected)


def verify_stopped_attempt(
    directory: Path,
    metadata: dict,
    seal: str,
    result: dict,
    response_map: dict,
    outbound: list[bytes],
) -> dict:
    if result["status"] == "STOPPED_NO_MUTATION":
        if result.get("command_accepted"):
            raise ValueError("stopped attempt claims a mutation")
        inspect_req_path = directory / "inspect-1-request.json"
        inspect_resp_path = directory / "inspect-1-response.json"
        if not (
            inspect_req_path.is_file()
            and inspect_resp_path.is_file()
            and (directory / "session-before.sav").is_file()
        ):
            return dict(
                verification="UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED",
                result_status=result["status"],
                stop_reason=result.get("stop_reason"),
                statement="the stop evidence set is incomplete; no receipt is claimed",
            )
        inspect_req_bytes = inspect_req_path.read_bytes()
        inspect_resp_bytes = response_map.get(inspect_req_bytes, inspect_resp_path.read_bytes())
        attempt = ClearingReadback.parse_for(
            ClearingRequest.model_validate_json(inspect_req_bytes),
            inspect_resp_bytes,
        )
        try:
            admit_pinned_target(
                attempt,
                pinned=metadata["plan_policy"]["pinned"],
                prelaunch_digest=seal,
                source_save_digest=sha256(directory / "session-before.sav"),
                max_cost=metadata["plan_policy"]["max_cost"],
            )
        except StopNoMutation:
            replay_stop = True
        except ValueError:
            # An admission refusal corroborates the stop only when the retained
            # inspect status itself was a refusal (never READY).
            replay_stop = attempt.status != "READY"
        else:
            replay_stop = False
        if not replay_stop:
            raise ValueError("stopped attempt without pin-mismatch or refusal evidence")
        return dict(verification="STOPPED_WITHOUT_MUTATION", stop_reason=result["stop_reason"])
    return dict(
        verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
        result_status=result["status"],
        error=result.get("error"),
    )


def exit_status(result: dict) -> int:
    """The runner CLI exit code: zero only for the verified native receipt."""
    return 0 if result.get("status") == "NATIVE_STATE_VERIFIED" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "preflight", "run", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepared = prepare_candidate(directory)
        preflight(prepared)
        print("PRELAUNCH PASS", directory)
    elif args.command == "verify":
        print(json.dumps(verify_attempt(directory), sort_keys=True))
    elif args.command == "preflight":
        preflight(reopen(directory))
        print("PREFLIGHT PASS")
    else:
        result = asyncio.run(run(reopen(directory)))
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(exit_status(result))


if __name__ == "__main__":
    main()
