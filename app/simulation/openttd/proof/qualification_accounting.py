"""Qualification configuration of the existing secure native frame observer."""

from types import MappingProxyType

from app.simulation.openttd.qualification_policy import MAX_POST_AUTH_FRAMES, PHASE_BOUNDS

from .structural_contract import StructuralFrameBudget


class QualificationFrameBudget(StructuralFrameBudget):
    limits = MappingProxyType(
        {"establishment": 2, "setup": 3, **{k: v[2] for k, v in PHASE_BOUNDS.items()}, "cleanup": 1}
    )
    maximum_frames = MAX_POST_AUTH_FRAMES
    query_phases = tuple(PHASE_BOUNDS)

    def __init__(self):
        super().__init__()
        self._counts = dict.fromkeys(self.limits, 0)

    def enter(self, phase: str) -> None:
        if self.failed or phase not in self.limits:
            raise ValueError("unavailable qualification accounting phase")
        if phase == "setup":
            if self.phase != "establishment" or self._counts["establishment"] != 2:
                raise ValueError("exact single establishment required")
        elif phase in self.query_phases:
            if self.phase == "establishment" or self._counts["setup"] != 3:
                raise ValueError("explicit single subscription setup required")
            if self.phase == "cleanup":
                raise ValueError("accounting cannot resume after cleanup")
        elif phase != "cleanup":
            raise ValueError("accounting cannot reset establishment")
        self.phase = phase
