"""Semantic reconciliation of synthetic native outer evidence, never REAL acceptance."""

import hashlib
import json
import unicodedata
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.planning.canonical import canonical_bytes
from app.simulation.openttd.proof.endpoints import verify_retained_endpoints
from app.simulation.openttd.proof.terrain_attempt import verify_cleanup_records
from app.simulation.openttd.terrain_sweeps import VerifiedTerrainPair
from app.simulation.openttd.tile_facts import TileFactsRequest
from app.simulation.openttd.tile_facts_evidence import (
    GS_SEQUENCE,
    MARKER,
    parse_tile_facts_evidence,
)


class LaunchArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    argv: tuple[str, ...]


def argv_digest(argv: list[str]) -> str:
    if not argv or any(not a or "\0" in a or unicodedata.normalize("NFC", a) != a for a in argv):
        raise ValueError("Invalid native launch arguments")
    return hashlib.sha256(canonical_bytes(LaunchArguments(argv=tuple(argv)))).hexdigest()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _observation(records: dict, name: str) -> dict:
    try:
        return records[name]["observations"]
    except KeyError as error:
        raise ValueError("Missing native observations: " + name) from error


class BindingIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    policy: Literal["terrain-native-binding-v1"] = "terrain-native-binding-v1"
    domain: Literal["owned-path", "canonical-input", "seal-artifact"]
    locator: str


class OwnedResource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    policy: Literal["terrain-native-owned-resource-v1"] = "terrain-native-owned-resource-v1"
    path: str
    kind: Literal["directory", "capture"]
    ownership_sha256: str


class PublicCredential(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    policy: Literal["terrain-native-private-key-materialization-v1"] = (
        "terrain-native-private-key-materialization-v1"
    )
    attempt_identity: str
    operation: str
    path: str
    public_key_sha256: str
    ownership_sha256: str


def binding_identity(
    domain: Literal["owned-path", "canonical-input", "seal-artifact"], locator: str
) -> str:
    """Derive a record identity from an already authorized canonical locator."""
    if not locator or unicodedata.normalize("NFC", locator) != locator:
        raise ValueError("Native binding locator is not NFC")
    return "binding-" + _digest(canonical_bytes(BindingIdentity(domain=domain, locator=locator)))


def native_binding_requirements(
    prelaunch: dict, content: dict[str, bytes]
) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Derive exact disposal and integrity commitments from verified sealed inputs.

    Callers must first validate independent prelaunch pins and sealed provenance.
    This function neither reads credentials nor authorizes a process lifecycle.
    """
    ownership = json.loads(content["seal/path-ownership.json"])
    materializations = json.loads(content["seal/runtime-materializations.json"])
    index = json.loads(content["seal/canonical-inputs.json"])
    source = prelaunch["source"]
    credentials = [e["path"] for e in ownership["entries"] if e["kind"] == "RUNTIME_CREDENTIAL"]
    _require(len(credentials) == 1, "Native credential ownership coverage mismatch")
    key_path = credentials[0]
    endpoint = prelaunch["endpoint_policy"]
    public = bytes.fromhex(endpoint["client_public_key"])
    _require(
        len(public) == 32 and _digest(public) == endpoint["client_public_key_sha256"],
        "Native public credential identity mismatch",
    )
    key_digest = _digest(
        canonical_bytes(
            PublicCredential(
                attempt_identity=prelaunch["attempt"]["identity"],
                operation=prelaunch["operation"],
                path=key_path,
                public_key_sha256=endpoint["client_public_key_sha256"],
                ownership_sha256=source["ownership_sha256"],
            )
        )
    )
    rows = {e["path"]: e["sha256"] for e in materializations["entries"]}
    candidate_entry = next(
        e for e in index["entries"] if e["identity"] == "candidate:CANDIDATE.json"
    )
    candidate = json.loads(content["seal/" + candidate_entry["artifact"]])
    captures = set(candidate["capture_outputs"])
    disposal: dict[str, str] = {}
    checks: dict[tuple[str, str], str] = {}
    paths: set[str] = set()
    roots = {PurePosixPath(p) for p in ownership["cleanup_roots"]}
    directories = set(roots)
    for entry in ownership["entries"]:
        if entry["kind"] not in ("RUNTIME_EPHEMERAL", "RUNTIME_CREDENTIAL"):
            continue
        path = entry["path"]
        _require(path not in paths, "Native duplicate owned identity")
        paths.add(path)
        current = PurePosixPath(path)
        matching = [r for r in roots if current.is_relative_to(r)]
        _require(len(matching) == 1, "Native disposable root ambiguity")
        root = matching[0]
        for parent in current.parents:
            if not parent.is_relative_to(root):
                break
            directories.add(parent)
        identity = binding_identity("owned-path", path)
        if path == key_path:
            digest = key_digest
        elif path in rows:
            digest = rows[path]
        else:
            _require(path in captures, "Native undeclared disposable file")
            digest = _digest(
                canonical_bytes(
                    OwnedResource(
                        path=path, kind="capture", ownership_sha256=source["ownership_sha256"]
                    )
                )
            )
        disposal[identity] = digest
        if path == key_path or path in rows:
            checks[("final_pre_popen", identity)] = digest
    for directory in directories:
        path = str(directory)
        _require(path not in paths, "Native conflicting disposal identity")
        identity = binding_identity("owned-path", path)
        disposal[identity] = _digest(
            canonical_bytes(
                OwnedResource(
                    path=path, kind="directory", ownership_sha256=source["ownership_sha256"]
                )
            )
        )
    canonical_objects = set()
    for entry in index["entries"]:
        identity = binding_identity("canonical-input", entry["identity"])
        for phase in ("final_pre_popen", "post_run"):
            _require((phase, identity) not in checks, "Native duplicate integrity identity")
            checks[(phase, identity)] = entry["sha256"]
        canonical_objects.add("seal/" + entry["artifact"])
    for entry in prelaunch["commitments"]:
        if entry["path"] in canonical_objects:
            continue
        identity = binding_identity("seal-artifact", entry["path"])
        for phase in ("final_pre_popen", "post_run"):
            checks[(phase, identity)] = entry["sha256"]
    return dict(sorted(disposal.items())), dict(sorted(checks.items()))


def _bindings(prelaunch: dict, records: dict, content: dict[str, bytes], successful: bool) -> None:
    expected_disposal, expected_checks = native_binding_requirements(prelaunch, content)
    disposal = _observation(records, "credential-disposal")
    integrity = _observation(records, "post-run-integrity")
    lifecycle = _observation(records, "lifecycle")
    events = lifecycle["events"] if lifecycle["available"] else []
    times = {e["event"]: e["time_ns"] for e in events}
    if disposal["available"]:
        entries = disposal["materializations"]
        _require(
            [e["identity"] for e in entries] == list(expected_disposal),
            "Native disposal identity coverage mismatch",
        )
        for entry in entries:
            _require(
                entry["commitment_sha256"] == expected_disposal[entry["identity"]],
                "Native disposal commitment mismatch",
            )
            if successful:
                _require(
                    entry["removed"]
                    and times["cleanup_started"] <= entry["observed_ns"] <= times["finalized"],
                    "Native disposal observation mismatch",
                )
    else:
        _require(not successful, "Native disposal unavailable")
    if integrity["available"]:
        entries = integrity["before_disposal"]
        pairs = [(e["phase"], e["identity"]) for e in entries]
        _require(len(pairs) == len(set(pairs)), "Native duplicate integrity check")
        if successful:
            _require(pairs == list(expected_checks), "Native integrity phase coverage mismatch")
        else:
            for phase in ("final_pre_popen", "post_run"):
                actual = [p for p in pairs if p[0] == phase]
                planned = [p for p in expected_checks if p[0] == phase]
                _require(
                    actual == planned[: len(actual)], "Native failure integrity prefix mismatch"
                )
        for entry in entries:
            pair = (entry["phase"], entry["identity"])
            _require(
                pair in expected_checks and entry["expected_sha256"] == expected_checks[pair],
                "Native integrity sealed commitment mismatch",
            )
            observed, expected = entry["observed_sha256"], expected_checks[pair]
            outcome = (
                "MISSING" if observed is None else "MATCH" if observed == expected else "CHANGED"
            )
            _require(entry["outcome"] == outcome, "Native contradictory integrity outcome")
            if successful:
                _require(outcome == "MATCH", "Native required integrity failure")
            if entry["phase"] == "final_pre_popen" and "launched" in times:
                _require(
                    entry["checked_ns"] <= times["launched"], "Native final input check ordering"
                )
            if entry["phase"] == "post_run":
                runtime = _observation(records, "runtime")
                if runtime["available"] and runtime["exited_ns"] is not None:
                    _require(
                        runtime["exited_ns"] <= entry["checked_ns"], "Native postrun check ordering"
                    )
                if "cleanup_started" in times:
                    _require(
                        entry["checked_ns"] <= times["cleanup_started"],
                        "Native integrity disposal ordering",
                    )
        history = integrity["history"]
        (authority,) = prelaunch["external_authorities"]
        historical = json.loads(content["seal/historical-integrity.json"])
        _require(
            history["identity"] == authority["identity"]
            and history["inventory_sha256"] == authority["inventory_sha256"]
            and history["validated_paths"] == len(historical["entries"]),
            "Native historical integrity coverage mismatch",
        )
    else:
        _require(not successful, "Native integrity unavailable")


def _lineage(prelaunch: dict, records: dict, content: dict[str, bytes]) -> None:
    attempt = prelaunch["attempt"]
    grant = records["authorization-consumed"]
    expected = dict(
        authorization_mode="OPERATOR_ATTENDED_LOCAL_PROOF",
        trust="LOCAL_OPERATOR_ATTESTED",
        proof_operation=prelaunch["operation"],
        attempt_identity=attempt["identity"],
        attempt_directory=attempt["destination"],
        launch_allowance=1,
        connection_allowance=1,
        request_allowance=sum(len(s["pages"]) for s in records["page-plan"]["sweeps"]),
        state="STARTED",
        no_retry=True,
        no_reconnect=True,
        no_relaunch=True,
        no_resume=True,
    )
    _require(all(grant.get(k) == v for k, v in expected.items()), "Native grant lineage mismatch")
    seal = _digest(content["seal/PRELAUNCH.json"])
    _require(grant["seal_sha256"] == seal, "Native grant seal mismatch")
    for name, previous, field in (
        ("launch-claim", "authorization-consumed.json", "consumed_record_sha256"),
        ("native-launch-claimed", "launch-claim.json", "launch_claim_sha256"),
    ):
        if name not in records:
            continue
        record = records[name]
        shared = (
            "attempt_identity",
            "attempt_directory",
            "owner_pid",
            "owner_start",
            "owner_nonce",
        )
        _require(
            all(record[k] == grant[k] for k in shared)
            and record["seal_sha256"] == seal
            and record[field] == _digest(content[previous])
            and record["no_retry"] is True,
            "Native invocation lineage mismatch",
        )
    if "native-launch-claimed" in records:
        _require(
            records["native-launch-claimed"]["launch_invocations"] == 1,
            "Native launch count mismatch",
        )


def _runtime(prelaunch: dict, records: dict) -> None:
    value = _observation(records, "runtime")
    if not value["available"]:
        return
    runtime = prelaunch["runtime"]
    configs = [
        c
        for c in runtime["public_config"]
        if c["identity"] == "candidate:materialization-inputs/openttd.cfg"
    ]
    _require(len(configs) == 1, "Missing authoritative native configuration")
    policy = prelaunch["endpoint_policy"]
    _require(
        value["endpoints"] == {k: policy[k] for k in ("family", "host", "game_port", "admin_port")},
        "Native runtime sealed endpoint mismatch",
    )
    grant = records["authorization-consumed"]
    _require(
        value["owner"] == {"pid": grant["owner_pid"], "start": grant["owner_start"]}
        and value["launch_argv_sha256"] == argv_digest(runtime["argv"])
        and value["configuration_sha256"] == configs[0]["sha256"]
        and value["executable_sha256"] == runtime["executable"]["sha256"]
        and value["bridge_sha256"] == runtime["bridge_sha256"]
        and value["process_instances"] == (0 if value["child"] is None else 1),
        "Native runtime identity mismatch",
    )


def _authentication(prelaunch: dict, records: dict, successful: bool) -> None:
    value = _observation(records, "authentication")
    if not value["available"]:
        _require(not successful, "Native authentication unavailable")
        return
    runtime = _observation(records, "runtime")
    endpoint = prelaunch["endpoint_policy"]
    _require(
        value["process"] == runtime["child"] and value["endpoints"] == runtime["endpoints"],
        "Native session identity mismatch",
    )
    _require(
        value["public_key"] == endpoint["client_public_key"]
        and value["public_key_sha256"] == endpoint["client_public_key_sha256"],
        "Native public key mismatch",
    )
    order = [("outbound", 9), ("inbound", 128), ("outbound", 10), ("inbound", 129)]
    handshake = value["handshake"]
    _require(
        len(handshake) <= 4
        and [(f["direction"], f["packet_type"]) for f in handshake] == order[: len(handshake)]
        and [f["ordinal"] for f in handshake] == list(range(1, len(handshake) + 1)),
        "Native handshake ordering mismatch",
    )
    states = value["states"]
    expected_states = [
        "CONNECTED",
        "AUTH_JOIN_SENT",
        "AUTH_REQUEST_RECEIVED",
        "AUTH_RESPONSE_SENT",
        "ENCRYPTION_ENABLED",
        "PROTOCOL_RECEIVED",
        "WELCOME_RECEIVED",
        "ACTIVE",
    ]
    _require(
        [e["ordinal"] for e in states] == list(range(1, len(states) + 1))
        and [e["state"] for e in states] == expected_states[: len(states)]
        and [e["time_ns"] for e in states] == sorted(e["time_ns"] for e in states),
        "Native authentication state mismatch",
    )
    if successful:
        _require(
            value["state"] == "ACTIVE"
            and value["encrypted"] is True
            and value["method"] == "X25519_AuthorizedKey"
            and len(handshake) == 4
            and len(states) == 8
            and value["protocol"] is not None
            and value["welcome"] is not None,
            "Native authenticated runtime mismatch",
        )
        welcome = value["welcome"]
        context, recipe = prelaunch["context"], prelaunch["source"]["recipe"]
        expected = dict(
            revision="15.3",
            dedicated=True,
            width=context["map_width"],
            height=context["map_height"],
            seed=recipe["seed"],
            landscape=recipe["landscape"],
            start_date=recipe["start_date"],
        )
        _require(all(welcome[k] == v for k, v in expected.items()), "Native welcome mismatch")


def _cleanup(prelaunch: dict, records: dict, successful: bool) -> None:
    raw = _observation(records, "cleanup.raw")
    summary = _observation(records, "cleanup")
    if not successful:
        if raw["available"] and summary["available"]:
            _require(
                raw["cleanup"] == summary["cleanup"]
                and raw["completed_ns"] == summary["completed_ns"],
                "Native failure cleanup contradiction",
            )
            verification = summary["endpoints"]["endpoint_verification"]
            _require(
                summary["endpoints"]["sockets_closed"] is (verification is not None),
                "Native failure endpoint summary contradiction",
            )
            if verification is not None:
                policy = prelaunch["endpoint_policy"]
                verify_retained_endpoints(
                    verification,
                    {
                        "game_port": policy["game_port"],
                        "admin_port": policy["admin_port"],
                        "endpoints": [policy["game_port"], policy["admin_port"]],
                    },
                )
        return
    _require(raw["available"] and summary["available"], "Native cleanup unavailable")
    totals = _observation(records, "frame-accounting")["totals"]
    verify_cleanup_records(
        raw["cleanup"],
        {"cleanup": summary["cleanup"], "endpoints": summary["endpoints"]},
        "REAL",
        totals,
    )
    _require(
        raw["completed_ns"] == summary["completed_ns"]
        and summary["endpoints"]["sockets_closed"] is True,
        "Native cleanup phase mismatch",
    )
    policy = prelaunch["endpoint_policy"]
    metadata = dict(
        game_port=policy["game_port"],
        admin_port=policy["admin_port"],
        endpoints=[policy["game_port"], policy["admin_port"]],
    )
    verify_retained_endpoints(summary["endpoints"]["endpoint_verification"], metadata)
    disposal = _observation(records, "credential-disposal")
    _require(
        disposal["available"]
        and disposal["workspace_disposed"]
        and disposal["retained_secret_count"] == 0
        and all(
            d["removed"] and d["observed_ns"] >= raw["completed_ns"]
            for d in disposal["materializations"]
        ),
        "Native credential disposal mismatch",
    )
    integrity = _observation(records, "post-run-integrity")
    _require(
        integrity["available"]
        and integrity["workspace_disposed"]
        and not integrity["history"]["missing"]
        and not integrity["history"]["changed"],
        "Native historical integrity mismatch",
    )
    for check in integrity["before_disposal"]:
        if check["phase"] == "final_pre_popen" or check["phase"] == "post_run":
            _require(
                check["outcome"] == "MATCH"
                and check["observed_sha256"] == check["expected_sha256"],
                "Native source integrity mismatch",
            )


def _pages(records: dict, content: dict[str, bytes], pair: VerifiedTerrainPair) -> None:
    frames = _observation(records, "frame-accounting")
    log = _observation(records, "execution-log")
    _require(frames["available"] and log["available"], "Native exchange evidence unavailable")
    expected = [
        (s, p, ex)
        for s, dataset in enumerate(pair.sweeps, 1)
        for p, ex in enumerate(dataset.exchanges, 1)
    ]
    _require(
        len(frames["page_deltas"]) == len(expected) == len(log["pages"]),
        "Native page evidence coverage mismatch",
    )
    stderr = content["stderr.log"]
    for stream in ("stdout", "stderr"):
        final = log["final"][stream]
        data = content[stream + ".log"]
        _require(
            final["artifact"] == stream + ".log"
            and final["byte_length"] == len(data)
            and final["sha256"] == _digest(data),
            "Native final log mismatch",
        )
    last_end = 0
    global_ids = []
    for (sweep, page, exchange), delta, record in zip(
        expected, frames["page_deltas"], log["pages"], strict=True
    ):
        request_id = TileFactsRequest.parse(exchange.request_payload).request_id
        for v in (delta, record):
            _require(
                (v["sweep"], v["page"], v["request_id"]) == (sweep, page, request_id),
                "Native page identity mismatch",
            )
        _require(
            delta["admitted"]
            and delta["request_bytes"] == len(exchange.request_payload)
            and delta["response_bytes"] == len(exchange.response_payload)
            and delta["query_operations"] == exchange.protocol_operations
            and delta["request_sha256"] == _digest(exchange.request_payload)
            and delta["response_sha256"] == _digest(exchange.response_payload),
            "Native page accounting mismatch",
        )
        selected = frames["frames"][delta["first_frame"] - 1 : delta["last_frame"]]
        _require(
            len(selected) == 4
            and [(f["direction"], f["packet_type"]) for f in selected]
            == [("outbound", 6), ("inbound", 124), ("outbound", 7), ("inbound", 126)]
            and all(
                f["request_id"] == request_id and f["phase"] == "sweep" + str(sweep)
                for f in selected
            ),
            "Native query frame mismatch",
        )
        scope = record["snapshot"]
        end = scope["end_offset"]
        _require(
            scope["artifact"] == "stderr.log"
            and scope["start_offset"] == 0
            and last_end < end <= len(stderr)
            and scope["byte_length"] == end
            and scope["sha256"] == _digest(stderr[:end]),
            "Native snapshot scope mismatch",
        )
        parse_tile_facts_evidence(stderr[:end], request_id).require_complete(exchange)
        _require(
            tuple(m["marker"] for m in record["markers"]) == GS_SEQUENCE,
            "Native marker identity mismatch",
        )
        marker_end = last_end
        for marker in record["markers"]:
            start, stop = marker["start_offset"], marker["end_offset"]
            _require(marker_end <= start < stop <= end, "Native marker range mismatch")
            text = stderr[start:stop].decode("utf-8").rstrip("\r\n")
            parsed = MARKER.fullmatch(text)
            _require(
                parsed is not None
                and parsed.group(1) == marker["marker"]
                and parsed.group(2) == request_id,
                "Native marker correlation mismatch",
            )
            marker_end = stop
        last_end = end
        global_ids += [request_id] * 4
    actual_ids = [
        m.group(2) for line in stderr.decode("utf-8").splitlines() if (m := MARKER.fullmatch(line))
    ]
    _require(
        actual_ids == global_ids
        and log["pending"] is None
        and frames["pending"] is None
        and frames["rejected"] is None,
        "Native global log correlation mismatch",
    )


def _lifecycle(prelaunch: dict, records: dict, pair: VerifiedTerrainPair | None) -> None:
    value = _observation(records, "lifecycle")
    _require(value["available"], "Native lifecycle unavailable")
    events = value["events"]
    _require(
        [e["ordinal"] for e in events] == list(range(1, len(events) + 1))
        and [e["time_ns"] for e in events] == sorted(e["time_ns"] for e in events),
        "Native lifecycle ordering mismatch",
    )
    names = [e["event"] for e in events]
    initial = [
        "prepared",
        "sealed",
        "authorized",
        "claimed",
        "invocation_recorded",
        "launched",
        "connected",
        "subscribed",
    ]
    if pair is None:
        before_rejection = names[: names.index("rejected")] if "rejected" in names else names
        _require(
            before_rejection[: len(initial)] == initial[: len(before_rejection[: len(initial)])]
            and "rejected" in names
            and "cleanup_started" in names
            and names[-1] == "finalized",
            "Native terminal failure lifecycle mismatch",
        )
        return
    expected = initial.copy()
    for dataset in pair.sweeps:
        expected += ["sweep_started"]
        for _ in dataset.exchanges:
            expected += ["request_sent", "response_received", "page_admitted"]
        expected += ["sweep_completed"]
    expected += ["pair_verified", "cleanup_started", "cleaned", "finalized"]
    _require(
        names == expected and value["failure"] is None and value["cleanup_errors"] == [],
        "Native lifecycle transition mismatch",
    )
    expected_pages = [
        (s, p, TileFactsRequest.parse(ex.request_payload).request_id)
        for s, dataset in enumerate(pair.sweeps, 1)
        for p, ex in enumerate(dataset.exchanges, 1)
        for _ in range(3)
    ]
    actual_pages = [
        (e["sweep"], e["page"], e["request_id"])
        for e in events
        if e["event"] in ("request_sent", "response_received", "page_admitted")
    ]
    _require(actual_pages == expected_pages, "Native lifecycle page correlation mismatch")
    runtime = _observation(records, "runtime")
    _require(
        runtime["launched_ns"] == next(e["time_ns"] for e in events if e["event"] == "launched")
        and runtime["launched_ns"] <= runtime["exited_ns"] <= runtime["reaped_ns"],
        "Native process time mismatch",
    )
    cleanup = _observation(records, "cleanup.raw")
    _require(
        runtime["reaped_ns"] <= cleanup["completed_ns"] <= events[-1]["time_ns"],
        "Native cleanup ordering mismatch",
    )
    _require(
        events[-1]["time_ns"]
        <= prelaunch["resources"]["acquisition_ns"]
        + prelaunch["resources"]["cleanup_ns"]
        + prelaunch["resources"]["finalization_ns"],
        "Native lifecycle deadline exceeded",
    )


def _accounting(prelaunch: dict, records: dict, pair: VerifiedTerrainPair | None) -> None:
    value = _observation(records, "frame-accounting")
    if not value["available"]:
        _require(pair is None, "Native accounting unavailable")
        return
    frames, totals = value["frames"], value["totals"]
    auth = _observation(records, "authentication")
    handshake = len(auth["handshake"]) if auth["available"] else 0
    _require(
        [f["ordinal"] for f in frames] == list(range(1, len(frames) + 1)),
        "Native frame ordinal mismatch",
    )
    _require(
        totals["handshake"] == totals["pre_auth_frames"] == handshake
        and totals["post_auth_frames"] == len(frames),
        "Native handshake accounting mismatch",
    )
    for phase in ("establishment", "setup", "sweep1", "sweep2", "cleanup"):
        _require(
            totals[phase] == sum(f["phase"] == phase for f in frames),
            "Native frame phase accounting mismatch",
        )
    for direction, name in (
        ("inbound", "inbound_stream_bytes"),
        ("outbound", "outbound_stream_bytes"),
    ):
        _require(
            totals[name]
            == sum(f["encoded_byte_length"] for f in frames if f["direction"] == direction),
            "Native stream accounting mismatch",
        )
    caps = prelaunch["budgets"]["frames"]
    if auth["available"]:
        _require(
            sum(f["encoded_byte_length"] for f in auth["handshake"])
            <= caps["pre_auth_stream_bytes"]
            and all(f["encoded_byte_length"] <= 32767 for f in auth["handshake"]),
            "Native pre-auth stream budget exceeded",
        )
    _require(
        totals["post_auth_frames"] <= caps["post_auth_frames"]
        and handshake <= caps["pre_auth_frames"]
        and totals["inbound_stream_bytes"] + totals["outbound_stream_bytes"]
        <= caps["post_auth_stream_bytes"]
        and all(f["plaintext_byte_length"] <= 32767 for f in frames),
        "Native frame budget exceeded",
    )
    if pair is not None:
        meta = pair.metadata
        _require(
            totals["query_operations"] == meta["query_operations"]
            and totals["request_bytes"] == meta["request_bytes"]
            and totals["response_bytes"] == meta["response_bytes"]
            and (totals["establishment"], totals["setup"], totals["cleanup"]) == (2, 3, 1),
            "Native aggregate accounting mismatch",
        )
        allowed = {
            "establishment": [("inbound", 103), ("inbound", 104)],
            "setup": [("outbound", 2), ("outbound", 7), ("inbound", 126)],
            "cleanup": [("outbound", 1)],
        }
        for phase, sequence in allowed.items():
            _require(
                [(f["direction"], f["packet_type"]) for f in frames if f["phase"] == phase]
                == sequence,
                "Native control frame mismatch",
            )


def _result_outcomes(
    prelaunch: dict, records: dict, content: dict[str, bytes], pair: VerifiedTerrainPair | None
) -> dict[str, bool]:
    """Derive gate values after structural, relational and byte validation."""
    _, checks = native_binding_requirements(prelaunch, content)
    integrity = _observation(records, "post-run-integrity")
    entries = integrity["before_disposal"] if integrity["available"] else []

    def phase_matches(phase: str) -> bool:
        expected = [k for k in checks if k[0] == phase]
        actual = [e for e in entries if e["phase"] == phase]
        return len(actual) == len(expected) and all(e["outcome"] == "MATCH" for e in actual)

    disposal = _observation(records, "credential-disposal")
    raw = _observation(records, "cleanup.raw")
    summary = _observation(records, "cleanup")
    runtime = _observation(records, "runtime")
    cleanup = False
    if raw["available"] and summary["available"]:
        value = raw["cleanup"]
        child = runtime["child"] if runtime["available"] else None
        _require(
            value["pid"] == (child["pid"] if child is not None else None),
            "Native cleanup process identity mismatch",
        )
        if child is None:
            _require(value["returncode"] is None, "Native no-child cleanup returncode mismatch")
        else:
            _require(
                value["reaped"] is (value["returncode"] is not None),
                "Native cleanup reaping contradiction",
            )
        cleanup = (
            value["reaped"]
            and not value["remaining_processes"]
            and not value["cleanup_error"]
            and summary["endpoints"]["sockets_closed"]
            and summary["endpoints"]["endpoint_verification"] is not None
        )
        life = _observation(records, "lifecycle")
        times = {e["event"]: e["time_ns"] for e in life["events"]}
        _require(
            times["cleanup_started"] <= raw["completed_ns"] <= times["finalized"],
            "Native failure cleanup ordering mismatch",
        )
    auth = _observation(records, "authentication")
    authenticated = auth["available"] and auth["state"] == "ACTIVE"
    log = _observation(records, "execution-log")
    if log["available"]:
        for stream in ("stdout", "stderr"):
            final = log["final"][stream]
            path = stream + ".log"
            _require(
                final["artifact"] == path
                and final["byte_length"] == len(content[path])
                and final["sha256"] == _digest(content[path]),
                "Native final log commitment mismatch",
            )
    return dict(
        authorization=True,
        source_integrity=phase_matches("final_pre_popen"),
        runtime_identity=runtime["available"],
        authentication=authenticated,
        coverage=pair is not None,
        equality=pair is not None,
        accounting=_observation(records, "frame-accounting")["available"],
        liveness=pair is not None,
        log_integrity=log["available"],
        cleanup=cleanup,
        credential_disposal=(
            disposal["available"]
            and disposal["workspace_disposed"]
            and disposal["retained_secret_count"] == 0
            and all(e["removed"] for e in disposal["materializations"])
        ),
        post_run_integrity=(
            integrity["available"]
            and phase_matches("post_run")
            and integrity["workspace_disposed"]
            and not integrity["history"]["missing"]
            and not integrity["history"]["changed"]
        ),
    )


def validate_observations(
    prelaunch: dict,
    records: dict,
    content: dict[str, bytes],
    paired_result: VerifiedTerrainPair | None,
) -> Literal["CONTROLLED_CONTRACT_ACCEPTED", "CONTROLLED_CONTRACT_FAILURE_RETAINED"]:
    """Validate REAL-shaped local records; return CONTROLLED only, never authorize launch."""
    result = _observation(records, "result")
    _require(result["available"], "Native result unavailable")
    successful = result["status"] == "REAL_PASS"
    _lineage(prelaunch, records, content)
    _runtime(prelaunch, records)
    _authentication(prelaunch, records, successful)
    _accounting(prelaunch, records, paired_result)
    _lifecycle(prelaunch, records, paired_result)
    _bindings(prelaunch, records, content, successful)
    _cleanup(prelaunch, records, successful)
    outcomes = _result_outcomes(prelaunch, records, content, paired_result)
    _require(result["gates"] == outcomes, "Native result gate contradiction")
    if successful:
        _require(paired_result is not None, "Native paired evidence unavailable")
        if paired_result is not None:
            paired_result.verify()
            _pages(records, content, paired_result)
        _require(
            result["failure"] is None and all(result["gates"].values()),
            "Native result gate contradiction",
        )
        return "CONTROLLED_CONTRACT_ACCEPTED"
    _require(
        result["failure"] is not None and not all(result["gates"].values()),
        "Native failure gate contradiction",
    )
    return "CONTROLLED_CONTRACT_FAILURE_RETAINED"
