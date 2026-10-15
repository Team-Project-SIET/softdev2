"""The version-15 no-mutation GameScript package; staging never launches a game."""

import hashlib
from pathlib import Path

from app.simulation.openttd.observation_identity import (
    BridgePackage as BridgePackage,
)
from app.simulation.openttd.runtime.config import RuntimeWorkspace

BRIDGE_DIRECTORY = Path(__file__).with_name("gamescript_bridge_package")
PACKAGE_FILES = ("info.nut", "main.nut")


def stage_bridge(workspace: RuntimeWorkspace) -> BridgePackage:
    """Select this package for a future new world in an already prepared workspace."""
    if workspace.game.is_symlink() or not workspace.game.resolve().is_relative_to(workspace.root):
        raise ValueError("GameScript staging directory escapes workspace")
    if workspace.config.is_symlink() or not workspace.config.resolve().is_relative_to(
        workspace.root
    ):
        raise ValueError("configuration escapes workspace")
    config = workspace.config.read_text()
    if "[game_scripts]" in config:
        raise ValueError("GameScript already selected")
    directory = workspace.game / "NoMutationBridge"
    directory.mkdir(mode=0o700)
    digest = hashlib.sha256()
    for name in PACKAGE_FILES:
        content = (BRIDGE_DIRECTORY / name).read_bytes()
        with (directory / name).open("xb") as output:
            output.write(content)
        digest.update(name.encode() + b"\0" + len(content).to_bytes(8, "big") + content)
    with workspace.config.open("a") as output:
        output.write("\n[game_scripts]\nNoMutationBridge = \n")
    return BridgePackage(directory, digest.hexdigest())
