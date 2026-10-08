"""Exact tagged native authority and derived thin qualification package identity."""

import hashlib
import json

from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY, PACKAGE_FILES
from app.simulation.openttd.qualification_bridge import qualification_bridge_source

from .qualification_contract import digest, qualification_contract


def bridge_digest():
    h = hashlib.sha256()
    for name in PACKAGE_FILES:
        content = (
            qualification_bridge_source().encode()
            if name == "main.nut"
            else (BRIDGE_DIRECTORY / name).read_bytes()
        )
        h.update(name.encode() + b"\0" + len(content).to_bytes(8, "big") + content)
    return h.hexdigest()


def qualification_authority():
    from .harness import PROJECT, sha256

    files = {}
    for directory in ("economy_clock_15_3", "qualification_15_3", "qualification_timing_15_3"):
        path = PROJECT / "tests/reference" / directory / "manifest.json"
        manifest = json.loads(path.read_text())
        if manifest["version"] != "15.3":
            raise ValueError("Exact native qualification source version required")
        files[str(path)] = sha256(path)
        for name, entry in manifest["files"].items():
            source = PROJECT / name
            if sha256(source) != entry["sha256"]:
                raise ValueError("Native qualification authority changed")
            files[str(source)] = entry["sha256"]
    contract = qualification_contract()
    value = dict(
        version="15.3",
        files=files,
        clock=contract["native_clock"],
        lifetime=contract["lifetime"],
        profile=contract["profile"],
        timing=dict(
            tick_ms=27,
            ticks_per_day=74,
            nominal_day_seconds=1.998,
            hard_real_time_guarantee=False,
            paused_economy_stops=True,
        ),
        date_domains=(
            "construction CALENDAR identity; qualification ECONOMY; "
            "synchronized generated calendar profile only"
        ),
    )
    value["sha256"] = digest(value)
    return value
