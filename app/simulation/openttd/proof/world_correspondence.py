"""Fail-closed world correspondence policy for Tile Classification V2 fusion.

The prepared census binds to the retained Seed 17 TileFacts projection. Same
seeds and matching industry coordinates are not the same world, so fusion is
only permitted through an explicit correspondence mode whose acceptance rules
are code-enforced here and in :meth:`TileClassificationSweep.record
<app.simulation.openttd.tile_classification.TileClassificationSweep>`. Three
modes exist and none may be implied:

- ``SOURCE_SAVE_FUSION`` (preferred): the capture process loads a byte-verified
  retained source save, so the world state is reproduced from a frozen artifact
  rather than from an equivalent recipe. The loaded world's welcome identity is
  validated before the census and every classified tile must still agree with
  the retained TileFacts (the sweep coherence gate).
- ``FRESH_GENERATION_FACT_COHERENCE``: a fresh native generation of the pinned
  recipe; the sweep contract (identical welcome keys plus coherence of every
  shared per-tile fact against the retained TileFacts) is the correspondence
  gate and any contradiction stays recorded, never repaired.
- ``SAME_SESSION_CENSUS`` (fallback): the capture session first re-observes the
  v1 ``tile_facts_page`` bank for the census region and then the schema-2 bank;
  fresh facts and retained facts must agree tile by tile before the schema-2
  census may fuse with the retained record. The extra requests are accounted
  explicitly here; the original classification-page allowance is never silently
  exceeded (each bank keeps its own page and byte ceilings, and the combined
  session budget is sealed into a fresh candidate before any launch).

Offline only: this module never launches OpenTTD, never connects to AdminPort
and never consumes an authorization claim.
"""

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..supplemental_planning_facts import Region, SupplementalPlanningFacts
from ..tile_classification import (
    CLASSIFICATION_PAGE_LIMIT,
    CLASSIFICATION_TOTAL_RESPONSE_BYTES_LIMIT,
    classification_bands,
)
from ..tile_facts import MAX_RESPONSE_BYTES, PAGE_SIZE, TileFact, TileFactsRequest
from .harness import (
    BINARY_SHA256,
    sha256,
    write_json,
)
from .terrain_classification_preparation import (
    OBSERVATION_SECONDS,
    SEED17_RUN,
)
from .terrain_classification_preparation import (
    retained_facts as retained_census_facts,
)

SAVE_CORRESPONDENCE_SCHEMA = "owned-freight-save-correspondence-v1"
SOURCE_SAVE_MODE = "SOURCE_SAVE_FUSION"
FRESH_GENERATION_MODE = "FRESH_GENERATION_FACT_COHERENCE"
SAME_SESSION_MODE = "SAME_SESSION_CENSUS"
CORRESPONDENCE_MODES = (SOURCE_SAVE_MODE, FRESH_GENERATION_MODE, SAME_SESSION_MODE)

# The GameScript info name stored inside the retained save: the staged
# source-save composition must announce exactly this name (verified against the
# retained frozen-source archive below, never asserted from memory).
SOURCE_SAVE_GS_NAME = "RoadFreightProof"


def _retained_staged_game_script_name() -> str:
    """The staged GameScript GetName() value of the retained run.

    The retained run's frozen-source archive contains the exact staged
    ``info.nut``; extracting the registered name there binds the save's stored
    GameScript identity to evidence instead of assumption.
    """
    with zipfile.ZipFile(SEED17_RUN / "frozen-source.zip") as archive:
        text = archive.read("staged/info.nut").decode()
    line = next((line for line in text.splitlines() if "function GetName()" in line), "")
    if '"' not in line:
        raise ValueError("retained staged composition lost its GameScript name")
    return line.split('"')[1]


def retained_save_binding() -> dict:
    """Byte-verify the retained source-save provenance records; fail closed.

    ``before.sav`` is the retained world state captured in the same observation
    session as ``network-facts-0.json`` (zero tile mutations between the two).
    Its binding must agree with the retained prelaunch seal, binary digest and
    the staged GameScript identity before any capture may rely on it.
    """
    record = SEED17_RUN / "native-save-correspondence.json"
    if not record.is_file():
        raise ValueError(f"retained save correspondence missing: {record}")
    binding = json.loads(record.read_bytes())
    save = SEED17_RUN / "before.sav"
    prelaunch = SEED17_RUN / "PRELAUNCH.json"
    if binding.get("schema") != SAVE_CORRESPONDENCE_SCHEMA:
        raise ValueError("unexpected retained save correspondence schema")
    if not save.is_file() or sha256(save) != binding.get("before_save_digest"):
        raise ValueError("retained source-save digest mismatch")
    if sha256(prelaunch) != binding.get("prelaunch_digest"):
        raise ValueError("retained save correspondence prelaunch seal mismatch")
    if binding.get("runtime_digest") != BINARY_SHA256:
        raise ValueError("retained save correspondence runtime digest mismatch")
    game_script_name = _retained_staged_game_script_name()
    if game_script_name != SOURCE_SAVE_GS_NAME:
        raise ValueError("retained staged GameScript identity drifted")
    return {
        "schema": SAVE_CORRESPONDENCE_SCHEMA,
        "role": "SOURCE_SAVE",
        "retained_directory": str(SEED17_RUN),
        "save": "before.sav",
        "save_sha256": binding["before_save_digest"],
        "qualified_save_sha256": binding.get("qualified_save_digest"),
        "prelaunch_digest": binding["prelaunch_digest"],
        "binary_sha256": BINARY_SHA256,
        "world_observation_digest": binding.get("world_observation_digest"),
        "game_script_name": game_script_name,
    }


def verify_staged_source_save(binding: dict, workspace_save: Path) -> None:
    """The staged workspace save must be a byte-identical copy of the pinned source."""
    if not workspace_save.is_file() or sha256(workspace_save) != binding["save_sha256"]:
        raise ValueError("staged source save is not the pinned retained world state")


@dataclass(frozen=True)
class SameSessionAccounting:
    """Explicit combined budget lines for the fallback census mode."""

    facts_pages: int
    classification_pages: int
    facts_response_bytes_limit: int
    classification_response_bytes_limit: int
    observation_seconds: int

    @property
    def session_requests(self) -> int:
        return self.facts_pages + self.classification_pages

    def as_dict(self) -> dict:
        return dict(
            mode=SAME_SESSION_MODE,
            facts_pages=self.facts_pages,
            classification_pages=self.classification_pages,
            session_requests=self.session_requests,
            facts_response_bytes_limit=self.facts_response_bytes_limit,
            classification_response_bytes_limit=self.classification_response_bytes_limit,
            observation_seconds=self.observation_seconds,
            statement=(
                "each bank keeps its own page and byte ceiling; the combined"
                " session-request budget is sealed into a fresh candidate, never"
                " silently grown beyond the original classification allowance"
            ),
        )


def _census_pages(region: Region, tile_count: int) -> int:
    total = region.width * region.height
    if total != tile_count or total > 512:
        raise ValueError("census region does not match its facts")
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if pages > CLASSIFICATION_PAGE_LIMIT:
        raise ValueError("census bank exceeds the shared page ceiling")
    return pages


def same_session_accounting() -> SameSessionAccounting:
    """Deterministic combined budget for the fallback mode over the census region."""
    facts = retained_census_facts()
    pages = _census_pages(facts.region, len(facts.tiles))
    return SameSessionAccounting(
        facts_pages=pages,
        classification_pages=pages,
        facts_response_bytes_limit=CLASSIFICATION_PAGE_LIMIT * MAX_RESPONSE_BYTES,
        classification_response_bytes_limit=CLASSIFICATION_TOTAL_RESPONSE_BYTES_LIMIT,
        observation_seconds=OBSERVATION_SECONDS,
    )


def same_session_facts_plan(request_id: str) -> tuple[TileFactsRequest, ...]:
    """Deterministic v1 TileFacts page plan of the fallback census bank.

    The v1 wire addresses at most 256 tiles per request, so the bank uses the
    exact same guillotine banding as the schema-2 census plan.
    """
    facts = retained_census_facts()
    page_count = _census_pages(facts.region, len(facts.tiles))
    requests: list[TileFactsRequest] = []
    from ..supplemental_planning_facts import Region as _Region

    for x, y, width, height in classification_bands(facts.region):
        band = _Region(x=x, y=y, width=width, height=height)
        pages = (width * height + PAGE_SIZE - 1) // PAGE_SIZE
        for ordinal in range(pages):
            requests.append(TileFactsRequest(request_id, band, ordinal * PAGE_SIZE))
    if len(requests) != page_count:
        raise ValueError("banding produced an unexpected facts page count")
    return tuple(requests)


def same_session_schedule() -> dict:
    """Offline schedule record for the fallback mode (a plan, not a launch)."""
    return same_session_accounting().as_dict()


def persist_same_session_schedule(directory: Path) -> dict:
    schedule = same_session_schedule()
    write_json(directory / "same-session-accounting.json", schedule)
    return schedule


def fresh_fact_contradictions(
    retained: SupplementalPlanningFacts, fresh: tuple[TileFact, ...]
) -> tuple[tuple[int, str], ...]:
    """Tile-by-tile equality between a fresh v1 facts bank and the retained one.

    Every shared observation must match exactly; anything else means the two
    banks were not captured in the same qualified world state, so fusion is
    refused (recorded per tile, never repaired or downgraded).
    """
    projected = {tile.tile_id: tile for tile in fresh}
    contradictions: list[tuple[int, str]] = []
    for fact in retained.tiles:
        observed = projected.get(fact.tile_id)
        if observed is None:
            contradictions.append((fact.tile_id, "FRESH_FACT_MISSING"))
            continue
        for name in (
            "min_height",
            "slope",
            "industry_id",
            "water",
            "coast",
            "tree",
            "farm",
            "rock",
            "rough",
            "road",
            "rail",
            "water_transport",
            "air_transport",
        ):
            if getattr(observed, name) != getattr(fact, name):
                contradictions.append((fact.tile_id, f"FRESH_FACT_DIFFERS:{name}"))
        if observed.buildable != fact.buildable:
            contradictions.append((fact.tile_id, "FRESH_FACT_DIFFERS:buildable"))
    if len(projected) != len(retained.tiles):
        contradictions.append((-1, "FRESH_FACT_SURPLUS"))
    return tuple(contradictions)


def evaluate_correspondence(
    mode: str,
    *,
    bound: bool,
    coherence_failures: tuple[tuple[int, str], ...] = (),
    accountings: dict | None = None,
    save_binding: dict | None = None,
    fresh_contradictions: tuple[tuple[int, str], ...] = (),
) -> dict:
    """Machine-readable fusion verdict; fail closed on every unmet requirement."""
    if mode not in CORRESPONDENCE_MODES:
        raise ValueError("unknown correspondence mode")
    keys = {
        reason.split(":", 1)[1] if ":" in reason else "world"
        for _, reason in coherence_failures
        if reason.startswith("WORLD_IDENTITY_MISMATCH")
    }
    identity_failures = [f"WORLD_IDENTITY_MISMATCH:{k}" for k in sorted(keys)]
    disagreements = [
        [tile, reason]
        for tile, reason in coherence_failures
        if not reason.startswith("WORLD_IDENTITY_MISMATCH")
    ]
    verdict = dict(
        mode=mode,
        identity_failures=identity_failures,
        tile_disagreements=disagreements,
        save_binding_sha256=(
            hashlib.sha256(json.dumps(save_binding, sort_keys=True).encode()).hexdigest()
            if save_binding is not None
            else None
        ),
        fresh_fact_contradictions=[[tile, reason] for tile, reason in fresh_contradictions],
        accounting=accountings,
    )
    if not bound:
        if identity_failures:
            verdict["status"] = "REJECTED"
            verdict["statement"] = (
                "the observed world identity contradicts the retained world;"
                " the census is retained as partial evidence only and nothing was fused"
            )
        elif disagreements or fresh_contradictions:
            verdict["status"] = "REJECTED"
            verdict["statement"] = (
                "classified or freshly re-observed tiles contradict the retained"
                " TileFacts; nothing was fused and every contradiction is recorded"
            )
        else:
            verdict["status"] = "PARTIAL_CORRESPONDENCE"
            verdict["statement"] = (
                "the census did not bind to the retained TileFacts projection;"
                " the retained unknown tiles remain UNKNOWN and nothing was fused"
            )
        return verdict
    if mode == SOURCE_SAVE_MODE and save_binding is None:
        verdict["status"] = "REJECTED"
        verdict["statement"] = "source-save mode requires a verified retained save binding"
        return verdict
    if mode == SAME_SESSION_MODE and fresh_contradictions:
        verdict["status"] = "REJECTED"
        verdict["statement"] = (
            "the in-session facts bank contradicts the retained TileFacts;"
            " cross-run fusion is refused"
        )
        return verdict
    verdict["status"] = "CORRESPONDENCE_ESTABLISHED"
    verdict["statement"] = {
        SOURCE_SAVE_MODE: (
            "the census was captured from the byte-verified retained world state"
            " and bound to the retained TileFacts projection"
        ),
        FRESH_GENERATION_MODE: (
            "the fresh generation echoed the retained world identity and every"
            " shared per-tile fact agrees with the retained TileFacts"
        ),
        SAME_SESSION_MODE: (
            "one session re-observed the facts bank and classified the census;"
            " both banks agree tile by tile with the retained record"
        ),
    }[mode]
    return verdict
