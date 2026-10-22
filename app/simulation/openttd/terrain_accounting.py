"""Standalone design accounting configuration, not a native proof freeze."""

from types import MappingProxyType

from app.simulation.openttd.proof.structural_contract import StructuralFrameBudget


class TerrainFrameBudget(StructuralFrameBudget):
    limits = MappingProxyType(
        {"establishment": 2, "setup": 3, "sweep1": 416, "sweep2": 416, "cleanup": 1}
    )
    maximum_frames = 838
    query_phases = ("sweep1", "sweep2")

    def __init__(self):
        super().__init__()
        self._counts = dict.fromkeys(self.limits, 0)

    def enter(self, phase: str):
        if self.phase == "establishment" and self.total_frames != 2:
            raise ValueError("single establishment must finish")
        if self.phase == "setup" and self._counts["setup"] != 3:
            raise ValueError("explicit subscription must finish before tile queries")
        super().enter(phase)
