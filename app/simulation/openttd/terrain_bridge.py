"""Compose terrain-only extension without rewriting historical bridge packages."""

from pathlib import Path

from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY


def terrain_bridge_source() -> str:
    source = (BRIDGE_DIRECTORY / "main.nut").read_text()
    marker = "class NoMutationBridge extends GSController"
    if source.count(marker) != 1:
        raise ValueError("raw bridge composition authority changed")
    return (
        source.replace(marker, "class RawObservationBridge extends GSController")
        + Path(__file__).with_suffix(".nut").read_text()
    )
