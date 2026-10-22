"""Bounded, separately authorized canonical acquisition and fresh-process reload.

Preparation never launches or connects. Runtime orchestration reuses freight's
secure session, planning, native backend, console saves and ownership cleanup.
"""

import argparse
import asyncio
import configparser
import json
import os
import re
import shutil
import zipfile
from dataclasses import asdict
from pathlib import Path

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.freight_canonical import compare_canonical, seal_canonical_inputs
from app.simulation.openttd.freight_delivery import (
    DeliveryPlan,
    DeliveryRequest,
    admit,
    verify_snapshot,
)
from app.simulation.openttd.gamescript_transport import GameScriptTransport
from app.simulation.openttd.runtime.base import LaunchSpecification
from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.secure_admin import AuthState

from . import freight_delivery as freight
from .endpoints import verify_cleanup_endpoints
from .graphics import stage_opengfx
from .harness import (
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
from .road_mutation import console, save, wait_log

CREATE = "canonical-fleet-create-q3"
RELOAD = "canonical-fleet-reload-q3"
SCHEMA = "canonical-fleet-qualification-v1"
RELOAD_ONLY_CONTRACT = dict(
    mode="reload-only",
    purchase=False,
    dispatch=False,
    unpause=False,
    correspondence="exact-native-semantic-state",
    heartbeat="paused-before-and-after",
)
SUSPENSION_VALIDATION = PROJECT / "artifacts/validation/canonical-fleet-reload-q3/suspension.json"


def configuration_digest(path):
    """Exclude only connection coordinates/credential, never gameplay settings."""
    import hashlib

    config = configparser.ConfigParser(interpolation=None)
    config.read_string(path.read_text())
    for name in ("server_port", "server_admin_port"):
        config.remove_option("network", name)
    payload = {s: dict(config[s]) for s in config.sections()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def package_bytes():
    return freight.staged_package(True, True, True, "high-budget-500k", 3, 5, canonical=True)


def expected_argv(prepared, stage):
    source = prepared.spec.workspace.root / ("heightmap.png" if stage == CREATE else "source.sav")
    argv = freight.vehicle.load_argv(
        freight.BINARY.resolve(), prepared.spec.workspace.config, prepared.endpoints[0], source
    )
    return argv + (("-G", "42") if stage == CREATE else ())


class CanonicalBackend(freight.PlannerBackend):
    planning_frame_observer = None
    planning_frames = None

    def validate_launch(self, prepared):
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_bytes())
        if (
            prepared.spec.argv != expected_argv(prepared, metadata["qualification_id"])
            or sha256(freight.BINARY) != BINARY_SHA256
            or freight.vehicle.matching_processes(freight.BINARY)
        ):
            raise ValueError("canonical native launch identity/ownership mismatch")


def prepare(directory, *, stage, canonical=None):
    if stage not in (CREATE, RELOAD) or directory.name != stage:
        raise ValueError("exact independent canonical qualification identity required")
    if (stage == RELOAD) != (canonical is not None):
        raise ValueError("reload requires canonical creation evidence; create forbids it")
    if canonical is not None:
        from app.simulation.openttd.freight_canonical_runtime import verify_save

        created = verify_created_source(canonical)
        verify_save(canonical / "canonical.sav", created)
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    workspace = RuntimeWorkspace.create(directory / "isolated", retain=True)
    reservation = EndpointReservation.allocate()
    try:
        key = AuthorizedKey.generate()
        secret = workspace.root / ".admin-secret"
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
        if stage == CREATE:
            config = workspace.config.read_text().replace(
                "pause_on_newgame = true", "pause_on_newgame = false"
            )
            config += (
                "\n[misc]\ngraphicsset = OpenGFX\n[ai]\nai_in_multiplayer = true\n"
                "[game_scripts]\nRoadFreightProof = \n[game_creation]\nmap_x = 6\nmap_y = 6\n"
                "landscape = temperate\nstarting_year = 1950\n"
                "land_generator = 1\nheightmap_height = 1\n"
                "tree_placer = 0\namount_of_rivers = 0\n[difficulty]\nnumber_towns = 4\n"
                "industry_density = 0\nmax_no_competitors = 0\n"
                "vehicle_breakdowns = 0\ndisasters = false\n"
                "infinite_money = false\n[economy]\ntimekeeping_units = 0\n"
                "multiple_industry_per_town = true\n"
                "[newgrf]\n[company]\nengine_renew = false\n"
                "[construction]\ncommand_pause_level = 3\n"
            )
            workspace.config.write_text(config)
            (workspace.root / "heightmap.png").write_bytes(freight.flat_heightmap())
            shutil.copyfile(workspace.root / "heightmap.png", directory / "heightmap.png")
        else:
            if canonical is None:
                raise ValueError("reload canonical source missing")
            config = configparser.ConfigParser(interpolation=None)
            config.read_string((canonical / "effective-openttd.cfg").read_text())
            config.set("network", "server_port", str(reservation.game_port))
            config.set("network", "server_admin_port", str(reservation.admin_port))
            with workspace.config.open("w") as stream:
                config.write(stream)
            shutil.copyfile(canonical / "canonical.sav", workspace.root / "source.sav")
        graphics = stage_opengfx(freight.GRAPHICS_ARCHIVE, workspace.root / "baseset/OpenGFX")
        write_json(
            directory / "graphics-identity.json",
            dict(asdict(graphics), directory=str(graphics.directory)),
        )
        package = package_bytes()
        target = workspace.game / "RoadFreightProof"
        target.mkdir()
        for name, data in package.items():
            (target / name).write_bytes(data)
        target = workspace.ai / "RoadProofCompany"
        target.mkdir()
        for path in (PROJECT / "app/simulation/openttd/road_company_package").glob("*.nut"):
            shutil.copyfile(path, target / path.name)
        shutil.copyfile(workspace.config, directory / "effective-openttd.cfg")
        endpoints = (reservation.game_port, reservation.admin_port)
        from types import SimpleNamespace

        provisional = SimpleNamespace(
            spec=SimpleNamespace(workspace=workspace), endpoints=endpoints
        )
        argv = expected_argv(provisional, stage)
        spec = LaunchSpecification(
            workspace,
            RuntimeIdentity(freight.BINARY.resolve(), "15.3", BINARY_SHA256),
            argv,
            workspace.root,
            workspace.environment,
            workspace.logs / "stdout.log",
            workspace.logs / "stderr.log",
        )
        frozen = source_freeze()
        import openttdlab

        # Pin the actual VM regression execution to these exact staged bytes.
        validation = json.loads(SUSPENSION_VALIDATION.read_bytes())
        import hashlib

        if validation.get(
            "source_commit"
        ) != "14ec60f248547d4d062a1160f0fc26d742319888" or validation.get("package_sha256") != {
            name: hashlib.sha256(data).hexdigest() for name, data in sorted(package.items())
        }:
            raise ValueError("exact OpenTTD 15.3 VM validation/package correspondence required")
        for name in (
            "tests/validate_canonical_squirrel.py",
            "tests/support/openttd_squirrel_suspend.cpp",
            "tests/support/canonical_startup_vm.nut",
            "tests/support/canonical_protocol_vm.nut",
        ):
            helper = PROJECT / name
            if validation["helper_sha256"].get(str(helper)) != sha256(helper):
                raise ValueError("Squirrel validation helper changed")
            frozen[str(helper)] = sha256(helper)
        for path in (
            Path(openttdlab.__file__),
            PROJECT / "docs/capacity-experiment.md",
            SUSPENSION_VALIDATION,
        ):
            frozen[str(path.resolve())] = sha256(path)
        for root in (
            PROJECT / "app/planning",
            freight.PACKAGE,
            PROJECT / "app/simulation/openttd/road_company_package",
        ):
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in (".py", ".nut"):
                    frozen[str(path.resolve())] = sha256(path)
        archive = directory / "frozen-source.zip"
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
            for filename in sorted(frozen):
                path = Path(filename)
                if path.is_relative_to(PROJECT):
                    z.writestr(str(path.relative_to(PROJECT)), path.read_bytes())
            for name, data in package.items():
                z.writestr("staged/" + name, data)
            z.writestr("staged/openttd.cfg", workspace.config.read_bytes())
        if canonical is not None:
            for path in canonical.rglob("*"):
                if path.is_file():
                    frozen[str(path.resolve())] = sha256(path)
        frozen[str(archive)] = sha256(archive)
        frozen[str(freight.BINARY)] = sha256(freight.BINARY)
        for path in workspace.root.rglob("*"):
            if path.is_file() and path != secret:
                frozen[str(path.resolve())] = sha256(path)
        metadata = dict(
            schema=SCHEMA,
            qualification_id=stage,
            execution_contract=RELOAD_ONLY_CONTRACT if stage == RELOAD else {"mode": "create"},
            workspace=str(workspace.root),
            argv=list(argv),
            binary=str(freight.BINARY),
            public_key=key.public_hex,
            game_port=reservation.game_port,
            admin_port=reservation.admin_port,
            frozen=frozen,
            canonical_directory=str(canonical.resolve()) if canonical else None,
            canonical_save_sha256=created.source_save_sha256 if canonical else None,
            configuration_sha256=configuration_digest(workspace.config),
            bridge_sha256=bridge_digest(package),
            predecessor=dict(executor_source_digest=sha256(archive)),
            network_service_limit=3,
            delivery_batch_limit=20,
            planning_budget_gbp="500000",
            financial_reconciliation_version=1,
            game_time_metrics_version=1,
            budgets=freight.network_budgets(3) | dict(total_seconds=1200),
            authorization=(
                "separate explicit authorization; one launch; one connection; no retry/reconnect"
            ),
        )
        write_json(directory / "PRELAUNCH.json", metadata)
        (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")
        return PreparedProof(directory, spec, secret, key.public_hex, endpoints)
    except BaseException:
        # Only this fresh, owned preparation tree is disposed; retain its directory.
        (workspace.root / ".admin-secret").unlink(missing_ok=True)
        workspace.close()
        raise
    finally:
        reservation.close()


def bridge_digest(package):
    import hashlib

    digest = hashlib.sha256()
    for name, data in sorted(package.items()):
        digest.update(name.encode() + b"\0" + data + b"\0")
    return digest.hexdigest()


def load_created(directory):
    from app.simulation.openttd.freight_canonical import CanonicalObservation

    metadata = json.loads((directory / "canonical-provenance.json").read_bytes())
    return CanonicalObservation.model_validate_json(json.dumps(metadata["observation"]))


def verify_created_source(directory):
    """Accept only immutable successful owned creation evidence, after cleanup."""
    directory = directory.resolve()
    created = load_created(directory)
    metadata = json.loads((directory / "PRELAUNCH.json").read_bytes())
    result = json.loads((directory / "result.json").read_bytes())
    cleanup = json.loads((directory / "cleanup.json").read_bytes())
    raw = directory / "checkpoint-after/canonical-readback.jsonl"
    if (
        directory.name != CREATE
        or created.qualification_id != CREATE
        or metadata["qualification_id"] != CREATE
        or metadata["schema"] != SCHEMA
        or manifest(directory) != (directory / "artifact-manifest.sha256").read_text()
        or sha256(directory / "PRELAUNCH.json")
        != (directory / "PRELAUNCH.sha256").read_text().strip()
        or result.get("status") != "CANONICAL_CREATED_PENDING_FRESH_PROCESS_RELOAD"
        or result.get("launches") != 1
        or result.get("connections") != 1
        or not all(
            cleanup.get(k) is True
            for k in ("reaped", "sockets_closed", "workspace_disposed", "credential_removed")
        )
        or cleanup.get("cleanup_error")
        or cleanup.get("remaining_processes")
        or cleanup.get("verification_error")
        or sha256(raw) != created.raw_readback_sha256
        or metadata["bridge_sha256"] != created.bridge_sha256
        or metadata["configuration_sha256"] != created.configuration_sha256
    ):
        raise ValueError("canonical creation provenance or cleanup incomplete")
    claim = json.loads((directory / "CLAIM.json").read_bytes())
    if claim != dict(
        consumed=True,
        prelaunch_digest=sha256(directory / "PRELAUNCH.json"),
        launches_allowed=1,
        retries=0,
    ):
        raise ValueError("canonical creation launch claim mismatch")
    return created


def reopen(directory):
    directory = Path(directory).absolute()
    if ".." in directory.parts or any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("canonical evidence directory alias or symlink")
    return freight.reopen(directory)


def preflight(prepared):
    directory = prepared.directory
    metadata = json.loads((directory / "PRELAUNCH.json").read_bytes())
    stage = metadata["qualification_id"]
    if (
        stage not in (CREATE, RELOAD)
        or directory.name != stage
        or metadata["schema"] != SCHEMA
        or (directory / "CLAIM.json").exists()
        or sha256(directory / "PRELAUNCH.json")
        != (directory / "PRELAUNCH.sha256").read_text().strip()
    ):
        raise ValueError("canonical sealed identity/claim mismatch")
    verify_freeze(metadata["frozen"])
    if (
        bridge_digest(package_bytes()) != metadata["bridge_sha256"]
        or configuration_digest(prepared.spec.workspace.config) != metadata["configuration_sha256"]
    ):
        raise ValueError("canonical package/configuration mismatch")
    if stage == RELOAD:
        from app.simulation.openttd.freight_canonical_runtime import verify_save

        if metadata.get("execution_contract") != RELOAD_ONLY_CONTRACT:
            raise ValueError("sealed reload-only execution contract required")
        canonical = Path(metadata["canonical_directory"])
        created = verify_created_source(canonical)
        verify_save(prepared.spec.workspace.root / "source.sav", created)
        if load_created(canonical).configuration_sha256 != metadata["configuration_sha256"]:
            raise ValueError("reload effective gameplay configuration mismatch")
    backend = CanonicalBackend(authorized_one_launch=True)
    backend.preflight(prepared)
    backend.validate_launch(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    reservation.close()
    return metadata


async def construct_originals(
    backend, prepared, session, accounting, before, seal, metadata, result
):
    from app.simulation.openttd.freight_canonical_dispatch import seal_service
    from app.simulation.openttd.freight_native_network import (
        plan_network_world,
        require_selected_service_count,
    )

    _, execution, services, source_save = await plan_network_world(
        backend, prepared, session, accounting, before, 20
    )
    require_selected_service_count(metadata, services)
    plans = []
    from app.planning.canonical import plan_hash

    for n, (_, service) in enumerate(services):
        read = await freight.exchange(
            session, service.selection_request(request_id=f"select-{n}"), prepared.directory
        )
        native = admit(
            read,
            seal,
            source_save,
            None,
            executor_source=metadata["predecessor"]["executor_source_digest"],
            selection_digest=plan_hash(execution),
        )
        service.validate_native_selection(native, read)
        plans.append(native)
        write_json(prepared.directory / f"native-plan-{n}.json", native.model_dump(mode="json"))
        activated = await freight.exchange(
            session,
            DeliveryRequest(op="read", request_id=f"activate-{n}", plan=native.digest, arg=n),
            prepared.directory,
        )
        verify_snapshot(native, activated)
        if activated.status != "READ" or activated.s[22] != 0 or activated.s[4] != -1:
            raise ValueError("canonical original service activation mismatch")
        for stage in range(9):
            built = await freight.exchange(
                session,
                DeliveryRequest(
                    op="build", request_id=f"s{n}-build-{stage}", plan=native.digest, arg=stage
                ),
                prepared.directory,
            )
            read = await freight.exchange(
                session,
                DeliveryRequest(
                    op="read", request_id=f"s{n}-read-{stage}", plan=native.digest, arg=stage
                ),
                prepared.directory,
            )
            result["mutations"] += 1
            verify_snapshot(native, read)
            if built.status != "BUILT" or read.status != "READ" or read.s[22] != stage + 1:
                raise ValueError(f"canonical service {n} construction stage {stage} failed")
        await seal_service(session, prepared.directory, n)
    return plans


async def protected_save(backend, prepared, name):
    path = prepared.directory / (name + ".sav")
    if path.exists() or any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("refusing to overwrite or redirect protected native save")
    if name == "failure":
        return await save(backend, prepared, name, diagnostic=True)
    return await save(backend, prepared, name)


async def establish_reload_context(session, directory, canonical):
    """Use the frozen bridge's read handler to establish native road API context.

    Road type is process-local ScriptStorage, not restored GameScript fleet data.
    The packaged read handler selects ROADTYPE_ROAD, verifies availability/current
    type and checks the owned route before returning this native snapshot.
    """
    created = load_created(canonical)
    plan = DeliveryPlan.model_validate_json((canonical / "native-plan-0.json").read_bytes())
    vehicle = created.state.vehicles[0]
    if vehicle.service != 0 or vehicle.tile != plan.a[8]:
        raise ValueError("reload context source service binding mismatch")
    read = await freight.exchange(
        session,
        DeliveryRequest(op="read", request_id="activate-reload-context", plan=plan.digest, arg=0),
        directory,
    )
    s = read.s
    if (
        read.status != "READ"
        or read.plan != plan.digest
        or read.a != plan.a
        or read.f != plan.f
        or len(s) != 30
        or s[1] != created.state.economy_date
        or s[2] != 1
        or s[3] != created.state.cash
        or s[4:9]
        != (vehicle.vehicle, vehicle.owner, vehicle.engine, vehicle.capacity, vehicle.tile)
        or s[10:15] != (0, 0, 2, vehicle.orders[0].destination, vehicle.orders[1].destination)
        or s[18] != 0
        or s[22] != 10
        or s[28:30] != (1, 1)
    ):
        raise ValueError("reload native road context or sealed service readback mismatch")
    return read


def failure_details(prepared, error):
    """Preserve a native fatal behind a stalled exchange without inventing correlation."""
    details = {"error": type(error).__name__ + ": " + str(error)}
    if not isinstance(error, (TimeoutError, ConnectionError)):
        return details
    log = prepared.spec.workspace.logs / "stderr.log"
    if not log.is_file():
        return details
    lines = log.read_text(errors="replace").splitlines()
    fatal = re.compile(r"^.*dbg: \[script:0\] \[\d+\] \[S\] Your script made an error: (.+)$")
    matches = [(n, fatal.fullmatch(line)) for n, line in enumerate(lines)]
    matches = [(n, match) for n, match in matches if match is not None]
    if not matches:
        return details
    start, match = matches[-1]
    end = next(
        (
            n
            for n in range(start + 1, len(lines))
            if re.fullmatch(r".*dbg: \[script:0\] The script died unexpectedly\.", lines[n])
        ),
        None,
    )
    if end is None:
        return details
    context = lines[start : end + 1]
    pending = []
    correlation_errors = []
    for path in sorted(prepared.directory.glob("*-request.json")):
        response = path.with_name(path.name.removesuffix("-request.json") + "-response.json")
        if response.exists():
            continue
        try:
            request = json.loads(path.read_bytes())
        except (OSError, ValueError) as correlation_error:
            correlation_errors.append(dict(artifact=path.name, error=str(correlation_error)))
            continue
        pending.append(dict(artifact=path.name, request=request))
    details.update(
        error="GameScriptError: " + match.group(1),
        secondary_error=details["error"],
        native_failure=dict(
            log="stderr.log",
            line=start + 1,
            context=context,
            pending_requests=pending,
            correlation_errors=correlation_errors,
            correlation="single-unanswered-request"
            if len(pending) == 1 and not correlation_errors
            else "unresolved",
        ),
    )
    return details


async def run(prepared, *, authorize_one_launch=False):
    if authorize_one_launch is not True:
        raise ValueError("separate explicit one-launch authorization required")
    metadata = preflight(prepared)
    seal = sha256(prepared.directory / "PRELAUNCH.json")
    write_json(
        prepared.directory / "CLAIM.json",
        dict(consumed=True, prelaunch_digest=seal, launches_allowed=1, retries=0),
    )
    backend = CanonicalBackend(authorized_one_launch=True)
    frames = []
    accounting = freight.ScenarioPlanningAccounting(frames)
    backend.planning_frame_observer = lambda direction, frame: frames.append(
        (direction, frame.hex())
    )
    backend.planning_frames = frames
    result = dict(status="FAILED", launches=0, connections=0, mutations=0)
    try:
        async with asyncio.timeout(metadata["budgets"]["total_seconds"]):
            await backend.launch(prepared)
            result["launches"] = 1
            await wait_log(backend, prepared, "FREIGHT_DELIVERY_READY")
            if metadata["qualification_id"] == CREATE:
                console(backend, "start_ai RoadProofCompany")
                await wait_log(backend, prepared, "ROAD_PROOF_COMPANY_READY")
            session = await freight.PlannerDeliverySession.connect_secure(
                "127.0.0.1",
                prepared.endpoints[1],
                5,
                key=AuthorizedKey.from_bytes(prepared.key_path.read_bytes()),
                frame_observer=accounting.observe,
            )
            backend.session = session
            result["connections"] = 1
            await session.authenticate("Canonical-fleet", "1", timeout=10)
            w = session.welcome
            if (
                session.state is not AuthState.ACTIVE
                or w is None
                or (w.revision, w.seed, w.width, w.height) != ("15.3", 42, 64, 64)
            ):
                raise ValueError("canonical secure runtime identity mismatch")
            write_json(
                prepared.directory / "runtime-identity.json",
                dict(encrypted=True, welcome=asdict(w)),
            )
            if session.protocol is None:
                raise ValueError("native Admin protocol missing")
            accounting.enter("setup")
            await GameScriptTransport(session, session.protocol).subscribe()
            if metadata["qualification_id"] == CREATE:
                await acquire(backend, prepared, session, accounting, seal, metadata, result)
            else:
                session._frame_observer = backend.planning_frame_observer
                from app.simulation.openttd.freight_canonical_dispatch import (
                    read_boundary,
                    require_stable_boundary,
                )
                from app.simulation.openttd.freight_canonical_runtime import verify_reloaded

                canonical = Path(metadata["canonical_directory"])
                created = load_created(canonical)
                await establish_reload_context(session, prepared.directory, canonical)
                before = await read_boundary(session, prepared.directory, "reload-before")
                await protected_save(backend, prepared, "reload-readback")
                loaded = await verify_reloaded(
                    session,
                    prepared.directory,
                    created=created,
                    save=canonical / "canonical.sav",
                    identity=RELOAD,
                    runtime_sha256=BINARY_SHA256,
                    bridge_sha256=metadata["bridge_sha256"],
                    configuration_sha256=metadata["configuration_sha256"],
                    snapshot_path=prepared.directory / "reload-readback.sav",
                )
                after = await read_boundary(session, prepared.directory, "reload-after")
                require_stable_boundary(before, after)
                for receipt in (before, after):
                    if not receipt.restored or receipt.extra is not None:
                        raise ValueError("reload restored originals-only boundary required")
                    for row, vehicle in zip(receipt.originals, created.state.vehicles, strict=True):
                        if row[:5] != (vehicle.service, vehicle.vehicle, vehicle.tile, 0, 0):
                            raise ValueError("reload original service binding mismatch")
                    if (receipt.cash, receipt.loan, receipt.economy_date) != (
                        created.state.cash,
                        created.state.loan,
                        created.state.economy_date,
                    ):
                        raise ValueError("reload boundary finance/date mismatch")
                compare_canonical(created, loaded)
                write_json(
                    prepared.directory / "reload-observation.json", loaded.model_dump(mode="json")
                )
                write_json(
                    prepared.directory / "reload-correspondence.json",
                    dict(
                        status="EXACT_NATIVE_SEMANTIC_CORRESPONDENCE",
                        execution_contract=RELOAD_ONLY_CONTRACT,
                        source_save_sha256=loaded.source_save_sha256,
                        observation_sha256=sha256(prepared.directory / "reload-observation.json"),
                        before=before.model_dump(mode="json"),
                        after=after.model_dump(mode="json"),
                    ),
                )
                result["status"] = "CANONICAL_RELOAD_ONLY_VERIFIED"
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
        try:
            result.update(failure_details(prepared, error))
        except (OSError, ValueError) as reporting_error:
            result["failure_reporting_error"] = str(reporting_error)
        if backend.process is not None:
            try:
                await protected_save(backend, prepared, "failure")
            except Exception as failure:
                result["failure_save_error"] = str(failure)
    finally:
        try:
            write_json(prepared.directory / "frames.json", frames)
        except Exception as error:
            result["evidence_error"] = type(error).__name__ + ": " + str(error)
            result["status"] = "FAILED_EVIDENCE"
        cleanup = await backend.cleanup(prepared)
        for name in ("stdout.log", "stderr.log"):
            source = prepared.spec.workspace.logs / name
            if source.is_file():
                try:
                    with (
                        source.open("rb") as incoming,
                        (prepared.directory / name).open("xb") as out,
                    ):
                        shutil.copyfileobj(incoming, out)
                except Exception as error:
                    result["evidence_error"] = type(error).__name__ + ": " + str(error)
                    result["status"] = "FAILED_EVIDENCE"
        try:
            cleanup.update(verify_cleanup_endpoints(prepared, cleanup))
            if not cleanup["reaped"] or cleanup["cleanup_error"]:
                raise ValueError("incomplete cleanup")
            prepared.spec.workspace.close()
            cleanup["workspace_disposed"] = not prepared.spec.workspace.root.exists()
            cleanup["credential_removed"] = not prepared.key_path.exists()
        except Exception as error:
            cleanup["verification_error"] = str(error)
            result["status"] = "FAILED_CLEANUP"
        write_json(prepared.directory / "cleanup.json", cleanup)
        write_json(prepared.directory / "result.json", result)
        (prepared.directory / "artifact-manifest.sha256").write_text(manifest(prepared.directory))
    return result


async def qualify_purchase(backend, prepared, session, loaded, metadata):
    from app.simulation.openttd.freight_canonical_dispatch import qualify_paused_purchase
    from app.simulation.openttd.freight_canonical_runtime import verify_intervention_snapshot

    canonical = Path(metadata["canonical_directory"])
    created = load_created(canonical)
    plans = tuple(
        DeliveryPlan.model_validate_json((canonical / f"native-plan-{n}.json").read_bytes()).digest
        for n in range(3)
    )

    async def snapshot(binding, capex, *, started):
        await protected_save(backend, prepared, "purchase-readback")
        directory = prepared.directory / "purchase-readback"
        directory.mkdir()
        return await verify_intervention_snapshot(
            session,
            directory,
            canonical=created.state,
            binding=binding,
            capex=capex,
            started=started,
            identity=RELOAD + "-purchase",
            runtime_sha256=BINARY_SHA256,
            bridge_sha256=metadata["bridge_sha256"],
            configuration_sha256=metadata["configuration_sha256"],
            source_save_sha256=created.source_save_sha256,
            snapshot_path=prepared.directory / "purchase-readback.sav",
        )

    receipt = await qualify_paused_purchase(
        session,
        prepared.directory,
        created.state,
        loaded.state,
        snapshot=snapshot,
        service_plans=plans,
    )
    write_json(prepared.directory / "paused-purchase-qualification.json", receipt)


async def acquire(backend, prepared, session, accounting, seal, metadata, result):
    from app.simulation.openttd.freight_canonical_dispatch import read_boundary
    from app.simulation.openttd.freight_canonical_runtime import collect_canonical
    from app.simulation.openttd.scenario_capital import (
        ScenarioCapitalReadback,
        ScenarioCapitalRequest,
        require_company_policy,
        verify_capital,
    )

    accounting.begin_funding()
    values = []
    for operation in ("initialize", "read"):
        values.append(
            await freight.exchange(
                session,
                ScenarioCapitalRequest(request_id="capital-" + operation, op=operation),
                prepared.directory,
                response_type=ScenarioCapitalReadback,
            )
        )
    accounting.end_funding()
    financing = verify_capital(*values)
    require_company_policy(financing)
    write_json(prepared.directory / "scenario-capital.json", financing)
    before = await protected_save(backend, prepared, "before")
    await construct_originals(
        backend, prepared, session, accounting, before, seal, metadata, result
    )
    console(backend, "pause")
    await read_boundary(session, prepared.directory, name="canonical-paused")
    digests = dict(
        identity=CREATE,
        runtime_sha256=BINARY_SHA256,
        bridge_sha256=metadata["bridge_sha256"],
        configuration_sha256=metadata["configuration_sha256"],
    )
    await protected_save(backend, prepared, "checkpoint-before")
    pre = prepared.directory / "checkpoint-before"
    post = prepared.directory / "checkpoint-after"
    pre.mkdir()
    post.mkdir()
    first = await collect_canonical(
        session,
        pre,
        source_save_sha256="0" * 64,
        snapshot_path=prepared.directory / "checkpoint-before.sav",
        **digests,
    )
    digest = await protected_save(backend, prepared, "canonical")
    second = await collect_canonical(
        session,
        post,
        source_save_sha256=digest,
        snapshot_path=prepared.directory / "canonical.sav",
        **(digests | dict(identity=CREATE + "-post-save")),
    )
    first = first.model_copy(update=dict(source_save_sha256=digest))
    compare_canonical(first, second)
    # Raw collector transcript path is supplied by the collector contract.
    raw = post / "canonical-readback.jsonl"
    second = second.model_copy(update=dict(qualification_id=CREATE))
    seal_canonical_inputs(
        prepared.directory / "canonical-provenance.json",
        prepared.directory / "canonical.sav",
        second,
        raw,
    )
    (prepared.directory / "canonical.sav").chmod(0o444)
    result["status"] = "CANONICAL_CREATED_PENDING_FRESH_PROCESS_RELOAD"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "preflight", "create", "reload"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--stage", choices=(CREATE, RELOAD))
    parser.add_argument("--canonical", type=Path)
    parser.add_argument("--authorize-one-launch", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        if args.stage is None:
            parser.error("prepare requires --stage")
        preflight(prepare(args.directory, stage=args.stage, canonical=args.canonical))
        print("CANONICAL PREFLIGHT PASS; ZERO LAUNCHES")
    elif args.command == "preflight":
        preflight(reopen(args.directory))
        print("CANONICAL PREFLIGHT PASS; ZERO LAUNCHES")
    else:
        if not args.authorize_one_launch:
            parser.error("separate --authorize-one-launch required")
        expected = CREATE if args.command == "create" else RELOAD
        prepared = reopen(args.directory)
        if preflight(prepared)["qualification_id"] != expected:
            parser.error("command does not match separately prepared stage")
        result = asyncio.run(run(prepared, authorize_one_launch=True))
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(0 if result["status"].startswith("CANONICAL_") else 1)


if __name__ == "__main__":
    main()
