"""CONTROLLED validation of REAL-shaped records never grants native permission."""

import pytest

from app.simulation.openttd.terrain_native_paired_evidence import (
    ControlledNativeContractResult,
    verify_native_paired_package,
)
from tests.test_terrain_single_page_preparation import candidate as candidate


def test_independent_commitments_required_before_package_read(tmp_path):
    with pytest.raises(ValueError, match="commitment"):
        verify_native_paired_package(
            tmp_path / "missing",
            expected_prelaunch_sha256="",
            expected_completion_sha256="0" * 64,
            immutable_authorities={},
        )


@pytest.mark.parametrize(
    "status", ["CONTROLLED_CONTRACT_ACCEPTED", "CONTROLLED_CONTRACT_FAILURE_RETAINED"]
)
def test_exact_controlled_status_vocabulary(status):
    construct = getattr(ControlledNativeContractResult, "__call__")
    result = construct(status, "0" * 64, "1" * 64, None)
    assert result.status == status
    assert result.status != "REAL_PASS"


@pytest.mark.parametrize("status", ["REAL_PASS", "CONTROLLED_PASS", "", "unknown"])
def test_untrusted_status_cannot_construct_controlled_result(status):
    construct = getattr(ControlledNativeContractResult, "__call__")
    with pytest.raises(ValueError, match="controlled contract status"):
        construct(status, "0" * 64, "1" * 64, None)


def complete_native_fixture(candidate, tmp_path):
    """Public writer inputs assembled from deterministic locally attested observations.

    There is no process launch, socket, operator grant or native authentication.
    The REAL-shaped wire vocabulary is test data for CONTROLLED validation only.
    """
    import hashlib
    import json
    from dataclasses import asdict

    from app.simulation.openttd.proof.endpoints import endpoint_cleanup_contract
    from app.simulation.openttd.terrain_native_paired_evidence import _manifest, _plan
    from app.simulation.openttd.terrain_native_records import GATES, encode, parse_prelaunch
    from app.simulation.openttd.terrain_native_validation import (
        argv_digest,
        native_binding_requirements,
    )
    from app.simulation.openttd.terrain_pagination import PaginationBudget
    from app.simulation.openttd.terrain_paired_evidence import write_paired_package
    from app.simulation.openttd.terrain_sweeps import TerrainTwoSweep, TwoSweepBudget
    from app.simulation.openttd.tile_facts import TileFactsRequest
    from app.simulation.openttd.tile_facts_evidence import GS_SEQUENCE
    from tests.test_terrain_native_records import prelaunch_wire
    from tests.test_terrain_native_retention import native_provenance_fixture
    from tests.test_terrain_sweeps import collect, context

    def sha(raw):
        return hashlib.sha256(raw).hexdigest()

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    destination = tmp_path / "outer"
    content, authority, histories = native_provenance_fixture(
        candidate, tmp_path / "seal", destination
    )
    prelaunch = prelaunch_wire()
    prelaunch["attempt"] = dict(
        identity="fixture", destination=str(destination), seal_destination=str(tmp_path / "seal")
    )
    prelaunch["runtime"].update(authority["runtime"])
    prelaunch["runtime"]["bridge_sha256"] = candidate.record["bridge_digest"]
    prelaunch["source"].update(authority["source"])
    recipe = dict(map_x=6, map_y=6, seed=42, landscape=0, start_date=730000)
    prelaunch["source"].update(recipe=recipe, recipe_sha256=sha(canonical(recipe)))
    prelaunch["external_authorities"][0].update(authority["external_authorities"][0])
    c = context()
    prelaunch["context"] = dict(
        acquisition_id=c.acquisition_id,
        world_fingerprint=c.world_fingerprint,
        map_width=c.map_width,
        map_height=c.map_height,
        region=c.region.model_dump(mode="json"),
    )
    pair = TerrainTwoSweep(c)
    collect(pair, c, 1)
    collect(pair, c, 2)
    accepted_pair = pair.finish()
    paired = tmp_path / "paired"
    write_paired_package(accepted_pair, paired)
    content.update(
        {
            "paired/" + p.relative_to(paired).as_posix(): p.read_bytes()
            for p in paired.rglob("*")
            if p.is_file()
        }
    )
    prelaunch["budgets"] = dict(
        per_sweep=asdict(PaginationBudget()),
        combined=asdict(TwoSweepBudget()),
        frames=dict(
            post_auth_frames=38,
            pre_auth_frames=4,
            post_auth_stream_bytes=38 * 32767,
            pre_auth_stream_bytes=4 * 32767,
        ),
    )
    endpoints = dict(
        family="AF_INET",
        host="127.0.0.1",
        game_port=candidate.record["endpoints"][0],
        admin_port=candidate.record["endpoints"][1],
    )
    public = candidate.record["public_key"]
    prelaunch["endpoint_policy"] = dict(
        **endpoints,
        policy=endpoint_cleanup_contract(),
        client_public_key=public,
        client_public_key_sha256=sha(bytes.fromhex(public)),
    )
    prelaunch["resources"].update(
        {
            k: 1000000
            for k in prelaunch["resources"]
            if k not in ("admission_evidence", "outer_files")
        }
    )
    prelaunch["resources"].update(stdout_bytes=262144, stderr_bytes=262144, paired_bytes=1048576)
    content["seal/page-plan.json"] = canonical(_plan(prelaunch))

    def commitment(p):
        return dict(path=p, byte_length=len(content[p]), sha256=sha(content[p]))

    prelaunch["plan"] = commitment("seal/page-plan.json")
    prelaunch["resources"]["admission_evidence"] = [commitment("seal/page-plan.json")]
    prelaunch["commitments"] = [commitment(p) for p in sorted(content) if p.startswith("seal/")]
    # Common fixed outputs, claims, sealed inputs, and the exact existing paired tree.
    from app.simulation.openttd.terrain_native_paired_evidence import COMMON

    prelaunch["resources"]["outer_files"] = len(
        set(COMMON) | set(content) | {"launch-claim.json", "native-launch-claimed.json"}
    )
    content["seal/PRELAUNCH.json"] = encode(parse_prelaunch(canonical(prelaunch)))
    pin = sha(content["seal/PRELAUNCH.json"])
    content["seal/SEAL.sha256"] = (pin + "\n").encode()
    content["seal/artifact-manifest.sha256"] = _manifest(
        {p[5:]: raw for p, raw in content.items() if p.startswith("seal/")}
    )
    grant = dict(
        schema="terrain-native-paired-local-grant-v1",
        version=1,
        authorization_mode="OPERATOR_ATTENDED_LOCAL_PROOF",
        trust="LOCAL_OPERATOR_ATTESTED",
        proof_operation=prelaunch["operation"],
        seal_sha256=pin,
        attempt_identity="fixture",
        attempt_directory=str(destination),
        owner_pid=10,
        owner_start="123",
        owner_nonce="1" * 32,
        launch_allowance=1,
        connection_allowance=1,
        request_allowance=4,
        no_retry=True,
        no_reconnect=True,
        no_relaunch=True,
        no_resume=True,
        state="STARTED",
    )
    content["authorization-consumed.json"] = canonical(grant)
    claim = {
        k: grant[k]
        for k in (
            "attempt_identity",
            "attempt_directory",
            "seal_sha256",
            "owner_pid",
            "owner_start",
            "owner_nonce",
            "no_retry",
        )
    }
    claim.update(
        schema=prelaunch["artifact_policy"]["schema"],
        version=1,
        mode="REAL",
        consumed_record_sha256=sha(content["authorization-consumed.json"]),
    )
    content["launch-claim.json"] = canonical(claim)
    invocation = dict(
        claim, launch_claim_sha256=sha(content["launch-claim.json"]), launch_invocations=1
    )
    content["native-launch-claimed.json"] = canonical(invocation)

    def record(kind, observations):
        content[kind + ".json"] = canonical(
            dict(
                schema=prelaunch["artifact_policy"]["schema"],
                version=1,
                kind=kind,
                attempt_identity="fixture",
                prelaunch_sha256=pin,
                observations=dict(available=True, **observations),
            )
        )

    events = []

    def event(name, phase, sweep=None, page=None, request_id=None):
        events.append(
            dict(
                ordinal=len(events) + 1,
                phase=phase,
                event=name,
                time_ns=(len(events) + 1) * 10,
                session_id="session-1"
                if name
                not in (
                    "prepared",
                    "sealed",
                    "authorized",
                    "claimed",
                    "invocation_recorded",
                    "launched",
                )
                else None,
                sweep=sweep,
                page=page,
                request_id=request_id,
            )
        )

    for name, phase in (
        ("prepared", "PREPARED"),
        ("sealed", "SEALED_UNAUTHORIZED"),
        ("authorized", "AUTHORIZED"),
        ("claimed", "CLAIMED"),
        ("invocation_recorded", "INVOCATION_RECORDED"),
        ("launched", "LAUNCHED"),
        ("connected", "CONNECTED"),
        ("subscribed", "CONNECTED"),
    ):
        event(name, phase)
    frames, deltas, log_pages = [], [], []
    stderr = b""

    def frame(direction, kind, phase, request_id=None):
        frames.append(
            dict(
                ordinal=len(frames) + 1,
                direction=direction,
                phase=phase,
                session_id="session-1",
                request_id=request_id,
                packet_type=kind,
                plaintext_byte_length=5,
                encoded_byte_length=21,
                plaintext_sha256=sha(b"frame"),
                encoded_sha256=sha(b"simulated-frame"),
            )
        )

    for direction, kind in (("inbound", 103), ("inbound", 104)):
        frame(direction, kind, "establishment")
    for direction, kind in (("outbound", 2), ("outbound", 7), ("inbound", 126)):
        frame(direction, kind, "setup")
    for sweep, dataset in enumerate(accepted_pair.sweeps, 1):
        phase = "SWEEP_" + str(sweep)
        event("sweep_started", phase, sweep)
        for page, exchange in enumerate(dataset.exchanges, 1):
            request_id = TileFactsRequest.parse(exchange.request_payload).request_id
            for name in ("request_sent", "response_received", "page_admitted"):
                event(name, phase, sweep, page, request_id)
            first = len(frames) + 1
            for direction, kind in (
                ("outbound", 6),
                ("inbound", 124),
                ("outbound", 7),
                ("inbound", 126),
            ):
                frame(direction, kind, "sweep" + str(sweep), request_id)
            deltas.append(
                dict(
                    sweep=sweep,
                    page=page,
                    request_id=request_id,
                    first_frame=first,
                    last_frame=len(frames),
                    admitted=True,
                    request_bytes=len(exchange.request_payload),
                    response_bytes=len(exchange.response_payload),
                    query_operations=exchange.protocol_operations,
                    request_sha256=sha(exchange.request_payload),
                    response_sha256=sha(exchange.response_payload),
                )
            )
            suffixes = (
                " type=tile_facts_page protocol=1",
                " response_json=" + exchange.response_payload.decode(),
                " type=tile_facts_page_result status=ok protocol=1",
                "",
            )
            markers = []
            for marker, suffix in zip(GS_SEQUENCE, suffixes, strict=True):
                start = len(stderr)
                stderr += (
                    "dbg: [script:4] [18] [I] "
                    + marker
                    + " request_id="
                    + request_id
                    + suffix
                    + "\n"
                ).encode()
                markers.append(dict(marker=marker, start_offset=start, end_offset=len(stderr)))
            path = f"paired/pages/s{sweep}/p{page:03d}/"
            log_pages.append(
                dict(
                    sweep=sweep,
                    page=page,
                    request_id=request_id,
                    request_artifact=path + "request.json",
                    response_artifact=path + "response.json",
                    exchange_artifact=path + "exchange.json",
                    response_sha256=sha(exchange.response_payload),
                    snapshot=dict(
                        artifact="stderr.log",
                        start_offset=0,
                        end_offset=len(stderr),
                        byte_length=len(stderr),
                        sha256=sha(stderr),
                    ),
                    markers=markers,
                )
            )
        event("sweep_completed", phase, sweep)
    event("pair_verified", "VERIFIED")
    event("cleanup_started", "CLEANING")
    cleanup_started = events[-1]["time_ns"]
    frame("outbound", 1, "cleanup")
    event("cleaned", "CLEANED")
    completed = events[-1]["time_ns"]
    event("finalized", "FINALIZED")
    record("lifecycle", dict(events=events, failure=None, cleanup_errors=[]))
    metadata = accepted_pair.metadata
    totals = {
        phase: sum(f["phase"] == phase for f in frames)
        for phase in ("establishment", "setup", "sweep1", "sweep2", "cleanup")
    }
    totals.update(
        handshake=4,
        pre_auth_frames=4,
        post_auth_frames=len(frames),
        query_operations=metadata["query_operations"],
        request_bytes=metadata["request_bytes"],
        response_bytes=metadata["response_bytes"],
        inbound_stream_bytes=sum(
            f["encoded_byte_length"] for f in frames if f["direction"] == "inbound"
        ),
        outbound_stream_bytes=sum(
            f["encoded_byte_length"] for f in frames if f["direction"] == "outbound"
        ),
    )
    record(
        "frame-accounting",
        dict(frames=frames, page_deltas=deltas, totals=totals, rejected=None, pending=None),
    )
    process = dict(pid=20, start="456")
    record(
        "runtime",
        dict(
            owner=dict(pid=10, start="123"),
            child=process,
            launch_argv_sha256=argv_digest(prelaunch["runtime"]["argv"]),
            configuration_sha256=candidate.record["configuration_digest"],
            bridge_sha256=candidate.record["bridge_digest"],
            executable_sha256=candidate.record["executable_digest"],
            process_instances=1,
            network_namespace="controlled-namespace",
            endpoints=endpoints,
            launched_ns=60,
            exited_ns=cleanup_started - 2,
            reaped_ns=completed - 1,
        ),
    )
    auth_states = (
        "CONNECTED",
        "AUTH_JOIN_SENT",
        "AUTH_REQUEST_RECEIVED",
        "AUTH_RESPONSE_SENT",
        "ENCRYPTION_ENABLED",
        "PROTOCOL_RECEIVED",
        "WELCOME_RECEIVED",
        "ACTIVE",
    )
    handshake = [
        dict(
            ordinal=i,
            direction=direction,
            packet_type=kind,
            encoded_byte_length=5,
            encoded_sha256=sha(b"synthetic-handshake"),
            state=auth_states[i],
        )
        for i, (direction, kind) in enumerate(
            (("outbound", 9), ("inbound", 128), ("outbound", 10), ("inbound", 129)), 1
        )
    ]
    record(
        "authentication",
        dict(
            session_id="session-1",
            process=process,
            endpoints=endpoints,
            public_key=public,
            public_key_sha256=sha(bytes.fromhex(public)),
            method="X25519_AuthorizedKey",
            encrypted=True,
            state="ACTIVE",
            states=[
                dict(ordinal=i, state=state, time_ns=60 + i)
                for i, state in enumerate(auth_states, 1)
            ],
            protocol=dict(version=3, frequencies=[]),
            welcome=dict(
                revision="15.3",
                dedicated=True,
                width=64,
                height=64,
                seed=42,
                landscape=0,
                start_date=730000,
            ),
            handshake=handshake,
        ),
    )
    stderr += b"controlled disconnect and shutdown\n"
    content["stderr.log"], content["stdout.log"] = stderr, b""
    record(
        "execution-log",
        dict(
            policy="terrain-execution-log-multi-page-v1",
            pages=log_pages,
            pending=None,
            final={
                name: dict(
                    artifact=name + ".log",
                    byte_length=len(content[name + ".log"]),
                    sha256=sha(content[name + ".log"]),
                )
                for name in ("stdout", "stderr")
            },
        ),
    )
    cleanup = dict(
        pid=20,
        graceful_attempted=True,
        quit_command="quit",
        returncode=0,
        reaped=True,
        remaining_processes=[],
        events=["quit", "reaped"],
        cleanup_error=[],
        admin_frame_accounting=totals,
    )
    record("cleanup.raw", dict(cleanup=cleanup, completed_ns=completed))
    endpoint = dict(
        **endpoints,
        policy="linux-kernel-endpoint-closure-v1",
        process_reaped=True,
        reservation_released=True,
        listener_closed=True,
        connection_closed=True,
        kernel_states=[],
        immediate_rebindability_required=False,
        connection_probe=False,
    )
    record(
        "cleanup",
        dict(
            cleanup=cleanup,
            completed_ns=completed,
            endpoints=dict(sockets_closed=True, endpoint_verification=endpoint),
        ),
    )
    disposal, checks = native_binding_requirements(prelaunch, content)
    record(
        "credential-disposal",
        dict(
            materializations=[
                dict(
                    identity=identity, commitment_sha256=digest, removed=True, observed_ns=completed
                )
                for identity, digest in disposal.items()
            ],
            workspace_disposed=True,
            retained_secret_count=0,
        ),
    )
    inventory = json.loads(content["seal/historical-integrity.json"])
    history = prelaunch["external_authorities"][0]
    record(
        "post-run-integrity",
        dict(
            before_disposal=[
                dict(
                    identity=identity,
                    phase=phase,
                    expected_sha256=digest,
                    observed_sha256=digest,
                    checked_ns=59 if phase == "final_pre_popen" else cleanup_started - 1,
                    outcome="MATCH",
                )
                for (phase, identity), digest in checks.items()
            ],
            history=dict(
                identity=history["identity"],
                inventory_sha256=history["inventory_sha256"],
                validated_paths=len(inventory["entries"]),
                missing=[],
                changed=[],
            ),
            workspace_disposed=True,
        ),
    )
    record(
        "result",
        dict(
            status="REAL_PASS",
            terminal_phase="ACCEPTED",
            failure=None,
            gates={gate: True for gate in GATES},
        ),
    )
    return destination, content, histories


def test_complete_controlled_native_package(candidate, tmp_path):
    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)
    pins = write_native_paired_package(
        directory, content=content, immutable_authorities=authorities
    )
    result = verify_native_paired_package(
        directory,
        expected_prelaunch_sha256=pins.prelaunch_sha256,
        expected_completion_sha256=pins.completion_sha256,
        immutable_authorities=authorities,
    )
    assert result.status == "CONTROLLED_CONTRACT_ACCEPTED"
    assert result.pair is not None
    assert result.pair.metadata["pages"] == 4


def test_coordinated_runtime_authentication_cannot_replace_sealed_endpoint(candidate, tmp_path):
    import json

    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)
    for name in ("runtime.json", "authentication.json"):
        value = json.loads(content[name])
        value["observations"]["endpoints"].update(game_port=41000, admin_port=41001)
        content[name] = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ValueError, match="endpoint"):
        write_native_paired_package(directory, content=content, immutable_authorities=authorities)


def test_pre_authentication_encoded_bytes_enforce_sealed_ceiling(candidate, tmp_path):
    import json

    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)
    value = json.loads(content["authentication.json"])
    value["observations"]["handshake"][0]["encoded_byte_length"] = 131069
    content["authentication.json"] = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode()
    with pytest.raises(ValueError, match="[Bb]udget|[Cc]eiling|[Bb]ytes"):
        write_native_paired_package(directory, content=content, immutable_authorities=authorities)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("missing-disposal", "disposal identity coverage"),
        ("substituted-disposal", "disposal identity coverage"),
        ("duplicate-disposal", "disposal identity coverage"),
        ("credential-commitment", "disposal commitment"),
        ("not-removed", "disposal observation"),
        ("missing-precheck", "integrity phase coverage"),
        ("missing-postcheck", "integrity phase coverage"),
        ("duplicate-check", "duplicate integrity"),
        ("wrong-check-identity", "integrity phase coverage"),
        ("wrong-check-digest", "integrity sealed commitment"),
        ("contradictory-check", "contradictory integrity"),
        ("invalid-grant", "grant lineage"),
        ("cleanup-failure", "cleanup evidence"),
        ("private-digest-field", "Extra inputs"),
    ],
)
def test_complete_package_rejects_substituted_local_records(
    candidate, tmp_path, mutation, expected
):
    import json

    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)
    name = (
        "credential-disposal.json"
        if mutation
        in (
            "missing-disposal",
            "substituted-disposal",
            "duplicate-disposal",
            "credential-commitment",
            "not-removed",
            "private-digest-field",
        )
        else "post-run-integrity.json"
    )
    if mutation == "invalid-grant":
        name = "authorization-consumed.json"
    elif mutation == "cleanup-failure":
        name = "cleanup.raw.json"
    value = json.loads(content[name])
    observations = value.get("observations", {})
    if mutation == "missing-disposal":
        observations["materializations"].pop()
    elif mutation == "substituted-disposal":
        observations["materializations"][0]["identity"] = "binding-" + "0" * 64
    elif mutation == "duplicate-disposal":
        observations["materializations"].append(observations["materializations"][0])
    elif mutation == "credential-commitment":
        # Change every public commitment, including the private-key lifecycle identity.
        for row in observations["materializations"]:
            row["commitment_sha256"] = "0" * 64
    elif mutation == "not-removed":
        observations["materializations"][0]["removed"] = False
    elif mutation in ("missing-precheck", "missing-postcheck"):
        phase = "final_pre_popen" if mutation == "missing-precheck" else "post_run"
        observations["before_disposal"] = [
            row for row in observations["before_disposal"] if row["phase"] != phase
        ]
    elif mutation == "duplicate-check":
        observations["before_disposal"].append(observations["before_disposal"][0])
    elif mutation == "wrong-check-identity":
        observations["before_disposal"][0]["identity"] = "binding-" + "0" * 64
    elif mutation == "wrong-check-digest":
        observations["before_disposal"][0]["expected_sha256"] = "0" * 64
        observations["before_disposal"][0]["observed_sha256"] = "0" * 64
    elif mutation == "contradictory-check":
        observations["before_disposal"][0]["outcome"] = "CHANGED"
    elif mutation == "invalid-grant":
        value["attempt_identity"] = "different-attempt"
    elif mutation == "cleanup-failure":
        observations["cleanup"]["reaped"] = False
    elif mutation == "private-digest-field":
        observations["materializations"][0]["private_key_sha256"] = "0" * 64
    content[name] = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    # Writer recomputes completion and manifests; mutable consistency confers no authority.
    with pytest.raises(ValueError, match=expected):
        write_native_paired_package(directory, content=content, immutable_authorities=authorities)


@pytest.mark.parametrize("mutation", ["unknown", "secret", "missing", "paired-response"])
def test_complete_package_inventory_and_bytes_reject(candidate, tmp_path, mutation):
    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)
    if mutation == "unknown":
        content["unknown.json"] = b"{}"
    elif mutation == "secret":
        content["private-key.bin"] = b"prohibited-secret-shaped-test-data"
    elif mutation == "missing":
        del content["runtime.json"]
    else:
        content["paired/pages/s1/p001/response.json"] += b"changed"
    with pytest.raises((ValueError, KeyError)):
        write_native_paired_package(directory, content=content, immutable_authorities=authorities)


def test_complete_package_cleanup_and_fresh_process(candidate, tmp_path):
    import json
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)
    pins = write_native_paired_package(
        directory, content=content, immutable_authorities=authorities
    )
    shutil.rmtree(candidate.directory)
    (tmp_path / "separate-cwd").mkdir()
    result = verify_native_paired_package(
        directory,
        expected_prelaunch_sha256=pins.prelaunch_sha256,
        expected_completion_sha256=pins.completion_sha256,
        immutable_authorities=authorities,
    )
    assert result.status == "CONTROLLED_CONTRACT_ACCEPTED"
    script = (
        "import json,sys; from pathlib import Path; "
        "from app.simulation.openttd.terrain_native_paired_evidence "
        "import verify_native_paired_package; "
        "v=verify_native_paired_package(Path(sys.argv[1]),"
        "expected_prelaunch_sha256=sys.argv[2],expected_completion_sha256=sys.argv[3],"
        "immutable_authorities={k:Path(v) for k,v in json.loads(sys.argv[4]).items()});"
        "print(v.status)"
    )
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(directory),
            pins.prelaunch_sha256,
            pins.completion_sha256,
            json.dumps({k: str(v) for k, v in authorities.items()}),
        ],
        cwd=tmp_path / "separate-cwd",
        env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])),
        capture_output=True,
        text=True,
        check=True,
    )
    assert child.stdout.strip() == "CONTROLLED_CONTRACT_ACCEPTED"


def test_completion_cannot_replace_independent_pin(candidate, tmp_path):
    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)
    pins = write_native_paired_package(
        directory, content=content, immutable_authorities=authorities
    )
    with pytest.raises(ValueError, match="Independently pinned descriptor"):
        verify_native_paired_package(
            directory,
            expected_prelaunch_sha256=pins.prelaunch_sha256,
            expected_completion_sha256="0" * 64,
            immutable_authorities=authorities,
        )


@pytest.mark.parametrize("field", ["launch_argv_sha256", "configuration_sha256"])
def test_complete_package_runtime_commitments_cannot_be_substituted(candidate, tmp_path, field):
    import json

    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)
    value = json.loads(content["runtime.json"])
    value["observations"][field] = "0" * 64
    content["runtime.json"] = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ValueError, match="runtime identity"):
        write_native_paired_package(directory, content=content, immutable_authorities=authorities)


def test_complete_package_authorized_configuration_rewrite_is_disposable(candidate, tmp_path):
    from pathlib import Path

    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)
    # Only the owned runtime target changes. Retained original prelaunch cfg is untouched.
    argv = candidate.record["argv"]
    target = Path(argv[argv.index("-c") + 1])
    target.write_bytes(b"permitted post-launch configuration rewrite\n")
    pins = write_native_paired_package(
        directory, content=content, immutable_authorities=authorities
    )
    accepted = verify_native_paired_package(
        directory,
        expected_prelaunch_sha256=pins.prelaunch_sha256,
        expected_completion_sha256=pins.completion_sha256,
        immutable_authorities=authorities,
    )
    assert accepted.status == "CONTROLLED_CONTRACT_ACCEPTED"


def terminal_failure_fixture(candidate, tmp_path, *, handshake):
    """Retain the exact reached phase rather than fabricate completed pages."""
    import hashlib
    import json

    from app.simulation.openttd.terrain_native_paired_evidence import _manifest
    from app.simulation.openttd.terrain_native_records import GATES
    from app.simulation.openttd.terrain_native_validation import native_binding_requirements

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)

    def encode(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    def sha(raw):
        return hashlib.sha256(raw).hexdigest()

    prelaunch = json.loads(content["seal/PRELAUNCH.json"])
    paired_paths = [name for name in content if name.startswith("paired/")]
    for name in paired_paths:
        del content[name]
    lifecycle = json.loads(content["lifecycle.json"])
    observations = lifecycle["observations"]
    prefix = observations["events"][: 7 if handshake else 5]
    failure = dict(
        code="HANDSHAKE_FAILED" if handshake else "PRELAUNCH_VALIDATION_FAILED",
        phase="CONNECTED" if handshake else "INVOCATION_RECORDED",
        message="Deterministic synthetic failure",
        cause_type="ValueError",
    )
    for name, phase in (
        ("rejected", "REJECTED"),
        ("cleanup_started", "CLEANING"),
        ("finalized", "FAILED_CLEANED"),
    ):
        prefix.append(
            dict(
                ordinal=len(prefix) + 1,
                phase=phase,
                event=name,
                time_ns=(len(prefix) + 1) * 10,
                session_id=None,
                sweep=None,
                page=None,
                request_id=None,
            )
        )
    observations.update(events=prefix, failure=failure)
    content["lifecycle.json"] = encode(lifecycle)

    def update(name, value):
        record = json.loads(content[name + ".json"])
        record["observations"] = value
        content[name + ".json"] = encode(record)

    runtime = json.loads(content["runtime.json"])["observations"]
    if handshake:
        runtime.update(exited_ns=80, reaped_ns=85)
        auth = json.loads(content["authentication.json"])["observations"]
        auth.update(
            method=None,
            encrypted=False,
            state="AUTH_REQUEST_RECEIVED",
            states=auth["states"][:3],
            protocol=None,
            welcome=None,
            handshake=auth["handshake"][:2],
        )
    else:
        runtime.update(
            child=None, process_instances=0, launched_ns=None, exited_ns=None, reaped_ns=None
        )
        auth = dict(available=False, reason="NOT_CONNECTED", phase="INVOCATION_RECORDED")
    update("runtime", runtime)
    update("authentication", auth)
    totals = {
        name: 0
        for name in (
            "establishment",
            "setup",
            "sweep1",
            "sweep2",
            "cleanup",
            "handshake",
            "query_operations",
            "post_auth_frames",
            "pre_auth_frames",
            "request_bytes",
            "response_bytes",
            "inbound_stream_bytes",
            "outbound_stream_bytes",
        )
    }
    totals["handshake"] = totals["pre_auth_frames"] = 2 if handshake else 0
    update(
        "frame-accounting",
        dict(available=True, frames=[], page_deltas=[], totals=totals, rejected=None, pending=None),
    )
    content["stdout.log"] = content["stderr.log"] = b""
    update(
        "execution-log",
        dict(
            available=True,
            policy="terrain-execution-log-multi-page-v1",
            pages=[],
            pending=None,
            final={
                stream: dict(artifact=stream + ".log", byte_length=0, sha256=sha(b""))
                for stream in ("stdout", "stderr")
            },
        ),
    )
    completed = prefix[-1]["time_ns"] - 1
    cleanup = dict(
        pid=20 if handshake else None,
        graceful_attempted=handshake,
        quit_command="quit",
        returncode=0 if handshake else None,
        reaped=True,
        remaining_processes=[],
        events=["reaped"] if handshake else ["no-child-created"],
        cleanup_error=[],
        admin_frame_accounting=totals,
    )
    update("cleanup.raw", dict(available=True, cleanup=cleanup, completed_ns=completed))
    update(
        "cleanup",
        dict(
            available=True,
            cleanup=cleanup,
            completed_ns=completed,
            endpoints=json.loads(content["cleanup.json"])["observations"]["endpoints"],
        ),
    )
    update(
        "result",
        dict(
            available=True,
            status="REAL_FAIL",
            terminal_phase="FAILED_CLEANED",
            failure=failure,
            gates={
                gate: gate not in ("authentication", "coverage", "equality", "liveness")
                for gate in GATES
            },
        ),
    )
    # Freeze the selected phase's file count; all subsequent record hashes bind this new fixture.
    prelaunch["resources"]["outer_files"] -= len(paired_paths)
    content["seal/PRELAUNCH.json"] = encode(prelaunch)
    pin = sha(content["seal/PRELAUNCH.json"])
    content["seal/SEAL.sha256"] = (pin + "\n").encode()
    content["seal/artifact-manifest.sha256"] = _manifest(
        {p[5:]: raw for p, raw in content.items() if p.startswith("seal/")}
    )
    for name in (
        "runtime",
        "authentication",
        "frame-accounting",
        "lifecycle",
        "execution-log",
        "cleanup.raw",
        "cleanup",
        "credential-disposal",
        "post-run-integrity",
        "result",
    ):
        record = json.loads(content[name + ".json"])
        record["prelaunch_sha256"] = pin
        content[name + ".json"] = encode(record)
    grant = json.loads(content["authorization-consumed.json"])
    grant["seal_sha256"] = pin
    content["authorization-consumed.json"] = encode(grant)
    claim = json.loads(content["launch-claim.json"])
    claim.update(
        seal_sha256=pin, consumed_record_sha256=sha(content["authorization-consumed.json"])
    )
    content["launch-claim.json"] = encode(claim)
    invocation = json.loads(content["native-launch-claimed.json"])
    invocation.update(claim)
    invocation["launch_claim_sha256"] = sha(content["launch-claim.json"])
    content["native-launch-claimed.json"] = encode(invocation)
    disposal, checks = native_binding_requirements(prelaunch, content)
    row = json.loads(content["credential-disposal.json"])
    row["observations"]["materializations"] = [
        dict(identity=identity, commitment_sha256=digest, removed=True, observed_ns=completed)
        for identity, digest in disposal.items()
    ]
    content["credential-disposal.json"] = encode(row)
    integrity = json.loads(content["post-run-integrity.json"])
    cleanup_started = prefix[-2]["time_ns"]
    integrity["observations"]["before_disposal"] = [
        dict(
            identity=identity,
            phase=phase,
            expected_sha256=digest,
            observed_sha256=digest,
            checked_ns=59 if phase == "final_pre_popen" else cleanup_started - 1,
            outcome="MATCH",
        )
        for (phase, identity), digest in checks.items()
    ]
    content["post-run-integrity.json"] = encode(integrity)
    return directory, content, authorities


@pytest.mark.parametrize("handshake", [False, True])
def test_terminal_failure_retains_reached_native_contract_phase(candidate, tmp_path, handshake):
    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = terminal_failure_fixture(
        candidate, tmp_path, handshake=handshake
    )
    pins = write_native_paired_package(
        directory, content=content, immutable_authorities=authorities
    )
    result = verify_native_paired_package(
        directory,
        expected_prelaunch_sha256=pins.prelaunch_sha256,
        expected_completion_sha256=pins.completion_sha256,
        immutable_authorities=authorities,
    )
    assert result.status == "CONTROLLED_CONTRACT_FAILURE_RETAINED"
    assert result.pair is None


def test_failed_contract_result_cannot_contradict_verified_authorization(candidate, tmp_path):
    import json

    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = terminal_failure_fixture(candidate, tmp_path, handshake=True)
    result = json.loads(content["result.json"])
    result["observations"]["gates"]["authorization"] = False
    content["result.json"] = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ValueError, match="gate contradiction"):
        write_native_paired_package(directory, content=content, immutable_authorities=authorities)


def test_private_key_identity_cannot_disappear_from_disposal(candidate, tmp_path):
    import json

    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package
    from app.simulation.openttd.terrain_native_validation import binding_identity

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)
    identity = binding_identity("owned-path", candidate.record["key_path"])
    value = json.loads(content["credential-disposal.json"])
    original = value["observations"]["materializations"]
    value["observations"]["materializations"] = [
        row for row in original if row["identity"] != identity
    ]
    assert len(value["observations"]["materializations"]) == len(original) - 1
    content["credential-disposal.json"] = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode()
    with pytest.raises(ValueError, match="disposal identity coverage"):
        write_native_paired_package(directory, content=content, immutable_authorities=authorities)


@pytest.mark.parametrize("mutation", ["symlink", "directory"])
def test_complete_retained_package_rejects_artifact_type_substitution(
    candidate, tmp_path, mutation
):
    from app.simulation.openttd.terrain_native_paired_evidence import write_native_paired_package

    directory, content, authorities = complete_native_fixture(candidate, tmp_path)
    pins = write_native_paired_package(
        directory, content=content, immutable_authorities=authorities
    )
    target = directory / "runtime.json"
    raw = target.read_bytes()
    target.unlink()
    if mutation == "symlink":
        substitute = tmp_path / "alias.json"
        substitute.write_bytes(raw)
        target.symlink_to(substitute)
    else:
        target.mkdir()
    with pytest.raises(ValueError, match="inventory"):
        verify_native_paired_package(
            directory,
            expected_prelaunch_sha256=pins.prelaunch_sha256,
            expected_completion_sha256=pins.completion_sha256,
            immutable_authorities=authorities,
        )
