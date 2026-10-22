"""Evidence-bound clearing candidates for retained P08 proposals (PLANNING_ONLY).

This module binds the cleared tiles of a retained bounded TerrainProposal (and
of a P08 corridor clear requirement) to the V2 census-derived classification
evidence. It produces offline clearing-plan candidates for the separately
reviewed bounded clearing contract; it issues no native command and marks
nothing as executed.
"""

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt

from app.planning.domain import Contract
from app.simulation.openttd.terrain_clearing import ALLOWED_CLEARING_CLASSES

TileID = Annotated[StrictInt, Field(ge=0, le=65535)]
Elevation = Annotated[StrictInt, Field(ge=0, le=255)]
Slope = Annotated[StrictInt, Field(ge=0, le=31)]


class ClearingPlanCandidate(Contract):
    """One tile planned for one bounded clearing operation, evidence-bound.

    ``expected_classification``/``expected_owner``/``expected_elevation``/
    ``expected_slope`` come from the retained census (or a later native
    inspect readback); the clearing ceremony re-derives all of them natively
    before any command, so stale or silent evidence cannot authorize work.
    """

    schema_version: Literal[1] = 1
    tile: TileID
    x: Annotated[StrictInt, Field(ge=0, le=65535)]
    y: Annotated[StrictInt, Field(ge=0, le=65535)]
    expected_classification: Literal["TREES", "FARM", "ROUGH", "ROCK"]
    expected_owner: Literal[-1]
    expected_elevation: Elevation
    expected_slope: Slope
    source: Literal["proposal_cleared_tiles", "assessment_clear_requirement"]
    provenance: Annotated[str, Field(min_length=1)]
    execution_status: Literal["PLANNING_ONLY"] = "PLANNING_ONLY"


def _evidence_class(fact: Any, tile: int) -> str:
    classification = getattr(fact, "classification", None) or getattr(fact, "tile_class", None)
    value = getattr(classification, "value", classification)
    if value not in ALLOWED_CLEARING_CLASSES:
        raise ValueError(f"tile {tile} census class {value!r} is not a bounded clearing class")
    return value


def clearing_candidates(
    tiles: tuple[int, ...] | list[int],
    *,
    facts: Mapping[int, Any],
    source: Literal["proposal_cleared_tiles", "assessment_clear_requirement"],
    provenance: str,
    map_dims: tuple[int, int],
) -> list[ClearingPlanCandidate]:
    """Bind ordered clearing tiles to census-derived classification evidence.

    Requires every tile to be census-classified as an allowed clearing class
    (TREES, FARM, ROUGH, ROCK) and unowned; duplicates and unknown tiles fail
    closed. ``map_dims`` pins the x/y geometry (Seed 17 census is 256x256).
    """
    if (
        type(map_dims) is not tuple
        or len(map_dims) != 2
        or (not all(type(d) is int and 64 <= d <= 4096 and d & (d - 1) == 0 for d in map_dims))
    ):
        raise ValueError("map_dims must be bounded power-of-two dimensions")
    if not tiles:
        raise ValueError("a clear requirement must name at least one tile")
    width = map_dims[0]
    if any(type(tile) is int and tile >= width * map_dims[1] for tile in tiles):
        raise ValueError("clearing tile lies outside the declared map dimensions")
    candidates: list[ClearingPlanCandidate] = []
    seen: set[int] = set()
    for tile in tiles:
        if type(tile) is not int or not 0 <= tile <= 65535:
            raise ValueError(f"clearing tile {tile!r} is outside the bounded tile range")
        if tile in seen:
            raise ValueError(f"tile {tile} repeated in one clear requirement; never cleared twice")
        seen.add(tile)
        if tile not in facts:
            raise ValueError(f"tile {tile} has no census classification to validate against")
        fact = facts[tile]
        classification = _evidence_class(fact, tile)
        owner = getattr(fact, "owner", None)
        if type(owner) is not int or owner != -1:
            raise ValueError(f"tile {tile} is not unowned in the census evidence")
        industry_id = getattr(fact, "industry_id", None)
        if industry_id is not None:
            raise ValueError(f"tile {tile} carries an industry pointer in the census evidence")
        elevation = getattr(fact, "elevation", getattr(fact, "min_height", None))
        slope = getattr(fact, "slope", None)
        if type(elevation) is not int or not 0 <= elevation <= 255:
            raise ValueError(f"tile {tile} census elevation is out of bounds")
        if type(slope) is not int or not 0 <= slope <= 31:
            raise ValueError(f"tile {tile} census slope is out of bounds")
        candidates.append(
            ClearingPlanCandidate(
                tile=tile,
                x=tile % width,
                y=tile // width,
                expected_classification=classification,
                expected_owner=-1,
                expected_elevation=elevation,
                expected_slope=slope,
                source=source,
                provenance=provenance,
            )
        )
    return candidates


def candidates_for_proposal(
    proposal: Any,
    *,
    facts: Mapping[int, Any],
    provenance: str,
    map_dims: tuple[int, int] = (256, 256),
) -> list[ClearingPlanCandidate]:
    """Candidates for one retained TerrainProposal's ``cleared_tiles``."""
    cleared = getattr(proposal, "cleared_tiles", None)
    if not isinstance(cleared, tuple):
        raise ValueError("proposal cleared_tiles must be an immutable tile tuple")
    return clearing_candidates(
        cleared,
        facts=facts,
        source="proposal_cleared_tiles",
        provenance=provenance,
        map_dims=map_dims,
    )


def candidates_for_clear_requirement(
    tiles: tuple[int, ...] | list[int],
    *,
    facts: Mapping[int, Any],
    provenance: str,
    map_dims: tuple[int, int] = (256, 256),
) -> list[ClearingPlanCandidate]:
    """Candidates for a P08 corridor assessment clear requirement."""
    return clearing_candidates(
        tiles,
        facts=facts,
        source="assessment_clear_requirement",
        provenance=provenance,
        map_dims=map_dims,
    )
