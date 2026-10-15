"""P06 preflight and runtime bindings for execution of the existing v1 plan.

Bindings resolve scenario catalog labels, never choose infrastructure or fleet.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.planning.canonical import _json_value
from app.planning.domain import (
    ConstructionKind,
    Contract,
    ExecutionPlan,
    Identifier,
    Mode,
    NonNegativeInt,
    PlanningScenario,
    RailComposition,
    RoadFleetOption,
    StopRole,
    Tile,
)
from app.planning.runtime_world import runtime_projection_from_manifest, runtime_world_hash
from app.planning.validation import validate_execution_plan


class EngineBinding(Contract):
    vehicle_type: Identifier
    engine_id: NonNegativeInt
    engine_name: str = Field(min_length=1, max_length=120)
    mode: Mode
    is_wagon: bool = False
    road_type: NonNegativeInt | None = None
    road_station_kind: Literal["truck", "bus"] | None = None


class CatalogBinding(Contract):
    identifier: Identifier
    runtime_id: NonNegativeInt
    runtime_name: str | None = None


class ExecutionBindings(Contract):
    schema_version: Literal[1] = 1
    engines: tuple[EngineBinding, ...]
    cargo_ids: tuple[CatalogBinding, ...]
    rail_types: tuple[CatalogBinding, ...]


class ExecutionPreparationError(ValueError):
    """A plan has no unambiguous, supported execution mapping; no mutation occurred."""


def execution_payload(
    plan: ExecutionPlan, scenario: PlanningScenario, bindings: ExecutionBindings
) -> dict:
    """Validate every selected decision before rendering the optional P06 module."""
    validate_execution_plan(plan, scenario)
    bindings = ExecutionBindings.model_validate_json(bindings.model_dump_json())
    engines = {b.vehicle_type: b for b in bindings.engines}
    cargo = {b.identifier: b.runtime_id for b in bindings.cargo_ids}
    rails = {b.identifier: b.runtime_id for b in bindings.rail_types}
    for items, index in (
        (bindings.engines, engines),
        (bindings.cargo_ids, cargo),
        (bindings.rail_types, rails),
    ):
        if len(items) != len(index):
            raise ExecutionPreparationError("duplicate runtime binding")
    if len({e.engine_id for e in bindings.engines}) != len(engines):
        raise ExecutionPreparationError("runtime engine aliases are unsupported")
    locations = {s.location_id: s for s in scenario.locations}
    candidates = {c.candidate_id: c for c in scenario.infrastructure_candidates}
    options = {o.option_id: o for o in scenario.fleet_options}
    demands = {d.demand_id: d for d in scenario.cargo_demands}
    routes = {r.route_id: r for r in plan.routes}
    used_engines = set()
    group_bindings = {}
    for group in plan.fleet.groups:
        if group.start_day != 0:
            raise ExecutionPreparationError(
                f"{group.fleet_group_id}: nonzero start_day unsupported"
            )
        if len(group.route_ids) != 1:
            raise ExecutionPreparationError(
                f"{group.fleet_group_id}: shared fleet orders ambiguous"
            )
        route = routes[group.route_ids[0]]
        if any(s.role is StopRole.SERVICE for s in route.stops):
            raise ExecutionPreparationError(f"{route.route_id}: SERVICE waypoints unsupported")
        if len(route.stops) != 3:
            raise ExecutionPreparationError(f"{route.route_id}: unsupported stop sequence")
        cargos = {demands[a.demand_id].cargo_type for a in route.cargo_assignments}
        if len(cargos) != 1 or not cargos <= cargo.keys():
            raise ExecutionPreparationError(f"{route.route_id}: one bound cargo required")
        option = options[group.option_id]
        if isinstance(option, RoadFleetOption):
            names = [(option.vehicle.vehicle_type, False)]
        else:
            assert isinstance(group.composition, RailComposition)
            names = [(group.composition.locomotive_type, False)] + [
                (w.wagon_type, True) for w in group.composition.wagons
            ]
        for name, wagon in names:
            if (
                name not in engines
                or engines[name].mode != group.mode
                or engines[name].is_wagon != wagon
            ):
                raise ExecutionPreparationError(
                    f"{group.fleet_group_id}: missing/incompatible engine {name}"
                )
            used_engines.add(name)
        cargo_name = next(iter(cargos))
        cargo_binding = next(b for b in bindings.cargo_ids if b.identifier == cargo_name)
        if cargo_binding.runtime_name is None:
            raise ExecutionPreparationError(f"{route.route_id}: cargo runtime label required")
        group_data = {
            "cargo_id": cargo[cargo_name],
            "cargo_label": cargo_binding.runtime_name,
            "route_id": route.route_id,
        }
        if isinstance(option, RoadFleetOption):
            binding = engines[option.vehicle.vehicle_type]
            if binding.road_type is None or binding.road_station_kind is None:
                raise ExecutionPreparationError(
                    f"{option.option_id}: road type/station kind required"
                )
            group_data.update(
                road_type=binding.road_type,
                station_kind=binding.road_station_kind,
                expected_capacity=option.vehicle.capacity_cargo_units,
            )
        else:
            if option.rail_type not in rails:
                raise ExecutionPreparationError(f"{option.option_id}: rail type binding required")
            assert isinstance(group.composition, RailComposition)
            rail_binding = next(b for b in bindings.rail_types if b.identifier == option.rail_type)
            if rail_binding.runtime_name is None:
                raise ExecutionPreparationError(f"{option.option_id}: rail runtime name required")
            group_data.update(
                rail_type=rails[option.rail_type],
                rail_name=rail_binding.runtime_name,
                expected_capacity=group.composition.total_capacity_cargo_units,
                max_length_16ths=group.composition.total_length_tiles * 16,
            )
        group_bindings[group.fleet_group_id] = group_data
    action_data: list[dict[str, Any]] = []
    seen = set()
    for action in plan.infrastructure.actions:
        if action.construction_id in seen or not set(action.depends_on) <= seen:
            raise ExecutionPreparationError(
                f"{action.construction_id}: duplicate or unordered dependency"
            )
        seen.add(action.construction_id)
        candidate = candidates[action.candidate_id]
        users = [group_bindings[routes[r].fleet_group_id] for r in action.route_ids]
        type_key = "road_type" if action.mode is Mode.ROAD else "rail_type"
        if len({u[type_key] for u in users}) != 1:
            raise ExecutionPreparationError(
                f"{action.construction_id}: incompatible shared infrastructure types"
            )
        row: dict[str, Any] = {
            "action": _json_value(action),
            "candidate": _json_value(candidate),
            "network_type": users[0][type_key],
        }
        if candidate.kind is ConstructionKind.SEGMENT:
            if any(
                abs(a.x - b.x) + abs(a.y - b.y) != 1
                for a, b in zip(candidate.tiles, candidate.tiles[1:])
            ):
                raise ExecutionPreparationError(
                    f"{candidate.candidate_id}: diagonal geometry unsupported"
                )
            if len(set(candidate.tiles)) != len(candidate.tiles):
                raise ExecutionPreparationError(f"{candidate.candidate_id}: repeated segment tile")
            if action.mode is Mode.RAIL:
                # Baseline explicit rail corridors are straight; no inferred endpoint turns/signals.
                if not (
                    len({t.x for t in candidate.tiles}) == 1
                    or len({t.y for t in candidate.tiles}) == 1
                ):
                    raise ExecutionPreparationError(
                        f"{candidate.candidate_id}: curved rail geometry unsupported"
                    )
                row["axis"] = "x" if candidate.tiles[0].y == candidate.tiles[-1].y else "y"
        else:
            assert candidate.site_id is not None
            site = locations[candidate.site_id]
            orientation = candidate.orientation or site.orientation
            if orientation is None or (
                candidate.orientation
                and site.orientation
                and candidate.orientation != site.orientation
            ):
                raise ExecutionPreparationError(
                    f"{candidate.candidate_id}: explicit consistent orientation required"
                )
            width = candidate.footprint_width_tiles or 1
            height = candidate.footprint_height_tiles or 1
            if (site.footprint_width_tiles is not None and site.footprint_width_tiles != width) or (
                site.footprint_height_tiles is not None and site.footprint_height_tiles != height
            ):
                raise ExecutionPreparationError(
                    f"{candidate.candidate_id}: footprint differs from site"
                )
            dx, dy = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}[
                orientation
            ]
            front_x, front_y = site.tile.x + dx, site.tile.y + dy
            if not (0 <= front_x < scenario.width_tiles and 0 <= front_y < scenario.height_tiles):
                raise ExecutionPreparationError(f"{candidate.candidate_id}: front tile outside map")
            row.update(
                site=_json_value(site),
                orientation=orientation,
                width=width,
                height=height,
                front={"x": front_x, "y": front_y},
            )
            if action.mode is Mode.RAIL and candidate.kind is ConstructionKind.STATION:
                axis = "x" if orientation in ("east", "west") else "y"
                length = width if axis == "x" else height
                if length != site.platform_length_tiles or max(width, height) > 255:
                    raise ExecutionPreparationError(
                        f"{candidate.candidate_id}: rail platform footprint required"
                    )
                row.update(
                    axis=axis,
                    platform_length=length,
                    num_platforms=height if axis == "x" else width,
                )
            elif width != 1 or height != 1:
                raise ExecutionPreparationError(
                    f"{candidate.candidate_id}: facility requires 1x1 footprint"
                )
            if action.mode is Mode.ROAD and candidate.kind is ConstructionKind.STATION:
                kinds = {u["station_kind"] for u in users}
                if len(kinds) != 1:
                    raise ExecutionPreparationError(
                        f"{candidate.candidate_id}: mixed road station kinds"
                    )
                row["station_kind"] = users[0]["station_kind"]
        action_data.append(row)
    facilities = {
        r["candidate"]["site_id"]: r for r in action_data if r["candidate"]["kind"] != "segment"
    }
    for row in action_data:
        c = row["candidate"]
        if c["kind"] == "segment" and c["mode"] == "rail":
            for endpoint in (c["origin_id"], c["destination_id"]):
                if facilities[endpoint]["axis"] != row["axis"]:
                    raise ExecutionPreparationError(
                        f"{c['candidate_id']}: station/corridor axes differ"
                    )
        if c["kind"] != "segment":
            tile = row["site"]["tile"]
            for y in range(row["height"]):
                for x in range(row["width"]):
                    t = Tile(x=tile["x"] + x, y=tile["y"] + y)
                    if (
                        t.x >= scenario.width_tiles
                        or t.y >= scenario.height_tiles
                        or t not in scenario.world_manifest.buildable_tiles
                    ):
                        raise ExecutionPreparationError(
                            f"{c['candidate_id']}: unsupported footprint tile {t.x},{t.y}"
                        )
        if c["kind"] == "depot":
            for route_id in row["action"]["route_ids"]:
                route = routes[route_id]
                segments = [
                    r
                    for r in action_data
                    if r["candidate"]["kind"] == "segment"
                    and r["action"]["construction_id"] in route.infrastructure_ids
                ]
                if not any(row["front"] in r["candidate"]["tiles"] for r in segments):
                    raise ExecutionPreparationError(
                        f"{c['candidate_id']}: depot front must touch a supplied corridor"
                    )
                if c["mode"] == "rail" and any(
                    r["axis"] != ("x" if row["orientation"] in ("east", "west") else "y")
                    for r in segments
                ):
                    raise ExecutionPreparationError(
                        f"{c['candidate_id']}: depot/corridor axes differ"
                    )
                if c["mode"] == "road" and any(
                    row["front"] == r["site"]["tile"]
                    for r in facilities.values()
                    if r["candidate"]["kind"] == "station"
                ):
                    raise ExecutionPreparationError(
                        f"{c['candidate_id']}: road depot front cannot enter "
                        "a terminal station sideways"
                    )
    # Conservative bound for the independent parser's 64 KiB terminal record and
    # 1 MiB evidence stream. Reject before staging, never after world mutation.
    evidence_capacity = 4096 + sum(
        1024
        + 24
        * (
            len(r["candidate"]["tiles"])
            if r["candidate"]["kind"] == "segment"
            else r["width"] * r["height"]
        )
        for r in action_data
    )
    for group in plan.fleet.groups:
        components = 1
        if isinstance(group.composition, RailComposition):
            components += sum(w.count for w in group.composition.wagons)
        evidence_capacity += 1024 + group.count * (2048 + 1024 * components)
    if evidence_capacity > 65536:
        raise ExecutionPreparationError("plan exceeds bounded P06 evidence capacity")
    # Existing P03 observation requires at least one independently resolved world object.
    try:
        runtime_hash = runtime_world_hash(runtime_projection_from_manifest(scenario.world_manifest))
    except ValueError as error:
        raise ExecutionPreparationError("P03 runtime world identity required") from error
    return {
        "version": 1,
        "executor_version": "1",
        "runtime_world_hash": runtime_hash,
        "actions": action_data,
        "groups": group_bindings,
        "engines": {name: _json_value(engines[name]) for name in sorted(used_engines)},
        "locations": {name: _json_value(locations[name]) for name in sorted(locations)},
    }
