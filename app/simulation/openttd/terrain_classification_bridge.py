"""Compose the schema-2 classification bridge without touching frozen sources.

The v1 terrain capture package (``terrain_bridge.py`` composing
``terrain_bridge.nut``) and the base ``gamescript_bridge_package`` stay exactly
as they are: historical digests, staged correspondence, EVIDENCE_INDEX records
and the leaked fixed/run artifacts depend on those bytes. The classification
capture is a separate, explicitly versioned composition — base sources with the
marker rename that both proven compositions already use, plus the additive
``terrain_classification.nut`` handler — bound at capture time by its own
package digest. Nothing here launches the game or allocates an attempt.
"""

import hashlib
from pathlib import Path

from app.simulation.openttd.gamescript_bridge import (
    BRIDGE_DIRECTORY,
    PACKAGE_FILES,
)

CLASSIFICATION_HANDLER_FILE = Path(__file__).with_name("terrain_classification.nut")
CLASSIFICATION_SCHEMA_VERSION = 2


def terrain_classification_source() -> str:
    """Compose base bridge + additive classification handler (no file writes)."""
    source = (BRIDGE_DIRECTORY / "main.nut").read_text()
    marker = "class NoMutationBridge extends GSController"
    if source.count(marker) != 1:
        raise ValueError("raw bridge composition authority changed")
    handler = CLASSIFICATION_HANDLER_FILE.read_text()
    required = (
        'request.type != "tile_classification_page"',
        'typeof request.schema!="integer" || request.schema!=2',
        "local predicates=[buildable,water,coast,tree,farm,rock,rough,"
        "road_tile,road_track,road0,rail,water_transport,airport,house,station];",
        "TILE_CLASSIFICATION_READ",
        "class NoMutationBridge extends TerrainClassificationBridge {}",
    )
    for fragment in required:
        if fragment not in handler:
            raise ValueError("classification handler composition authority changed")
    composed = source.replace(marker, "class RawObservationBridge extends GSController") + handler
    if composed.count("class RawObservationBridge extends GSController") != 1:
        raise ValueError("base bridge marker rename drifted")
    return composed


def classification_package_bytes() -> dict[str, bytes]:
    """Staged package for the classification capture composition."""
    return {
        "info.nut": (BRIDGE_DIRECTORY / "info.nut").read_bytes(),
        "main.nut": terrain_classification_source().encode(),
    }


def classification_package_digest(package: dict[str, bytes] | None = None) -> str:
    """Same digest convention as terrain preparation: name\\0 len\\0 content."""
    package = classification_package_bytes() if package is None else package
    h = hashlib.sha256()
    for name in sorted(PACKAGE_FILES):
        b = package[name]
        h.update(name.encode() + b"\0" + len(b).to_bytes(8, "big") + b)
    return h.hexdigest()


def classification_capture_consistency() -> dict[str, str | int | None]:
    """Offline readiness facts for a future authorized capture (no launch)."""
    package = classification_package_bytes()
    return {
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "handler_file": "app/simulation/openttd/terrain_classification.nut",
        "composed_main_nut_bytes": len(package["main.nut"]),
        "classification_package_digest": classification_package_digest(package),
        # The v1 terrain composition keeps its own builder and bytes so every
        # historical capture identity remains reproducible.
        "v1_composer": "app/simulation/openttd/terrain_bridge.py",
        "v1_sample_request_type": "tile_facts_page",
    }
