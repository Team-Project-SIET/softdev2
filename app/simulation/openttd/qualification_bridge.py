"""Compose the qualification adapter without changing the proven raw package."""

import hashlib
from pathlib import Path

from app.simulation.openttd.gamescript_bridge import (
    BRIDGE_DIRECTORY,
    PACKAGE_FILES,
    BridgePackage,
    stage_bridge,
)


def qualification_bridge_source() -> str:
    source = (BRIDGE_DIRECTORY / "main.nut").read_text()
    marker = "class NoMutationBridge extends GSController"
    if source.count(marker) != 1:
        raise ValueError("raw bridge composition authority changed")
    return (
        source.replace(marker, "class RawObservationBridge extends GSController")
        + Path(__file__).with_suffix(".nut").read_text()
    )


def stage_qualification_bridge(workspace) -> BridgePackage:
    package = stage_bridge(workspace)
    (package.directory / "main.nut").write_text(qualification_bridge_source())
    digest = hashlib.sha256()
    for name in PACKAGE_FILES:
        content = (package.directory / name).read_bytes()
        digest.update(name.encode() + b"\0" + len(content).to_bytes(8, "big") + content)
    return BridgePackage(package.directory, digest.hexdigest())
