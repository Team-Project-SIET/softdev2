"""Strict native outer wire boundaries; no native execution."""

import hashlib
import json
from dataclasses import asdict

import pytest

from app.simulation.openttd.proof.endpoints import endpoint_cleanup_contract
from app.simulation.openttd.terrain_native_records import (
    GATES,
    AuthenticationRecord,
    Commitment,
    Completion,
    Prelaunch,
    Resources,
    argv_sha256,
    encode,
    parse_completion,
    parse_prelaunch,
    parse_record,
)
from app.simulation.openttd.terrain_pagination import PaginationBudget
from app.simulation.openttd.terrain_sweeps import TwoSweepBudget


def test_exact_argv_commitment():
    assert (
        argv_sha256(("/runtime/openttd", "-c", "/runtime/openttd.cfg"))
        == hashlib.sha256(b'{"argv":["/runtime/openttd","-c","/runtime/openttd.cfg"]}').hexdigest()
    )


@pytest.mark.parametrize("argument", ["", "e\u0301", "a\x00b"])
def test_invalid_argv_rejected(argument):
    with pytest.raises(ValueError):
        argv_sha256((argument,))


def test_completion_wire_alias_roundtrip():
    raw = (
        b'{"artifacts":[],"attempt_identity":"attempt-1","mode":"REAL",'
        b'"operation":"openttd-15.3.tile_facts_page.two_sweeps",'
        b'"paired_descriptor_sha256":null,"prelaunch_sha256":"'
        + b"0"
        * 64
        + b'","schema":"terrain-native-paired-evidence-v1","status":"REAL_FAIL",'
        b'"terminal_phase":"FAILED_CLEANED","version":1}'
    )
    value = parse_completion(raw)
    assert isinstance(value, Completion)
    assert encode(value) == raw


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw.replace(b'"version":1', b'"version":2'),
        lambda raw: raw.replace(b'"version":1', b'"version":true'),
        lambda raw: raw.replace(b'"version":1', b'"version":1,"extra":null'),
        lambda raw: raw.replace(b'"version":1', b'"version":1,"version":1'),
        lambda raw: raw + b"\n",
    ],
)
def test_strict_record_parser_rejects_invalid_structure(mutation):
    raw = encode(
        AuthenticationRecord.model_validate_json(
            b'{"schema":"terrain-native-paired-evidence-v1","version":1,'
            b'"kind":"authentication","attempt_identity":"attempt-1",'
            b'"prelaunch_sha256":"'
            + b"0" * 64
            + b'","observations":{"available":false,"reason":"NOT_CONNECTED","phase":"CLAIMED"}}'
        )
    )
    with pytest.raises(ValueError):
        parse_record(mutation(raw))


def test_failed_handshake_prefix_is_retained_without_success():
    raw = (
        b'{"schema":"terrain-native-paired-evidence-v1","version":1,"kind":"authentication",'
        b'"attempt_identity":"attempt-1","prelaunch_sha256":"'
        + b"0"
        * 64
        + b'","observations":{"available":true,"session_id":"session-1",'
        b'"process":{"pid":10,"start":"123"},"endpoints":{"family":"AF_INET",'
        b'"host":"127.0.0.1","game_port":39000,"admin_port":39001},"public_key":"'
        + b"1" * 64
        + b'","public_key_sha256":"'
        + b"2" * 64
        + b'","method":null,"encrypted":false,"state":"AUTH_JOIN_SENT",'
        b'"states":[{"ordinal":1,"state":"AUTH_JOIN_SENT","time_ns":1}],'
        b'"protocol":null,"welcome":null,"handshake":[{"ordinal":1,"direction":"outbound",'
        b'"packet_type":1,"encoded_byte_length":5,"encoded_sha256":"'
        + b"3" * 64
        + b'","state":"AUTH_JOIN_SENT"}]}}'
    )
    record = AuthenticationRecord.model_validate_json(raw)
    assert parse_record(encode(record)) == record


def prelaunch_wire():
    """A schema fixture, not launch authority or a prepared native package."""
    digest = "0" * 64
    source = dict(
        identity="candidate:CANDIDATE.json",
        origin="/candidate/CANDIDATE.json",
        byte_length=1,
        sha256=digest,
    )
    commitment = dict(path="seal/page-plan.json", byte_length=1, sha256=digest)
    resources = Resources(
        startup_ns=1,
        query_ns=1,
        marker_ns=1,
        acquisition_ns=1,
        cleanup_ns=1,
        finalization_ns=1,
        raw_reader_bytes=1,
        frame_queue_count=1,
        frame_queue_bytes=1,
        decrypted_queue_count=1,
        decrypted_queue_bytes=1,
        host_admission_bytes=1,
        process_rss_bytes=1,
        memory_monitor_interval_ns=1,
        stdout_bytes=1,
        stderr_bytes=1,
        paired_bytes=1,
        outer_bytes=1,
        outer_files=1,
        admission_evidence=(Commitment(path="seal/page-plan.json", byte_length=1, sha256=digest),),
    ).model_dump(mode="json")
    return dict(
        schema="terrain-native-paired-prelaunch-v1",
        version=1,
        mode="REAL",
        operation="openttd-15.3.tile_facts_page.two_sweeps",
        attempt=dict(identity="fixture", destination="/attempt", seal_destination="/seal"),
        runtime=dict(
            executable=source,
            version="15.3",
            graphics_archive=source,
            graphics_files=[],
            bridge_inputs=[],
            bridge_sha256=digest,
            argv=["/executable"],
            environment={},
            public_config=[],
        ),
        source=dict(
            candidate=source,
            source_freeze_sha256=digest,
            canonical_inputs_sha256=digest,
            ownership_sha256=digest,
            materializations_sha256=digest,
            historical_integrity_sha256=digest,
            recipe=dict(map_x=6, map_y=6, seed=42, start_date=1, landscape=0),
            recipe_sha256=digest,
        ),
        context=dict(
            acquisition_id="fixture",
            world_fingerprint=digest,
            map_width=64,
            map_height=64,
            region=dict(x=1, y=1, width=1, height=1),
        ),
        plan=commitment,
        budgets=dict(
            per_sweep=asdict(PaginationBudget()),
            combined=asdict(TwoSweepBudget()),
            frames=dict(
                post_auth_frames=22,
                pre_auth_frames=4,
                post_auth_stream_bytes=22 * 32767,
                pre_auth_stream_bytes=4 * 32767,
            ),
        ),
        resources=resources,
        endpoint_policy=dict(
            policy=endpoint_cleanup_contract(),
            family="AF_INET",
            host="127.0.0.1",
            game_port=3979,
            admin_port=3980,
            client_public_key=digest,
            client_public_key_sha256=digest,
        ),
        artifact_policy=dict(schema="terrain-native-paired-evidence-v1", version=1),
        required_gates=list(GATES),
        commitments=[commitment],
        external_authorities=[
            dict(
                role="historical",
                provenance_base="/history",
                identity="history",
                inventory_sha256=digest,
                policy="historical-exact-paths-v1",
            )
        ],
    )


def test_prelaunch_preserves_exact_wire_roundtrip_and_freezing():
    raw = json.dumps(prelaunch_wire(), sort_keys=True, separators=(",", ":")).encode()
    parsed = parse_prelaunch(raw)
    assert isinstance(parsed, Prelaunch)
    assert parsed.version == 1
    assert parsed.schema_id == "terrain-native-paired-prelaunch-v1"
    assert encode(parsed) == raw
    with pytest.raises(ValueError):
        setattr(parsed, "version", 2)
    assert parsed.version == 1


@pytest.mark.parametrize("mutation", ["version", "missing", "extra", "nested-extra"])
def test_prelaunch_strict_schema_survives_direct_inheritance(mutation):
    value = prelaunch_wire()
    if mutation == "version":
        value["version"] = True
    elif mutation == "missing":
        del value["version"]
    elif mutation == "extra":
        value["unreviewed"] = True
    else:
        value["runtime"]["unreviewed"] = True
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ValueError):
        parse_prelaunch(raw)


def test_resource_wire_preserves_numeric_caps_and_admission_list():
    resources = prelaunch_wire()["resources"]
    assert resources["startup_ns"] == 1
    assert resources["outer_files"] == 1
    assert resources["admission_evidence"] == [
        {"path": "seal/page-plan.json", "byte_length": 1, "sha256": "0" * 64}
    ]
    raw = json.dumps(resources, sort_keys=True, separators=(",", ":")).encode()
    assert encode(Resources.model_validate_json(raw)) == raw


@pytest.mark.parametrize("mutation", ["boolean-cap", "missing-admission", "invalid-admission"])
def test_resource_schema_remains_strict(mutation):
    resources = prelaunch_wire()["resources"]
    if mutation == "boolean-cap":
        resources["startup_ns"] = True
    elif mutation == "missing-admission":
        del resources["admission_evidence"]
    else:
        resources["admission_evidence"][0]["unreviewed"] = True
    with pytest.raises(ValueError):
        Resources.model_validate_json(json.dumps(resources))
