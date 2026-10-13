"""One-shot native delivery, reusing the secure loaded-world proof lifecycle."""

import argparse
import asyncio
import configparser
import json
import os
import re
import shutil
import struct
import zipfile
import zlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.admin_protocol import AdminFrameDecoder
from app.simulation.openttd.freight_delivery import (
    OBS_SECONDS,
    DeliveryPlan,
    DeliveryReadback,
    DeliveryRequest,
    admit,
    verify_delivery,
    verify_observation,
    verify_snapshot,
)
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptTransport,
    decode_gamescript,
    encode_gamescript,
)
from app.simulation.openttd.runtime.base import LaunchSpecification
from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.secure_admin import AuthState

from . import road_freight_infrastructure as freight
from . import road_vehicle_lifecycle as vehicle
from .endpoints import verify_cleanup_endpoints
from .graphics import ARCHIVE_SHA256, stage_opengfx
from .harness import (
    BINARY as DEFAULT_BINARY,
)
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
from .qualification_native import QualificationNativeBackend
from .road_mutation import console, save, wait_log

BINARY = Path(os.environ.get("OPENTTD_BINARY", str(DEFAULT_BINARY))).expanduser().resolve()
GRAPHICS_ARCHIVE = (
    Path(
        os.environ.get(
            "OPENTTD_OPENGFX_ARCHIVE",
            str(PROJECT / "artifacts/runtime/verified-assets/opengfx-8.0-all.zip"),
        )
    )
    .expanduser()
    .resolve()
)

SOURCE = PROJECT / "artifacts/runtime/openttd-15.3-road-freight-infrastructure-attempt1"
PREVIOUS = PROJECT / "artifacts/runtime/openttd-15.3-road-vehicle-lifecycle-attempt2"
PACKAGE = PROJECT / "app/simulation/openttd/freight_delivery_package"
BUDGETS = dict(
    launches=1,
    connections=1,
    retries=0,
    reconnects=0,
    requests=26,
    mutations=10,
    layouts=64,
    engines=32,
    industries=32,
    road_tiles=48,
    observation_script_ticks=4440,
    observation_route_ticks_per_tile=128,
    observation_slack_ticks=2048,
    movement_stall_ticks=2048,
    permitted_quarter_transitions=1,
    permitted_year_transitions=0,
    samples=4441,
    poll_interval=1,
    observation_economy_days=60,
    observation_seconds=OBS_SECONDS,
    total_seconds=180,
    response_bytes=768,
    gsadmin_bytes=1450,
)


DEMO_BUDGETS = BUDGETS | dict(world_preparation_mutations=52)
PLANNER_BUDGETS = DEMO_BUDGETS | dict(
    qualification_seconds=300,
    supplemental_requests=292,
    total_seconds=600,
    construction_commands=64,
)

NETWORK_BUDGETS = PLANNER_BUDGETS | dict(
    requests=58,
    mutations=22,
    supplemental_requests=1168,
    total_seconds=900,
    world_preparation_mutations=108,
    construction_commands=128,
    selected_services=2,
)


def flat_heightmap():
    """64x64 grayscale 1: native heightmap loader maps every interior tile to height 1."""

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\1" * 64) * 64))
        + chunk(b"IEND", b"")
    )


class DemoBackend(vehicle.VehicleBackend):
    def preflight(self, prepared):
        key_path = prepared.key_path
        if (
            key_path.is_symlink()
            or key_path.stat().st_mode & 0o777 != 0o600
            or key_path.stat().st_uid != os.getuid()
        ):
            raise ValueError("private key ownership/permissions invalid")
        self._key = AuthorizedKey.from_bytes(key_path.read_bytes())
        graphics = json.loads((prepared.directory / "graphics-identity.json").read_text())
        if (
            self._key.public_hex != prepared.public_key
            or graphics["archive_sha256"] != ARCHIVE_SHA256
            or sha256(BINARY) != BINARY_SHA256
            or vehicle.matching_processes(BINARY)
        ):
            raise ValueError("pinned demo executable/assets/ownership mismatch")

    async def cleanup(self, prepared):
        value = await super().cleanup(prepared)
        value["remaining_processes"] = vehicle.matching_processes(BINARY)
        value["runtime_errors"] = [
            e for e in value["cleanup_error"] if e["stage"] == "final_log_health"
        ]
        value["cleanup_error"] = [
            e for e in value["cleanup_error"] if e["stage"] != "final_log_health"
        ]
        return value

    def validate_launch(self, prepared):
        expected = vehicle.load_argv(
            BINARY.resolve(),
            prepared.spec.workspace.config,
            prepared.endpoints[0],
            prepared.spec.workspace.root / "heightmap.png",
        )
        expected += ("-G", "42")
        if (
            prepared.spec.argv != expected
            or sha256(BINARY) != BINARY_SHA256
            or vehicle.matching_processes(BINARY)
        ):
            raise ValueError("native generated-demo identity/ownership mismatch")


def backend_for(metadata):
    cls = (
        PlannerBackend
        if metadata.get("planner", False)
        else (DemoBackend if metadata.get("demo", False) else vehicle.VehicleBackend)
    )
    return cls(authorized_one_launch=True)


def staged_package(demo, planner=False, network=False):
    out = {
        p.name: p.read_bytes()
        for p in PACKAGE.glob("*.nut")
        if p.name not in ("demo.nut", "planner.nut", "network.nut")
    }
    if demo:
        out["delivery.nut"] = out["main.nut"]
        out["main.nut"] = (PACKAGE / "demo.nut").read_bytes()
        out["info.nut"] = out["info.nut"].replace(b'"FreightDeliveryProof"', b'"FreightDemoProof"')
    if planner:
        from app.simulation.openttd.qualification_bridge import qualification_bridge_source

        out["demo-world.nut"] = out["main.nut"]
        out["delivery.nut"] = out["delivery.nut"].replace(
            b"function Handle(q)", b"function DeliveryHandle(q)"
        )
        out["delivery.nut"] = out["delivery.nut"].replace(
            b"function Execute(i)", b"function DeliveryExecute(i)"
        )
        out["delivery.nut"] = out["delivery.nut"].replace(
            b"function Tiles(a)", b"function DeliveryTiles(a)"
        )
        out["delivery.nut"] = out["delivery.nut"].replace(
            b"function Quote(i)", b"function DeliveryQuote(i)"
        )
        out["main.nut"] = (PACKAGE / "planner.nut").read_bytes()
        out["qualification.nut"] = qualification_bridge_source().encode()
        out["info.nut"] = out["info.nut"].replace(b'"FreightDemoProof"', b'"PlannerFreightProof"')
    if network:
        out["network-parent.nut"] = (
            out["main.nut"]
            .replace(b"function Handle(q)", b"function PlannerHandle(q)")
            .replace(b"function Quote(i)", b"function PlannerQuote(i)")
        )
        out["network-parent.nut"] = out["network-parent.nut"].replace(
            b"planner_requests>=292", b"planner_requests>=1168"
        )
        out["network-parent.nut"] = (
            out["network-parent.nut"]
            .replace(b'FREIGHT_ROUTE_EDGE a="+a', b'FREIGHT_ROUTE_EDGE plan="+dplan+" a="+a')
            .replace(
                b'FREIGHT_ROUTE_FRONTS origin="', b'FREIGHT_ROUTE_FRONTS plan="+dplan+" origin="'
            )
        )
        out["delivery.nut"] = out["delivery.nut"].replace(b"drequests>=26", b"drequests>=58")
        out["delivery.nut"] = out["delivery.nut"].replace(
            b"GSVehicleList().Count()!=1", b"GSVehicleList().Count()!=ExpectedVehicleCount()"
        )
        out["main.nut"] = (PACKAGE / "network.nut").read_bytes()
        out["info.nut"] = out["info.nut"].replace(
            b'"PlannerFreightProof"', b'"NetworkFreightProof"'
        )
    return out


class PlannerBackend(DemoBackend, QualificationNativeBackend):
    """Reuse qualification evidence validators on the owned freight runtime."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.qualification_coordinator = None
        self.secure_connection = None
        self.structural_session = None
        self.query_operation_baseline = 0


class DeliverySession(vehicle.VehicleSecureSession):
    def validate_outbound(self, frame):
        if len(frame) < 3 or struct.unpack_from("<H", frame)[0] != len(frame):
            raise ValueError("valid framed encrypted request required")
        if len(frame) >= 3 and frame[2] == ADMIN_GAMESCRIPT:
            if self.state is not AuthState.ACTIVE:
                raise ValueError("ACTIVE encrypted connection required")
            DeliveryRequest.model_validate_json(decode_gamescript(frame[3:])).to_bytes()
        else:
            super().validate_outbound(frame)


class PlannerDeliverySession(DeliverySession):
    def validate_outbound(self, frame):
        if len(frame) >= 3 and frame[2] == ADMIN_GAMESCRIPT:
            from app.simulation.openttd.cargo_page import CargoPageRequest
            from app.simulation.openttd.freight_planning import PlanningSelectionRequest
            from app.simulation.openttd.freight_runtime_planning import PlanningRead
            from app.simulation.openttd.industry_cargo import IndustryCargoRequest
            from app.simulation.openttd.industry_page import IndustryPageRequest
            from app.simulation.openttd.industry_production import IndustryProductionRequest
            from app.simulation.openttd.qualification_clock import (
                EconomyClockRequest,
                IndustryLifetimeRequest,
            )

            if self.state is not AuthState.ACTIVE or struct.unpack_from("<H", frame)[0] != len(
                frame
            ):
                raise ValueError("active correctly framed planning request required")
            raw = decode_gamescript(frame[3:])
            value = json.loads(raw)
            if value.get("type") == "planning_read":
                PlanningRead.model_validate_json(raw).to_bytes()
                return
            if value.get("op") == "select":
                PlanningSelectionRequest.model_validate_json(raw).to_bytes()
                return
            classes = dict(
                economy_clock=EconomyClockRequest,
                industry_lifetime=IndustryLifetimeRequest,
                industry_page=IndustryPageRequest,
                industry_cargo=IndustryCargoRequest,
                cargo_page=CargoPageRequest,
                industry_production=IndustryProductionRequest,
            )
            if value.get("type") in classes:
                classes[value["type"]].parse(raw)
                return
        super().validate_outbound(frame)


def attempt_number(directory):
    match = re.fullmatch(
        r"openttd-15\.3-first-freight-delivery-attempt([1-9][0-9]*)", directory.name
    )
    if match is None:
        raise ValueError("use an explicit fresh freight-delivery attempt identifier")
    return int(match[1])


def recovery_path(directory):
    return directory.with_name(directory.name + "-cleanup-recovery.json")


def recover_cleanup(directory):
    """Finish owned disposal after a reaped script failure; never rewrite consumed evidence."""
    cleanup = json.loads((directory / "cleanup.json").read_text())
    if (
        cleanup.get("reaped") is not True
        or cleanup.get("remaining_processes") != []
        or cleanup.get("cleanup_error") != [dict(stage="final_log_health", type="RuntimeError")]
        or vehicle.matching_processes(BINARY)
    ):
        raise ValueError("only a reaped runtime-log-health failure can be recovered")
    m = json.loads((directory / "PRELAUNCH.json").read_text())
    root = Path(m["workspace"])
    prepared = type(
        "RecoveryEndpoints",
        (),
        dict(directory=directory, endpoints=(m["game_port"], m["admin_port"])),
    )()
    endpoint = verify_cleanup_endpoints(
        prepared, dict(reaped=True, remaining_processes=[], cleanup_error=[])
    )
    if root.exists():
        RuntimeWorkspace.reopen(root).close()
    value = dict(
        original_manifest_sha256=sha256(directory / "artifact-manifest.sha256"),
        original_cleanup_sha256=sha256(directory / "cleanup.json"),
        workspace=str(root),
        workspace_disposed=not root.exists(),
        credential_removed=not (root / ".admin-secret").exists(),
        **endpoint,
    )
    write_json(recovery_path(directory), value)
    return value


def consumed_identity(directory):
    """Bind a consumed predecessor without reinterpreting or changing its source."""
    seal = sha256(directory / "PRELAUNCH.json")
    claim = json.loads((directory / "CLAIM.json").read_text())
    cleanup = json.loads((directory / "cleanup.json").read_text())
    recovery = None
    if recovery_path(directory).exists():
        recovery = json.loads(recovery_path(directory).read_text())
        if (
            recovery["original_manifest_sha256"] != sha256(directory / "artifact-manifest.sha256")
            or recovery["original_cleanup_sha256"] != sha256(directory / "cleanup.json")
            or cleanup.get("cleanup_error") != [dict(stage="final_log_health", type="RuntimeError")]
            or not all(
                recovery.get(k) is True
                for k in ("sockets_closed", "workspace_disposed", "credential_removed")
            )
        ):
            raise ValueError("cleanup recovery does not bind the consumed failure")
        cleanup = cleanup | recovery | dict(cleanup_error=[])
    if (
        manifest(directory) != (directory / "artifact-manifest.sha256").read_text()
        or seal != (directory / "PRELAUNCH.sha256").read_text().strip()
        or claim != dict(consumed=True, prelaunch_digest=seal, launches_allowed=1, retries=0)
        or not all(
            cleanup.get(k) is True
            for k in ("reaped", "sockets_closed", "workspace_disposed", "credential_removed")
        )
        or cleanup.get("cleanup_error")
        or cleanup.get("remaining_processes")
    ):
        raise ValueError("consumed freight predecessor integrity/cleanup mismatch")
    return dict(
        directory=str(directory),
        prelaunch_sha256=seal,
        artifact_manifest_sha256=sha256(directory / "artifact-manifest.sha256"),
        cleanup_recovery_sha256=sha256(recovery_path(directory)) if recovery is not None else None,
    )


def prepare(directory, *, demo=False, planner=False, batch_limit=20, network=False):
    if network and (not demo or not planner):
        raise ValueError("network requires --demo --planner")
    if planner and not demo:
        raise ValueError("planner demonstration requires --demo")
    if type(batch_limit) is not int or not 1 <= batch_limit <= 65535:
        raise ValueError("positive bounded delivery batch required")
    number = attempt_number(directory)
    prior = (
        consumed_identity(
            directory.with_name(f"openttd-15.3-first-freight-delivery-attempt{number - 1}")
        )
        if number > 1
        else None
    )
    predecessor = vehicle.verify_receipt(PREVIOUS) if not demo else None
    source = freight.verify_receipt(SOURCE) if not demo else None
    original = SOURCE / "before.sav"
    if source is not None and sha256(original) != source["before_save_sha256"]:
        raise ValueError("native source save mismatch")
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
        workspace.config.write_text(
            workspace.config.read_text().replace(
                "pause_on_newgame = true", "pause_on_newgame = false"
            )
            + "\n[misc]\ngraphicsset = OpenGFX\n[ai]\nai_in_multiplayer = true\n"
            "[game_scripts]\nRoadFreightProof = \n"
        )
        if demo:
            workspace.config.write_text(
                workspace.config.read_text()
                + "\n[game_creation]\nmap_x = 6\nmap_y = 6\nlandscape = temperate\n"
                "starting_year = 1950\nland_generator = 1\nheightmap_height = 1\n"
                "tree_placer = 0\namount_of_rivers = 0\n"
                "[difficulty]\nnumber_towns = 4\nindustry_density = 0\n"
                "max_no_competitors = 0\nvehicle_breakdowns = 0\ndisasters = false\n"
            )
            (workspace.root / "heightmap.png").write_bytes(flat_heightmap())
            shutil.copyfile(workspace.root / "heightmap.png", directory / "heightmap.png")
        if planner:
            workspace.config.write_text(
                workspace.config.read_text()
                + "\n[economy]\ntimekeeping_units = 0\n"
                + ("multiple_industry_per_town = true\n" if network else "")
                + "[newgrf]\n"
            )
        graphics = stage_opengfx(
            GRAPHICS_ARCHIVE,
            workspace.root / "baseset/OpenGFX",
        )
        write_json(
            directory / "graphics-identity.json",
            dict(asdict(graphics), directory=str(graphics.directory)),
        )
        for src, parent, name in [
            (PACKAGE, workspace.game, "RoadFreightProof"),
            (
                PROJECT / "app/simulation/openttd/road_company_package",
                workspace.ai,
                "RoadProofCompany",
            ),
        ]:
            target = parent / name
            target.mkdir()
            if src == PACKAGE:
                for name, data in staged_package(demo, planner, network).items():
                    (target / name).write_bytes(data)
            else:
                for p in src.glob("*.nut"):
                    shutil.copyfile(p, target / p.name)
        if not demo:
            shutil.copyfile(original, workspace.root / "source.sav")
        argv = vehicle.load_argv(
            BINARY.resolve(),
            workspace.config,
            reservation.game_port,
            workspace.root / ("heightmap.png" if demo else "source.sav"),
        )
        if demo:
            argv += ("-G", "42")
        spec = LaunchSpecification(
            workspace,
            RuntimeIdentity(BINARY.resolve(), "15.3", BINARY_SHA256),
            argv,
            workspace.root,
            workspace.environment,
            workspace.logs / "stdout.log",
            workspace.logs / "stderr.log",
        )
        snapshot_paths = sorted(PACKAGE.glob("*.nut")) + [
            PROJECT / "app/simulation/openttd/freight_delivery.py",
            PROJECT / "app/simulation/openttd/proof/freight_delivery.py",
            PROJECT / "tests/test_freight_delivery.py",
            PROJECT / "docs/first-freight-delivery-proof.md",
        ]
        if planner:
            snapshot_paths += sorted((PROJECT / "app/planning").rglob("*.py"))
            snapshot_paths += [
                PROJECT / "app/simulation/openttd" / (name + ".py")
                for name in (
                    "freight_planning",
                    "freight_native_network",
                    "freight_runtime_planning",
                    "freight_planning_replay",
                    "prepared_source_correspondence",
                    "supplemental_planning_facts",
                    "world_planning_observation",
                    "qualified_production",
                    "qualification_session",
                )
            ]
            snapshot_paths += [PROJECT / "tests/test_freight_planning.py", PROJECT / "README.md"]
            snapshot_paths += [
                PROJECT / "tests/reference/freight_attempt6_route.json",
                PROJECT / "tests/reference/freight_attempt7_construction.json",
                PROJECT / "tests/reference/map_api_15_3/script_map.hpp",
                PROJECT / "tests/reference/map_api_15_3/SOURCE.txt",
            ]
        if network:
            snapshot_paths += [
                PROJECT / "tests/test_native_freight_network.py",
                PROJECT / "tests/test_network_world_preparation.py",
                PROJECT / "app/experiments/freight_network.py",
            ]
        archive = directory / "frozen-source.zip"
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
            for src in snapshot_paths:
                info = zipfile.ZipInfo(str(src.relative_to(PROJECT)))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, src.read_bytes())
            if planner:
                for name, data in staged_package(demo, planner, network).items():
                    z.writestr("staged/" + name, data)
                z.writestr("staged/openttd.cfg", workspace.config.read_bytes())
        frozen = source_freeze()
        if planner:
            frozen.update({str(p.resolve()): sha256(p) for p in snapshot_paths})
        frozen[str(BINARY)] = sha256(BINARY)
        frozen[str(archive)] = sha256(archive)
        for p in (
            [
                PROJECT / "tests/test_freight_delivery.py",
                PROJECT / "docs/first-freight-delivery-proof.md",
            ]
            + list(PACKAGE.glob("*.nut"))
            + ([] if demo else list(SOURCE.iterdir()) + list(PREVIOUS.iterdir()))
            + list(workspace.root.rglob("*"))
        ):
            if p.is_file() and p.name != ".admin-secret":
                frozen[str(p.resolve())] = sha256(p)
        m = dict(
            schema="first-freight-delivery-prelaunch-v1",
            attempt=number,
            demo=demo,
            planner=planner,
            network=network,
            construction_readback_version=1 if planner else None,
            delivery_batch_limit=batch_limit if planner else None,
            delivery_predecessor=prior,
            workspace=str(workspace.root),
            binary_sha256=BINARY_SHA256,
            binary=str(BINARY),
            argv=list(argv),
            public_key=key.public_hex,
            game_port=reservation.game_port,
            admin_port=reservation.admin_port,
            source=(
                dict(kind="NATIVE_FLAT_HEIGHTMAP", input_sha256=sha256(directory / "heightmap.png"))
                if demo
                else dict(
                    save=str(original),
                    save_sha256=sha256(original),
                    receipt_sha256=sha256(SOURCE / "receipt.json"),
                )
            ),
            predecessor=(
                dict(executor_source_digest=sha256(archive))
                if demo
                else dict(
                    directory=str(PREVIOUS),
                    receipt_sha256=sha256(PREVIOUS / "receipt.json"),
                    plan_digest=predecessor["plan_digest"] if predecessor is not None else None,
                )
            ),
            world=dict(
                source="NATIVE_GENERATED_DEMO" if demo else "COPIED_NATIVE_PROVEN_COMPANY_WORLD",
                seed=42,
                width=64,
                height=64,
            ),
            plan_policy=dict(
                company=0,
                mode="road",
                selection=(
                    "native compatible engine and genuine industry OD; "
                    "first admitted bounded L footprint"
                ),
                max_cost=100000,
                station_count=2,
                depot_count=1,
                vehicle_count=1,
                orders=["FULL_LOAD", "NO_LOAD"],
                monitor="native company/cargo/industry pickup and final delivery",
            ),
            execution_command=[
                str(PROJECT / ".venv/bin/python"),
                "-m",
                "app.simulation.openttd.proof.freight_delivery",
                "run",
                str(directory),
                "--authorize-one-launch",
            ],
            budgets=NETWORK_BUDGETS
            if network
            else PLANNER_BUDGETS
            if planner
            else DEMO_BUDGETS
            if demo
            else BUDGETS,
            cleanup=[
                "reap process",
                "close secure stream and listeners",
                "retain failure save/logs",
                "remove credential",
                "dispose copied world",
            ],
            authorization=(
                "explicit operator authorization for this single launch after preflight; "
                "native feasibility admission before every mutation"
            ),
            frozen=frozen,
        )
        write_json(directory / "PRELAUNCH.json", m)
        (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")
        return PreparedProof(
            directory, spec, secret, key.public_hex, (reservation.game_port, reservation.admin_port)
        )
    finally:
        reservation.close()


def reopen(directory):
    m = json.loads((directory / "PRELAUNCH.json").read_text())
    binary = Path(m.get("binary", str(DEFAULT_BINARY)))
    workspace = RuntimeWorkspace.reopen(Path(m["workspace"]))
    spec = LaunchSpecification(
        workspace,
        RuntimeIdentity(binary, "15.3", BINARY_SHA256),
        tuple(m["argv"]),
        workspace.root,
        workspace.environment,
        workspace.logs / "stdout.log",
        workspace.logs / "stderr.log",
    )
    return PreparedProof(
        directory,
        spec,
        workspace.root / ".admin-secret",
        m["public_key"],
        (m["game_port"], m["admin_port"]),
    )


def validate_network_world_inputs(prepared, metadata):
    """Admit only a fresh generated world; retained failure saves are evidence."""
    root = prepared.spec.workspace.root
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read_string(prepared.spec.workspace.config.read_text())
        if not config.getboolean("economy", "multiple_industry_per_town"):
            raise ValueError("network requires multiple industries per town")
    except configparser.Error as error:
        raise ValueError("network preparation config is ambiguous or incomplete") from error
    heightmap = root / "heightmap.png"
    retained = prepared.directory / "heightmap.png"
    if (
        heightmap.is_symlink()
        or retained.is_symlink()
        or heightmap.read_bytes() != flat_heightmap()
        or retained.read_bytes() != heightmap.read_bytes()
        or metadata["source"] != dict(kind="NATIVE_FLAT_HEIGHTMAP", input_sha256=sha256(retained))
    ):
        raise ValueError("network fresh heightmap identity mismatch")
    if any(path.suffix.lower() == ".sav" for path in root.rglob("*")):
        raise ValueError("network disposable world contains a retained save")


def preflight(p):
    if (p.directory / "CLAIM.json").exists():
        raise ValueError("one attempt consumed")
    m = json.loads((p.directory / "PRELAUNCH.json").read_text())
    if (
        sha256(p.directory / "PRELAUNCH.json")
        != (p.directory / "PRELAUNCH.sha256").read_text().strip()
        or m["schema"] != "first-freight-delivery-prelaunch-v1"
        or m["attempt"] != attempt_number(p.directory)
        or m["budgets"]
        != (
            NETWORK_BUDGETS
            if m.get("network", False)
            else PLANNER_BUDGETS
            if m.get("planner", False)
            else DEMO_BUDGETS
            if m.get("demo", False)
            else BUDGETS
        )
    ):
        raise ValueError("sealed budgets mismatch")
    verify_freeze(m["frozen"])
    if m["attempt"] > 1 and m["delivery_predecessor"] != consumed_identity(
        p.directory.with_name(f"openttd-15.3-first-freight-delivery-attempt{m['attempt'] - 1}")
    ):
        raise ValueError("delivery predecessor mismatch")
    if not m.get("demo", False):
        vehicle.verify_receipt(PREVIOUS)
        source = freight.verify_receipt(SOURCE)
        if sha256(p.spec.workspace.root / "source.sav") != source["before_save_sha256"]:
            raise ValueError("disposable source mismatch")
    elif (p.spec.workspace.root / "heightmap.png").read_bytes() != flat_heightmap():
        raise ValueError("deterministic heightmap mismatch")
    if m.get("network", False):
        validate_network_world_inputs(p, m)
    for name, data in staged_package(
        m.get("demo", False), m.get("planner", False), m.get("network", False)
    ).items():
        if data != (p.spec.workspace.game / "RoadFreightProof" / name).read_bytes():
            raise ValueError("stale delivery package")
    if (PACKAGE / "infrastructure.nut").read_bytes() != (
        vehicle.road.PACKAGES / "road_freight_package/main.nut"
    ).read_bytes() or (PACKAGE / "vehicle.nut").read_bytes() != (
        vehicle.PACKAGE / "main.nut"
    ).read_bytes():
        raise ValueError("proven dependency mismatch")
    if not p.spec.workspace.root.is_relative_to(p.directory / "isolated"):
        raise ValueError("workspace ownership mismatch")
    backend = backend_for(m)
    backend.preflight(p)
    backend.validate_launch(p)
    reservation = EndpointReservation.allocate(*p.endpoints)
    reservation.close()


async def exchange(session, q, directory, *, response_type=DeliveryReadback):
    raw = q.to_bytes()
    (directory / (q.request_id + "-request.json")).write_bytes(raw)
    await session.send(encode_gamescript(raw))
    decoder = AdminFrameDecoder()
    async with asyncio.timeout(OBS_SECONDS if getattr(q, "op", None) == "observe" else 20):
        while True:
            chunk = await session.receive()
            if not chunk:
                raise ConnectionError("secure stream ended")
            for kind, body in decoder.feed_frames(chunk):
                if kind != SERVER_GAMESCRIPT:
                    raise ValueError("unexpected packet")
                response = decode_gamescript(body)
                (directory / (q.request_id + "-response.json")).write_bytes(response)
                return response_type.parse_for(getattr(q, "admission_request", q), response)


def construction_evidence(plan, records, *, planner=False, reused_stages=()):
    """Bind fresh native command accounting and independent owned-state reads."""
    costs = []
    digests = []
    previous = records["inspect-1"].s[3]
    for i in range(10):
        built, read = records[f"build-{i}"], records[f"read-{i}"]
        verify_snapshot(plan, built)
        verify_snapshot(plan, read)
        if (built.status, read.status, built.s[22], read.s[22]) != ("BUILT", "READ", i + 1, i + 1):
            raise ValueError("construction result/readback sequence mismatch")
        cost = built.s[23]
        if (
            cost < 0
            or ((2 if planner else 0) <= i < 7 and i not in reused_stages and cost == 0)
            or (i >= 7 and cost != 0)
        ):
            raise ValueError("native construction/order/start cost mismatch")
        if i < 9 and (previous - built.s[3] != cost or built.s[3] != read.s[3]):
            raise ValueError("native spending/readback mismatch")
        previous = read.s[3]
        costs.append(cost)
        digests.extend([built.digest, read.digest])
    return dict(
        mutation_costs=costs,
        construction_purchase_spending=sum(costs),
        construction_native_digests=digests,
    )


def command_readback_evidence(log_path, plan, records, *, network_plans=()):
    """Replay bounded native command outcomes; failures remain failures."""
    stages = []
    commands = []
    for line in log_path.read_text().splitlines():
        match = re.search(r"FREIGHT_CONSTRUCTION_(STAGE|ROAD|FACILITY) (.+)$", line)
        if match is None:
            continue
        data = dict(item.split("=", 1) for item in match[2].split())
        digest = data.pop("plan")
        if digest != plan.digest:
            if digest in network_plans:
                continue
            raise ValueError("construction command provenance mismatch")
        kind = match[1]
        stage = int(data["stage"])
        if kind == "STAGE":
            if stage != len(stages) or int(data["result"]) != 1:
                raise ValueError("construction stage command failed or duplicated")
            cost = records[f"build-{stage}"].s[23]
            if (
                int(data["quoted"]) != cost
                or int(data["cost"]) != cost
                or int(data["spent"]) != cost
            ):
                raise ValueError("construction command quote/spending mismatch")
            stages.append(data)
        else:
            if not 0 <= stage <= 5 or len(commands) >= 64:
                raise ValueError("construction command readback bounds")
            satisfied = data["classification"] == "ALREADY_SATISFIED"
            if (
                data["classification"] not in ("ALREADY_SATISFIED", "COMMAND_SUCCEEDED")
                or int(data["result"]) != 1
                or int(data["after"]) != 1
                or int(data["before"]) != int(satisfied)
                or int(data["spent"]) < 0
                or (satisfied and int(data["spent"]) != 0)
            ):
                raise ValueError("failed or inconsistent construction command")
            commands.append(dict(kind=kind, **data))
    if len(stages) != 10:
        raise ValueError("missing construction command stage readback")
    for stage in range(6):
        group = [c for c in commands if int(c["stage"]) == stage]
        if not group or sum(int(c["spent"]) for c in group) != int(stages[stage]["cost"]):
            raise ValueError("construction command accounting incomplete")
    return dict(construction_command_readbacks=commands, construction_stage_readbacks=stages)


async def run(p):
    preflight(p)
    seal = sha256(p.directory / "PRELAUNCH.json")
    m = json.loads((p.directory / "PRELAUNCH.json").read_text())
    write_json(
        p.directory / "CLAIM.json",
        dict(consumed=True, prelaunch_digest=seal, launches_allowed=1, retries=0),
    )
    backend = backend_for(m)
    frames = []
    accounting = None
    if m.get("planner", False):
        from .qualification_accounting import QualificationFrameBudget

        class PlanningAccounting(QualificationFrameBudget):
            def observe(self, direction, frame):
                frames.append((direction, frame.hex()))
                super().observe(direction, frame)

        accounting = PlanningAccounting()
    backend.planning_frame_observer = lambda d, f: frames.append((d, f.hex()))
    backend.planning_frames = frames
    result: dict[str, Any] = dict(
        preflight="PASS", launches=0, connections=0, requests=0, mutations=0, status="FAILED"
    )
    try:
        async with asyncio.timeout(m["budgets"]["total_seconds"]):
            await backend.launch(p)
            result["launches"] = 1
            await wait_log(backend, p, "FREIGHT_DELIVERY_READY")
            if m.get("demo", False):
                console(backend, "start_ai RoadProofCompany")
                await wait_log(backend, p, "ROAD_PROOF_COMPANY_READY")
            session_class = PlannerDeliverySession if m.get("planner", False) else DeliverySession
            session = await session_class.connect_secure(
                "127.0.0.1",
                p.endpoints[1],
                5,
                key=AuthorizedKey.from_bytes(p.key_path.read_bytes()),
                frame_observer=accounting.observe
                if accounting is not None
                else backend.planning_frame_observer,
            )
            backend.session = session
            result["connections"] = 1
            await session.authenticate("Freight-delivery", "1", timeout=10)
            w = session.welcome
            if w is None or (w.revision, w.seed, w.width, w.height) != ("15.3", 42, 64, 64):
                raise ValueError("native runtime mismatch")
            write_json(
                p.directory / "runtime-identity.json",
                dict(encrypted=session.state is AuthState.ACTIVE, welcome=asdict(w)),
            )
            if session.protocol is None:
                raise ValueError("negotiated native Admin protocol required")
            if accounting is not None:
                accounting.enter("setup")
            await GameScriptTransport(session, session.protocol).subscribe()
            before = await save(backend, p, "before")

            async def query(op, id, arg=0, plan=seal):
                if result["requests"] >= m["budgets"]["requests"]:
                    raise ValueError("request budget exhausted")
                if op == "build":
                    result["mutations"] += 1
                result["requests"] += 1
                return await exchange(
                    session, DeliveryRequest(op=op, request_id=id, plan=plan, arg=arg), p.directory
                )

            if m.get("network", False):
                from app.simulation.openttd.freight_native_network import execute_network

                await execute_network(backend, p, session, accounting, before, seal, m, result)
                result["status"] = "NATIVE_MULTI_SERVICE_DELIVERY_VERIFIED"
                return result
            service = None
            source_save = before
            if m.get("planner", False):
                from app.simulation.openttd.freight_runtime_planning import plan_same_world

                service, source_save = await plan_same_world(
                    backend, p, session, accounting, before, batch_limit=m["delivery_batch_limit"]
                )
                result["supplemental_requests"] = backend.planning_read_count
                result["qualification_requests"] = sum(
                    v[0]
                    for _, v in service.road.input.admitted.world.qualification.evidence.phase_usage
                )
                request = service.selection_request()
                admission = await exchange(session, request, p.directory)
                result["requests"] += 1
            else:
                admission = await query("inspect", "inspect-1")
            plan = admit(
                admission,
                seal,
                source_save if m.get("demo", False) else m["source"]["save_sha256"],
                m["predecessor"].get("receipt_sha256"),
                executor_source=m["predecessor"].get("executor_source_digest"),
                selection_digest=service.execution_plan_digest if service is not None else None,
            )
            write_json(p.directory / "plan.json", plan.model_dump(mode="json"))
            binding = (
                service.validate_native_selection(plan, admission) if service is not None else None
            )
            if binding is not None:
                write_json(p.directory / "planning-binding.json", binding)
            baseline = None
            records = {"inspect-1": admission}
            for i in range(10):
                built = await query("build", f"build-{i}", i, plan.digest)
                read = await query("read", f"read-{i}", i, plan.digest)
                if built.status != "BUILT" or built.s[22] != i + 1:
                    raise ValueError(f"mutation {i} failed: {built.status}")
                records[f"build-{i}"] = built
                records[f"read-{i}"] = read
                verify_snapshot(plan, read)
                if (
                    read.status != "READ"
                    or read.s[22] != i + 1
                    or (i < 9 and read.s[3] != built.s[3])
                ):
                    raise ValueError("independent construction/readback mismatch")
                if i == 8:
                    baseline = read
            construction = construction_evidence(plan, records, planner=service is not None)
            observations = []
            for phase in range(4):
                r = await query("observe", f"observe-{phase}", phase, plan.digest)
                if r.status != "OBSERVED":
                    raise ValueError(f"observation {phase}: {r.status}")
                verify_observation(plan, r, phase)
                observations.append(r)
            final = await query("finish", "finish-1", 0, plan.digest)
            receipt = verify_delivery(plan, baseline, observations, final)
            receipt.update(construction)
            if m.get("construction_readback_version") == 1:
                receipt.update(
                    command_readback_evidence(p.spec.workspace.logs / "stderr.log", plan, records)
                )
            if binding is not None:
                receipt["planning_binding"] = binding
            receipt.update(
                before_save_sha256=before, after_save_sha256=await save(backend, p, "after")
            )
            write_json(p.directory / "receipt.json", receipt)
            result["status"] = "NATIVE_DELIVERY_VERIFIED"
    except Exception as e:
        result["error"] = type(e).__name__ + ": " + str(e)
        if backend.process is not None:
            try:
                await save(backend, p, "failure")
            except Exception as failure:
                result["failure_save_error"] = str(failure)
    finally:
        result["launches"] = int(backend.process is not None)
        write_json(p.directory / "frames.json", frames)
        cleanup = await backend.cleanup(p)
        for name in ["stdout.log", "stderr.log"]:
            if (p.spec.workspace.logs / name).is_file():
                shutil.copyfile(p.spec.workspace.logs / name, p.directory / name)
        try:
            cleanup.update(verify_cleanup_endpoints(p, cleanup))
            if not cleanup["reaped"] or cleanup["cleanup_error"]:
                raise ValueError("incomplete cleanup")
            p.spec.workspace.close()
            cleanup["workspace_disposed"] = not p.spec.workspace.root.exists()
            cleanup["credential_removed"] = not p.key_path.exists()
        except Exception as e:
            cleanup["verification_error"] = str(e)
            result["status"] = "FAILED_CLEANUP"
        write_json(p.directory / "cleanup.json", cleanup)
        write_json(p.directory / "result.json", result)
        (p.directory / "artifact-manifest.sha256").write_text(manifest(p.directory))
    return result


def verify_receipt(directory):
    directory = directory.resolve()
    if manifest(directory) != (directory / "artifact-manifest.sha256").read_text():
        raise ValueError("artifact manifest mismatch")
    m = json.loads((directory / "PRELAUNCH.json").read_text())
    seal = sha256(directory / "PRELAUNCH.json")
    legacy_budgets = DEMO_BUDGETS | dict(
        observation_script_ticks=2048,
        samples=2049,
        observation_economy_days=30,
        observation_seconds=60,
        response_bytes=512,
    )
    for key in (
        "observation_route_ticks_per_tile",
        "observation_slack_ticks",
        "movement_stall_ticks",
        "permitted_quarter_transitions",
        "permitted_year_transitions",
    ):
        legacy_budgets.pop(key)
    legacy = m.get("demo", False) and not m.get("planner", False) and m["budgets"] == legacy_budgets
    if seal != (directory / "PRELAUNCH.sha256").read_text().strip() or (
        not legacy
        and m["budgets"]
        != (
            NETWORK_BUDGETS
            if m.get("network", False)
            else PLANNER_BUDGETS
            if m.get("planner", False)
            else DEMO_BUDGETS
            if m.get("demo", False)
            else BUDGETS
        )
    ):
        raise ValueError("prelaunch mismatch")
    claim = json.loads((directory / "CLAIM.json").read_text())
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    if claim != dict(consumed=True, prelaunch_digest=seal, launches_allowed=1, retries=0):
        raise ValueError("consumed one-launch claim mismatch")
    w = runtime["welcome"]
    if runtime["encrypted"] is not True or (w["revision"], w["seed"], w["width"], w["height"]) != (
        "15.3",
        42,
        64,
        64,
    ):
        raise ValueError("encrypted pinned native runtime required")
    if not m.get("demo", False):
        vehicle.verify_receipt(PREVIOUS)
        source = freight.verify_receipt(SOURCE)
        if (
            m["source"]["save_sha256"] != source["before_save_sha256"]
            or m["source"]["receipt_sha256"] != sha256(SOURCE / "receipt.json")
            or m["predecessor"]["receipt_sha256"] != sha256(PREVIOUS / "receipt.json")
        ):
            raise ValueError("native source save lineage mismatch")
    elif (
        m["source"]["input_sha256"] != sha256(directory / "heightmap.png")
        or (directory / "heightmap.png").read_bytes() != flat_heightmap()
        or m["predecessor"]["executor_source_digest"] != sha256(directory / "frozen-source.zip")
    ):
        raise ValueError("native demonstration input/source mismatch")
    plan = DeliveryPlan.model_validate_json((directory / "plan.json").read_bytes())
    frames = json.loads((directory / "frames.json").read_text())
    sent = [bytes.fromhex(f) for d, f in frames if d == "outbound"]
    replies = []
    records = {}
    for d, f in frames:
        if d == "inbound":
            for kind, body in AdminFrameDecoder().feed_frames(bytes.fromhex(f)):
                if kind == SERVER_GAMESCRIPT:
                    replies.append(decode_gamescript(body))
    for path in directory.glob("*-request.json"):
        value = json.loads(path.read_bytes())
        raw = path.with_name(path.name.replace("-request", "-response")).read_bytes()
        if sent.count(encode_gamescript(path.read_bytes())) != 1 or replies.count(raw) != 1:
            raise ValueError("unique secure exchange missing")
        if m.get("planner", False) and value.get("type") is not None:
            continue
        if m.get("planner", False) and value.get("op") == "select":
            from app.simulation.openttd.freight_planning import PlanningSelectionRequest

            selected = PlanningSelectionRequest.model_validate_json(path.read_bytes())
            q = selected.admission_request
        else:
            q = DeliveryRequest.model_validate_json(path.read_bytes())
        records[q.request_id] = DeliveryReadback.parse_for(q, raw, legacy=legacy)
    expected_ids = (
        ["inspect-1"]
        + [name for i in range(10) for name in (f"build-{i}", f"read-{i}")]
        + [f"observe-{i}" for i in range(4)]
        + ["finish-1"]
    )
    wire_ids = []
    for frame in sent:
        if frame[2] == ADMIN_GAMESCRIPT:
            value = json.loads(decode_gamescript(frame[3:]))
            if m.get("planner", False) and value.get("type") is not None:
                continue
            wire_ids.append(value["request_id"])
    if (
        wire_ids != expected_ids
        or set(records) != set(expected_ids)
        or (not m.get("planner", False) and len(replies) != 26)
    ):
        raise ValueError("ordered single-attempt secure exchanges required")
    if (
        admit(
            records["inspect-1"],
            seal,
            sha256(directory / ("qualified.sav" if m.get("planner", False) else "before.sav"))
            if m.get("demo", False)
            else m["source"]["save_sha256"],
            m["predecessor"].get("receipt_sha256"),
            executor_source=m["predecessor"].get("executor_source_digest"),
            selection_digest=records["inspect-1"].plan if m.get("planner", False) else None,
        )
        != plan
    ):
        raise ValueError("native plan mismatch")
    for i in range(10):
        built = records[f"build-{i}"]
        read = records[f"read-{i}"]
        verify_snapshot(plan, read)
        if (
            built.status != "BUILT"
            or read.status != "READ"
            or built.s[22] != i + 1
            or read.s[22] != i + 1
            or (i < 9 and built.s[3] != read.s[3])
        ):
            raise ValueError("mutation/readback mismatch")
    receipt = verify_delivery(
        plan, records["read-8"], [records[f"observe-{i}"] for i in range(4)], records["finish-1"]
    )
    receipt.update(construction_evidence(plan, records, planner=m.get("planner", False)))
    if m.get("construction_readback_version") == 1:
        receipt.update(command_readback_evidence(directory / "stderr.log", plan, records))
    if m.get("planner", False):
        from app.simulation.openttd.freight_planning_replay import replay_planning_binding

        binding = replay_planning_binding(directory, m, runtime, plan)
        if binding != json.loads((directory / "planning-binding.json").read_bytes()):
            raise ValueError("plan-bound native receipt mismatch")
        request = json.loads((directory / "inspect-1-request.json").read_bytes())
        if request != binding["selection"]:
            raise ValueError("native selection request differs from P05 decision")
        receipt["planning_binding"] = binding
    receipt.update(
        before_save_sha256=sha256(directory / "before.sav"),
        after_save_sha256=sha256(directory / "after.sav"),
    )
    if receipt != json.loads((directory / "receipt.json").read_text()):
        raise ValueError("receipt mismatch")
    result = json.loads((directory / "result.json").read_text())
    cleanup = json.loads((directory / "cleanup.json").read_text())
    if (
        result["launches"],
        result["connections"],
        result["mutations"],
        result["requests"],
        result["status"],
    ) != (1, 1, 10, 26, "NATIVE_DELIVERY_VERIFIED"):
        raise ValueError("bounded runtime mismatch")
    if (
        not all(
            cleanup.get(k) is True
            for k in ["reaped", "sockets_closed", "workspace_disposed", "credential_removed"]
        )
        or cleanup.get("cleanup_error")
        or cleanup.get("remaining_processes")
    ):
        raise ValueError("cleanup failed")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["next", "prepare", "preflight", "run", "verify", "cleanup"]
    )
    parser.add_argument(
        "--demo", action="store_true", help="generate genuine native flat-world freight demo"
    )
    parser.add_argument("--authorize-one-launch", action="store_true")
    parser.add_argument(
        "--network", action="store_true", help="two P05-selected services in one session"
    )
    parser.add_argument(
        "--planner", action="store_true", help="qualify and plan in the same native world"
    )
    parser.add_argument(
        "--batch-limit", type=int, default=20, help="explicit planning batch cap, not native demand"
    )
    parser.add_argument("directory", type=Path, nargs="?")
    args = parser.parse_args()
    if args.command == "next":
        root = PROJECT / "artifacts/runtime"
        numbers = [
            attempt_number(p)
            for p in root.glob("openttd-15.3-first-freight-delivery-attempt*")
            if re.fullmatch(r"openttd-15\.3-first-freight-delivery-attempt[1-9][0-9]*", p.name)
        ]
        print(root / f"openttd-15.3-first-freight-delivery-attempt{max(numbers, default=0) + 1}")
        return
    if args.directory is None:
        parser.error("an explicit attempt directory is required")
    directory = args.directory.resolve()
    if args.command == "cleanup":
        print(json.dumps(recover_cleanup(directory), sort_keys=True))
    elif args.command == "prepare":
        p = prepare(
            directory,
            demo=args.demo,
            planner=args.planner,
            batch_limit=args.batch_limit,
            network=args.network,
        )
        preflight(p)
        print("PRELAUNCH PASS")
    elif args.command == "preflight":
        preflight(reopen(directory))
        print("PREFLIGHT PASS")
    elif args.command == "verify":
        metadata = json.loads((directory / "PRELAUNCH.json").read_text())
        if metadata.get("network", False):
            from app.simulation.openttd.freight_native_network import verify_network_receipt

            print(json.dumps(verify_network_receipt(directory), sort_keys=True))
        else:
            print(json.dumps(verify_receipt(directory), sort_keys=True))
    else:
        if not args.authorize_one_launch:
            parser.error("run requires --authorize-one-launch")
        result = asyncio.run(run(reopen(directory)))
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(
            0
            if result["status"]
            in ("NATIVE_DELIVERY_VERIFIED", "NATIVE_MULTI_SERVICE_DELIVERY_VERIFIED")
            else 1
        )


if __name__ == "__main__":
    main()
