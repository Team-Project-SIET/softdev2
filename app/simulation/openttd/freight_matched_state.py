"""Offline matched-capacity admission checks; never grant native authority."""

import hashlib
from pathlib import Path

from app.simulation.openttd.prepared_source_correspondence import ControlledSourceLinks

MATCHED_STATE_BLOCKERS = (
    "canonical paused post-construction/pre-intervention save with three fixed vehicles "
    "and native company, orders, infrastructure, production and finance readbacks unavailable",
    "save/load preservation of service bindings and loaded-world correspondence unverified",
)


def inspect_capacity_source(directory: Path) -> dict:
    """Check retained prepared-save bytes without relabeling them a matched fleet state.

    Existing prepared-source links bind pre-construction saves. They cannot witness
    the later three-vehicle purchase/dispatch boundary, even after offline recovery.
    """
    directory = Path(directory).absolute()
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("matched source must not contain symlinks")
    names = ("prepared-source-links.json", "before.sav", "qualified.sav")
    if any((directory / name).is_symlink() for name in names):
        raise ValueError("matched source files must not be symlinks")
    links = ControlledSourceLinks.model_validate_json(
        (directory / "prepared-source-links.json").read_bytes()
    )
    saves = {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in ("before.sav", "qualified.sav")
    }
    if (
        links.evidence_kind != "owned-native-save-snapshots"
        or links.original_save_digest != saves["before.sav"]
        or links.post_qualification_save_digest != saves["qualified.sav"]
    ):
        raise ValueError("retained prepared-save identity mismatch")
    return dict(
        classification="SOURCE_BYTES_VERIFIED_ONLY",
        native_ready=False,
        save_hashes=saves,
        canonical_fleet_save=None,
        blockers=list(MATCHED_STATE_BLOCKERS),
        native_launches=0,
        admin_connections=0,
    )


def validate_capacity_branches(branches: dict) -> None:
    """Reject inequivalent proposed branches; equality is not native proof.

    Each state is the full same-schema pre-intervention readback, including map,
    industries/production, company, infrastructure, original vehicles/orders,
    finances, economy date and timekeeping. No digest or caller label establishes
    that such a readback was actually produced by a loaded native world.
    """
    if set(branches) != {"A", "B", "C"}:
        raise ValueError("exact A/B/C branches required")
    fields = {
        "save_sha256",
        "runtime_sha256",
        "configuration_sha256",
        "bridge_sha256",
        "settings",
        "state",
        "auto_renew",
        "attempt_id",
        "intervention_service",
        "intervention_after_branch",
    }
    state_fields = {
        "map",
        "industries_production",
        "company",
        "infrastructure",
        "vehicles_orders",
        "finances",
        "economy_date",
        "timekeeping",
    }
    identities = set()
    for name, branch in branches.items():
        if set(branch) != fields or set(branch["state"]) != state_fields:
            raise ValueError("complete branch and pre-intervention state required")
        if not isinstance(branch["attempt_id"], str) or not branch["attempt_id"].strip():
            raise ValueError("distinct nonempty attempt identities required")
        identities.add(branch["attempt_id"])
        if branch["auto_renew"] is not False:
            raise ValueError("fixed-vehicle auto-renew must be disabled")
        if branch["intervention_service"] != {"A": None, "B": 1, "C": 2}[name]:
            raise ValueError("A/B/C intervention mismatch")
        if branch["intervention_after_branch"] is not True:
            raise ValueError("intervention must follow branching")
        for key in ("save_sha256", "runtime_sha256", "configuration_sha256", "bridge_sha256"):
            value = branch[key]
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError("canonical SHA-256 identity required")
    if len(identities) != 3:
        raise ValueError("distinct attempt identities required")
    common = fields - {"attempt_id", "intervention_service", "intervention_after_branch"}
    if any(branches[name][key] != branches["A"][key] for name in ("B", "C") for key in common):
        raise ValueError("pre-intervention branch correspondence mismatch")
