"""Offline correspondence and exclusive provenance; no native execution."""

import copy
import hashlib

import pytest
from pydantic import ValidationError

from app.simulation.openttd.freight_canonical import (
    CanonicalObservation,
    compare_canonical,
    seal_canonical_inputs,
)


def observation():
    vehicle = dict(
        owner=0,
        engine=5,
        cargo=2,
        capacity=20,
        tile=30,
        stopped=True,
        in_depot=True,
        speed=0,
        load=0,
        orders=[
            dict(destination=10, flags=64, goto_station=True),
            dict(destination=20, flags=128, goto_station=True),
        ],
    )
    return dict(
        qualification_id="canonical-create-q1",
        runtime_sha256="a" * 64,
        bridge_sha256="b" * 64,
        configuration_sha256="c" * 64,
        source_save_sha256="d" * 64,
        raw_readback_sha256="e" * 64,
        script_tick=100,
        state=dict(
            economy_date=700000,
            economy_date_fraction=0,
            calendar_date=700000,
            calendar_date_fraction=0,
            timekeeping=0,
            paused=True,
            auto_renew=False,
            company=0,
            cash=470000,
            loan=100000,
            map={"width": 64, "height": 64},
            industries_production=[{"industry": 1, "production": 100}],
            stations_cargo=[{"station": 1, "waiting": 0}],
            infrastructure=[{"tile": 30, "owner": 0}],
            vehicles=[dict(vehicle, service=i, vehicle=i + 1) for i in range(3)],
            delivered=[0, 0, 0],
        ),
    )


def parse(value):
    # JSON round-trip matches the retained native collector artifact boundary.
    import json

    return CanonicalObservation.model_validate_json(json.dumps(value))


def test_exact_correspondence_allows_only_process_metadata():
    created = observation()
    loaded = copy.deepcopy(created)
    loaded.update(
        qualification_id="canonical-reload-q1", script_tick=1, raw_readback_sha256="f" * 64
    )
    compare_canonical(parse(created), parse(loaded))
    with pytest.raises(ValueError, match="distinct"):
        compare_canonical(parse(created), parse(created))


@pytest.mark.parametrize(
    "field,value",
    [
        ("economy_date", 700001),
        ("economy_date_fraction", 1),
        ("calendar_date", 700001),
        ("calendar_date_fraction", 1),
        ("timekeeping", 1),
        ("cash", 469999),
        ("loan", 0),
        ("stations_cargo", [{"station": 1, "waiting": 1}]),
        ("infrastructure", [{"tile": 30, "owner": 1}]),
        ("industries_production", [{"industry": 1, "production": 101}]),
    ],
)
def test_semantic_drift_rejected(field, value):
    created = observation()
    loaded = copy.deepcopy(created)
    loaded["qualification_id"] = "canonical-reload-q1"
    loaded["state"][field] = value
    with pytest.raises(ValueError, match="correspondence"):
        compare_canonical(parse(created), parse(loaded))


@pytest.mark.parametrize(
    "field,value",
    [
        ("vehicle", 2),
        ("service", 1),
        ("stopped", False),
        ("speed", 1),
        ("load", 1),
        ("orders", []),
        ("in_depot", False),
    ],
)
def test_missing_bindings_and_movement_rejected(field, value):
    value_dict = observation()
    value_dict["state"]["vehicles"][0][field] = value
    with pytest.raises(ValidationError):
        parse(value_dict)


def test_position_drift_rejected():
    created = observation()
    loaded = copy.deepcopy(created)
    loaded["qualification_id"] = "canonical-reload-q1"
    loaded["state"]["vehicles"][0]["tile"] += 1
    with pytest.raises(ValueError, match="correspondence"):
        compare_canonical(parse(created), parse(loaded))


def test_seal_binds_exact_bytes_and_never_overwrites(tmp_path):
    save = tmp_path / "canonical.sav"
    raw = tmp_path / "readback.jsonl"
    dest = tmp_path / "canonical-provenance.json"
    save.write_bytes(b"controlled-save-not-native")
    raw.write_bytes(b"controlled-readback-not-native")
    value = observation()
    value.update(
        source_save_sha256=hashlib.sha256(save.read_bytes()).hexdigest(),
        raw_readback_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
    )
    seal = seal_canonical_inputs(dest, save, parse(value), raw)
    assert seal == hashlib.sha256(dest.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        seal_canonical_inputs(dest, save, parse(value), raw)
    save.write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes mismatch"):
        seal_canonical_inputs(tmp_path / "other.json", save, parse(value), raw)
    assert not (tmp_path / "other.json").exists()
