"""Bounded native canonical collection through the existing secure exchange.

No launcher or reconnect lives here. The caller owns the one-process lifecycle.
The standard 15.3 GameScript clock cannot expose calendar/fractional dates; an
incomplete native clock remains a hard blocker rather than a fabricated value.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import StrictBool, StrictInt

from app.planning.domain import Contract
from app.simulation.openttd.freight_canonical import CanonicalObservation, compare_canonical

SECTIONS = ("header", "vehicles", "map", "industries", "stations")
MAX_RECORDS = 4096


@dataclass(frozen=True)
class CanonicalRequest:
    request_id: str
    section: str
    offset: int = 0
    type: str = "canonical-page"

    def to_bytes(self) -> bytes:
        if (
            self.section not in SECTIONS
            or type(self.offset) is not int
            or not 0 <= self.offset < MAX_RECORDS
            or not 1 <= len(self.request_id) <= 32
            or not self.request_id.isascii()
            or not self.request_id.replace("-", "").isalnum()
            or self.type != "canonical-page"
        ):
            raise ValueError("invalid canonical page request")
        return json.dumps(
            dict(
                protocol=1,
                type=self.type,
                request_id=self.request_id,
                section=self.section,
                offset=self.offset,
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()


class CanonicalPage(Contract):
    protocol: Literal[1]
    type: Literal["canonical-page-result"]
    request_id: str
    section: str
    offset: StrictInt
    status: Literal["ok"]
    total: StrictInt
    records: list[dict]
    tick: StrictInt
    economy_date: StrictInt
    paused: StrictBool
    restored: StrictBool

    @classmethod
    def parse_for(cls, request: CanonicalRequest, raw: bytes):
        if not 0 < len(raw) <= 1450:
            raise ValueError("canonical page exceeds native payload bound")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate canonical response key")
                result[key] = value
            return result

        json.loads(raw, object_pairs_hook=unique)
        page = cls.model_validate_json(raw)
        if any(
            getattr(page, key) != getattr(request, key)
            for key in ("request_id", "section", "offset")
        ):
            raise ValueError("canonical response correlation mismatch")
        if (
            not 0 <= page.total <= MAX_RECORDS
            or page.offset > page.total
            or not 0 <= len(page.records) <= 8
            or page.offset + len(page.records) > page.total
            or (page.offset < page.total and not page.records)
            or page.tick < 0
            or page.economy_date < 0
            or not page.paused
        ):
            raise ValueError("incomplete or unpaused canonical page")
        return page


def _unused_request(directory: Path, request: CanonicalRequest) -> None:
    for suffix in ("-request.json", "-response.json"):
        path = directory / (request.request_id + suffix)
        if path.exists() or path.is_symlink():
            raise FileExistsError("canonical exchange must not overwrite retained evidence")


def verify_save(save: Path, created: CanonicalObservation) -> None:
    if any(p.is_symlink() for p in (save, *save.parents)) or not save.is_file():
        raise ValueError("canonical save must be an existing protected regular file")
    if hashlib.sha256(save.read_bytes()).hexdigest() != created.source_save_sha256:
        raise ValueError("canonical save SHA-256 mismatch")


async def collect_raw_canonical(
    session,
    directory: Path,
    *,
    identity: str,
    runtime_sha256: str,
    bridge_sha256: str,
    configuration_sha256: str,
    source_save_sha256: str,
    require_restored=False,
    expected_vehicle_count: int = 3,
    snapshot_path: Path | None = None,
    exchange_fn=None,
) -> dict:
    if exchange_fn is None:
        from app.simulation.openttd.proof.freight_delivery import exchange

        exchange_fn = exchange
    prefix = "c" + hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:8]
    records = {}
    transcript = bytearray()
    boundary = None
    last_tick = -1
    for section in SECTIONS:
        rows = []
        total = None
        while total is None or len(rows) < total:
            request = CanonicalRequest(f"{prefix}-{section}-{len(rows)}", section, len(rows))
            _unused_request(directory, request)
            # Native exchange retains exact request and response, even on parse failure.
            page = await exchange_fn(session, request, directory, response_type=CanonicalPage)
            raw = (directory / (request.request_id + "-response.json")).read_bytes()
            transcript.extend(request.to_bytes() + b"\n" + raw + b"\n")
            current = (page.economy_date, page.paused, page.restored)
            if boundary is None:
                boundary = current
            if (
                current != boundary
                or page.tick < last_tick
                or (require_restored and not page.restored)
                or (total is not None and page.total != total)
            ):
                raise ValueError("canonical collection changed boundary or lost persistence")
            total = page.total
            rows.extend(page.records)
            last_tick = page.tick
        records[section] = rows
    # Independent endpoint header catches financial, fleet and clock drift over pages.
    request = CanonicalRequest(f"{prefix}-header-final", "header")
    _unused_request(directory, request)
    final = await exchange_fn(session, request, directory, response_type=CanonicalPage)
    transcript.extend(
        request.to_bytes()
        + b"\n"
        + (directory / (request.request_id + "-response.json")).read_bytes()
        + b"\n"
    )
    raw_path = directory / "canonical-readback.jsonl"
    with raw_path.open("xb") as stream:
        stream.write(transcript)
    if (
        final.records != records["header"]
        or final.total != 1
        or (final.economy_date, final.paused, final.restored) != boundary
    ):
        raise ValueError("canonical endpoint drift")
    if len(records["header"]) != 1:
        raise ValueError("canonical header missing")
    header = dict(records["header"][0])
    if snapshot_path is None:
        raise ValueError("BLOCKED: paused native snapshot clock required")
    from app.simulation.openttd.freight_canonical_save import read_save_clock

    clock = read_save_clock(snapshot_path)
    if clock["economy_date"] != header["economy_date"]:
        raise ValueError("canonical snapshot/native economy clock disagreement")
    header.update(
        calendar_date=clock["date"],
        calendar_date_fraction=clock["date_fract"],
        economy_date_fraction=clock["economy_date_fract"],
    )
    plans = header.pop("service_plans", None)
    if (
        not isinstance(plans, list)
        or len(plans) != 3
        or any(
            not isinstance(plan, str)
            or len(plan) != 64
            or any(c not in "0123456789abcdef" for c in plan)
            for plan in plans
        )
        or len(set(plans)) != 3
    ):
        raise ValueError("canonical native service-plan bindings incomplete")
    count = header.pop("vehicle_count")
    width = header.pop("width")
    height = header.pop("height")
    if (
        expected_vehicle_count not in (3, 4)
        or count != expected_vehicle_count
        or len(records["vehicles"]) != 3
    ):
        raise ValueError("canonical fleet missing or duplicated")
    tiles = records["map"]
    if (
        type(width) is not int
        or type(height) is not int
        or width * height > MAX_RECORDS
        or len(tiles) != width * height
        or [row.get("tile") for row in tiles] != list(range(width * height))
    ):
        raise ValueError("canonical map coverage incomplete")
    for section, key in (("industries", "industry"), ("stations", "station")):
        ids = [row.get(key) for row in records[section]]
        if not ids or len(ids) != len(set(ids)) or None in ids:
            raise ValueError(f"canonical {section} coverage invalid")
    _validate_fleet_geometry(records)
    header.update(
        map=dict(
            width=width,
            height=height,
            tiles=tiles,
            service_plans=plans,
            saved_clock={
                "tick_counter": clock["tick_counter"],
                "calendar_sub_date_fract": clock["calendar_sub_date_fract"],
            },
        ),
        vehicles=records["vehicles"],
        industries_production=records["industries"],
        stations_cargo=records["stations"],
        infrastructure=[row for row in tiles if row.get("owner") == 0],
    )
    return dict(
        qualification_id=identity,
        runtime_sha256=runtime_sha256,
        bridge_sha256=bridge_sha256,
        configuration_sha256=configuration_sha256,
        source_save_sha256=source_save_sha256,
        raw_readback_sha256=hashlib.sha256(transcript).hexdigest(),
        script_tick=final.tick,
        state=header,
    )


def _validate_fleet_geometry(records: dict) -> None:
    tiles = {row["tile"]: row for row in records["map"]}
    stations = records["stations"]
    destinations = {order["destination"] for v in records["vehicles"] for order in v["orders"]}
    if len(destinations) != 6 or len(stations) != 6:
        raise ValueError("canonical requires six complete original station records")
    if {row.get("tile") for row in stations} != destinations:
        raise ValueError("canonical station/order correspondence incomplete")
    for station in stations:
        tile = tiles.get(station["tile"], {})
        if (
            station.get("owner") != 0
            or tile.get("owner") != 0
            or tile.get("station") != station["station"]
            or not isinstance(station.get("cargo"), list)
            or not station["cargo"]
        ):
            raise ValueError("canonical station ownership or cargo incomplete")
    for vehicle in records["vehicles"]:
        depot = tiles.get(vehicle["tile"], {})
        if depot.get("owner") != 0 or depot.get("depot") is not True:
            raise ValueError("canonical vehicle depot ownership mismatch")
        reached = {vehicle["tile"]}
        pending = list(reached)
        while pending:
            current = pending.pop()
            row = tiles[current]
            if row.get("owner") != 0 or not isinstance(row.get("edges"), list):
                raise ValueError("canonical road ownership/adjacency incomplete")
            for edge in row["edges"]:
                if edge not in tiles or current not in tiles[edge].get("edges", []):
                    raise ValueError("canonical road connectivity asymmetric")
                if edge not in reached:
                    reached.add(edge)
                    pending.append(edge)
        if not {order["destination"] for order in vehicle["orders"]} <= reached:
            raise ValueError("canonical service route disconnected")


async def collect_canonical(session, directory: Path, **kwargs) -> CanonicalObservation:
    """Strict pre-intervention acquisition/reload: exactly three stopped originals."""
    if "expected_vehicle_count" in kwargs:
        raise ValueError("strict canonical collection fixes the original fleet count")
    value = await collect_raw_canonical(session, directory, **kwargs)
    return CanonicalObservation.model_validate_json(json.dumps(value))


async def verify_reloaded(
    session,
    directory: Path,
    *,
    created: CanonicalObservation,
    save: Path,
    identity: str,
    runtime_sha256: str,
    bridge_sha256: str,
    configuration_sha256: str,
    snapshot_path: Path | None = None,
    exchange_fn=None,
) -> CanonicalObservation:
    """Run after an independently owned fresh launch; verify_save also runs before it."""
    verify_save(save, created)
    loaded = await collect_canonical(
        session,
        directory,
        identity=identity,
        runtime_sha256=runtime_sha256,
        bridge_sha256=bridge_sha256,
        configuration_sha256=configuration_sha256,
        source_save_sha256=created.source_save_sha256,
        require_restored=True,
        snapshot_path=snapshot_path,
        exchange_fn=exchange_fn,
    )
    compare_canonical(created, loaded)
    return loaded


async def verify_intervention_snapshot(
    session,
    directory: Path,
    *,
    canonical,
    binding: dict | None,
    capex: int,
    started: bool,
    **collector_kwargs,
) -> bool:
    """Verify full native world after the only permitted purchase/start changes.

    The fourth vehicle's independent command/read receipt and paused position are
    verified by dispatch_common; this collector enumerates all original objects
    and checks the native total fleet count excludes any unreceipted extras.
    """
    if type(started) is not bool or type(capex) is not int or capex < 0:
        raise ValueError("invalid intervention snapshot parameters")
    if binding is None:
        if capex != 0:
            raise ValueError("baseline cannot contain purchase CAPEX")
    elif (
        set(binding) != {"service", "vehicle", "purchase_capex"}
        or binding["service"] != 1
        or type(binding["vehicle"]) is not int
        or binding["vehicle"] < 0
        or binding["vehicle"] in {v.vehicle for v in canonical.vehicles}
        or binding["purchase_capex"] != capex
        or capex <= 0
    ):
        raise ValueError("invalid additional vehicle binding")
    actual = await collect_raw_canonical(
        session,
        directory,
        expected_vehicle_count=4 if binding else 3,
        require_restored=True,
        **collector_kwargs,
    )
    expected = canonical.model_dump(mode="json")
    expected["cash"] -= capex
    for vehicle in expected["vehicles"]:
        vehicle["stopped"] = not started
    if actual["state"] != expected:
        raise ValueError("canonical intervention snapshot semantic drift")
    return True
