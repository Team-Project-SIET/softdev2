"""Versioned deterministic demand and facility policies over extracted facts."""

from typing import Literal

from app.planning.domain import Contract, NonNegativeInt, PositiveInt
from app.planning.preparation.domain import (
    ExtractedIndustry,
    ExtractedTile,
    ExtractedWorldSnapshot,
    PreparationRequest,
    StationSamplingReport,
)
from app.planning.preparation.failures import PreparationFailureCode as Code
from app.planning.preparation.failures import fail

DIRECTIONS = (("north", 0, -1), ("east", 1, 0), ("south", 0, 1), ("west", -1, 0))


class PreparedDemand(Contract):
    origin_id: NonNegativeInt
    destination_id: NonNegativeInt
    cargo_id: NonNegativeInt
    quantity: PositiveInt
    earliest_day: Literal[0] = 0
    latest_delivery_day: NonNegativeInt


class FacilitySite(Contract):
    tile_index: NonNegativeInt
    front_tile: NonNegativeInt
    orientation: Literal["north", "east", "south", "west"]


def eligible(tile: ExtractedTile) -> bool:
    return (
        tile.slope == 0
        and tile.land_class == "land"
        and tile.occupancy == "vacant"
        and tile.build_eligible
        and not tile.transport_occupied
        and not tile.clearing_required
        and tile.industry_id is None
    )


def bound(value: int, limit: int, world: ExtractedWorldSnapshot, stage: str, name: str) -> None:
    if value > limit:
        fail(
            Code.CANDIDATE_LIMIT_EXCEEDED,
            stage,
            world.prepared_save_digest,
            f"{name} exceeds policy bound",
        )


def select_demand(
    world: ExtractedWorldSnapshot, request: PreparationRequest
) -> tuple[PreparedDemand, int]:
    relationships = []
    cargo_ids = {c.cargo_id for c in world.cargos if c.freight}
    for origin in sorted(world.industries, key=lambda i: i.industry_id):
        for cargo in sorted(origin.cargos, key=lambda c: c.cargo_id):
            if cargo.last_month_production <= 0 or cargo.cargo_id not in cargo_ids:
                continue
            for destination in sorted(world.industries, key=lambda i: i.industry_id):
                if destination.industry_id != origin.industry_id and any(
                    c.cargo_id == cargo.cargo_id and c.accepts for c in destination.cargos
                ):
                    relationships.append(
                        (
                            origin.industry_id,
                            cargo.cargo_id,
                            destination.industry_id,
                            cargo.last_month_production,
                        )
                    )
                    bound(
                        len(relationships),
                        request.limits.relationships,
                        world,
                        "demand",
                        "OD/cargo relationships",
                    )
    if not relationships:
        fail(
            Code.NO_COMPATIBLE_DESTINATION,
            "demand",
            world.prepared_save_digest,
            "no positive freight production with accepting destination",
        )
    origin, cargo, destination, quantity = relationships[0]
    return PreparedDemand(
        origin_id=origin,
        destination_id=destination,
        cargo_id=cargo,
        quantity=quantity,
        latest_delivery_day=request.horizon_days - 1,
    ), len(relationships)


def adjacent(world: ExtractedWorldSnapshot, index: int):
    x, y = index % world.width_tiles, index // world.width_tiles
    for direction, dx, dy in DIRECTIONS:
        nx, ny = x + dx, y + dy
        if 0 <= nx < world.width_tiles and 0 <= ny < world.height_tiles:
            yield direction, ny * world.width_tiles + nx


def station_candidates(
    world: ExtractedWorldSnapshot,
    request: PreparationRequest,
    industry: ExtractedIndustry,
    cargo_id: int,
    role: Literal["pickup", "delivery"],
) -> tuple[tuple[FacilitySite, ...], StationSamplingReport]:
    tiles = {t.tile_index: t for t in world.tiles}
    radius = world.profile.catchment_radius
    # Bounded union of footprint-local squares. Never scan all map tiles for stations.
    neighborhood = set()
    for index in industry.footprint:
        x, y = index % world.width_tiles, index // world.width_tiles
        for ny in range(max(0, y - radius), min(world.height_tiles, y + radius + 1)):
            for nx in range(max(0, x - radius), min(world.width_tiles, x + radius + 1)):
                neighborhood.add(ny * world.width_tiles + nx)
    ax, ay = industry.anchor_tile % world.width_tiles, industry.anchor_tile // world.width_tiles
    sectors: dict[str, list[tuple[tuple[int, int], FacilitySite]]] = {d[0]: [] for d in DIRECTIONS}
    relation = next((c for c in industry.cargos if c.cargo_id == cargo_id), None)
    count = 0
    for index in sorted(neighborhood):
        tile = tiles[index]
        if not eligible(tile) or relation is None:
            continue
        fact = next((c for c in tile.cargo_facts if c.cargo_id == cargo_id), None)
        if (
            fact is None
            or (role == "pickup" and (relation.last_month_production <= 0 or fact.production <= 0))
            or (
                role == "delivery"
                and (
                    not relation.accepts
                    or fact.acceptance_eighths < world.profile.acceptance_threshold
                )
            )
        ):
            continue
        dx, dy = tile.x - ax, tile.y - ay
        sector = (
            ("east" if dx > 0 else "west")
            if abs(dx) > abs(dy)
            else ("south" if dy > 0 else "north")
        )
        fronts = [
            (d, f)
            for d, f in adjacent(world, index)
            if eligible(tiles[f]) and tiles[f].height == tile.height
        ]
        if not fronts:
            continue
        # Prefer pointing away from the served industry, then fixed N/E/S/W order.
        fronts.sort(key=lambda item: (item[0] != sector, [d[0] for d in DIRECTIONS].index(item[0])))
        orientation, front = fronts[0]
        site = FacilitySite(tile_index=index, front_tile=front, orientation=orientation)
        sectors[sector].append(((abs(dx) + abs(dy), index), site))
        count += 1
    selected = []
    # Round robin compass sectors, nearest Manhattan distance then native tile index.
    for values in sectors.values():
        values.sort(key=lambda value: value[0])
    rank = 0
    while len(selected) < request.limits.stations_per_role:
        added = False
        for direction, _, _ in DIRECTIONS:
            values = sectors[direction]
            if rank < len(values):
                selected.append(values[rank][1])
                added = True
                if len(selected) == request.limits.stations_per_role:
                    break
        if not added:
            break
        rank += 1
    if not selected:
        fail(
            Code.NO_STATION_CANDIDATE,
            "stations",
            world.prepared_save_digest,
            "no eligible covered terminal truck stop",
            str(industry.industry_id),
        )
    return tuple(selected), StationSamplingReport(
        industry_id=industry.industry_id,
        role=role,
        eligible_count=count,
        selected_tiles=tuple(s.tile_index for s in selected),
    )


def depot_candidate(
    world: ExtractedWorldSnapshot,
    reserved: frozenset[int],
    facilities: tuple[FacilitySite, ...] = (),
) -> FacilitySite:
    tiles = {t.tile_index: t for t in world.tiles}
    ranked = sorted(
        tiles.items(),
        key=lambda row: (
            sum(
                abs(row[1].x - tiles[s.front_tile].x) + abs(row[1].y - tiles[s.front_tile].y)
                for s in facilities
            ),
            row[0],
        ),
    )
    for index, tile in ranked:
        if index in reserved or index in {s.front_tile for s in facilities} or not eligible(tile):
            continue
        for direction, front in adjacent(world, index):
            if (
                front not in reserved
                and eligible(tiles[front])
                and tiles[front].height == tile.height
            ):
                # Removing the depot footprint must leave all advertised station fronts connected.
                reachable, pending = set(), [front]
                while pending:
                    current = pending.pop()
                    if current in reachable:
                        continue
                    reachable.add(current)
                    pending.extend(
                        n
                        for _, n in adjacent(world, current)
                        if n not in reachable
                        and n != index
                        and n not in reserved
                        and eligible(tiles[n])
                        and tiles[n].height == tiles[current].height
                    )
                if facilities and any(s.front_tile not in reachable for s in facilities):
                    continue
                return FacilitySite(tile_index=index, front_tile=front, orientation=direction)
    fail(
        Code.NO_DEPOT_CANDIDATE,
        "depot",
        world.prepared_save_digest,
        "no eligible shared depot with a nonstation front",
    )
    raise AssertionError("unreachable")
