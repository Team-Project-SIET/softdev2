"""Strict public wire records for native paired v1; records do not grant execution."""

import hashlib
import json
import unicodedata
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, TypeAdapter, model_validator

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest
from app.simulation.openttd.terrain_paired_evidence import CombinedBudget, Context, SweepBudget

SCHEMA = "terrain-native-paired-evidence-v1"
OPERATION = "openttd-15.3.tile_facts_page.two_sweeps"
GATES = (
    "authorization",
    "source_integrity",
    "runtime_identity",
    "authentication",
    "coverage",
    "equality",
    "accounting",
    "liveness",
    "log_integrity",
    "cleanup",
    "credential_disposal",
    "post_run_integrity",
)
Count = Annotated[int, Field(strict=True, ge=0)]
Positive = Annotated[int, Field(strict=True, gt=0)]
Port = Annotated[int, Field(strict=True, gt=0, le=65535)]
Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
]
Start = Annotated[str, Field(pattern=r"^[0-9]+$")]
Nonce = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


def _text(value: str) -> str:
    if not value or "\x00" in value or unicodedata.normalize("NFC", value) != value:
        raise ValueError("Nonempty NFC text without NUL required")
    return value


Text = Annotated[str, AfterValidator(_text)]


def _relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(p in {".", ".."} for p in path.parts):
        raise ValueError("Canonical relative artifact path required")
    if not value.isascii() or "\\" in value or not path.parts:
        raise ValueError("Unsafe artifact path")
    return value


def _absolute(value: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute() or str(path) != value or ".." in path.parts or "\\" in value:
        raise ValueError("Canonical absolute provenance path required")
    return value


ArtifactPath = Annotated[Text, AfterValidator(_relative)]
AbsolutePath = Annotated[Text, AfterValidator(_absolute)]
Phase = Literal[
    "PREPARED",
    "SEALED_UNAUTHORIZED",
    "AUTHORIZED",
    "CLAIMED",
    "INVOCATION_RECORDED",
    "LAUNCHED",
    "CONNECTED",
    "SWEEP_1",
    "SWEEP_2",
    "VERIFIED",
    "CLEANING",
    "CLEANED",
    "FINALIZED",
    "ACCEPTED",
    "REJECTED",
    "FAILED_CLEANED",
    "CLEANUP_FAILED",
]
AuthState = Literal[
    "DISCONNECTED",
    "CONNECTED",
    "AUTH_JOIN_SENT",
    "AUTH_REQUEST_RECEIVED",
    "AUTH_RESPONSE_SENT",
    "ENCRYPTION_ENABLED",
    "PROTOCOL_RECEIVED",
    "WELCOME_RECEIVED",
    "ACTIVE",
    "CLOSED",
]
FramePhase = Literal["handshake", "establishment", "setup", "sweep1", "sweep2", "cleanup"]
Direction = Literal["inbound", "outbound"]


class Commitment(Contract):
    path: ArtifactPath
    byte_length: Count
    sha256: Digest


class Input(Contract):
    identity: Text
    origin: AbsolutePath
    byte_length: Count
    sha256: Digest


class Attempt(Contract):
    identity: Identifier
    destination: AbsolutePath
    seal_destination: AbsolutePath


class Argv(Contract):
    argv: tuple[Text, ...]


class RuntimePreparation(Contract):
    executable: Input
    version: Literal["15.3"]
    graphics_archive: Input
    graphics_files: tuple[Input, ...]
    bridge_inputs: tuple[Input, ...]
    bridge_sha256: Digest
    argv: tuple[Text, ...]
    environment: dict[Text, Text]
    public_config: tuple[Input, ...]


class Recipe(Contract):
    map_x: Positive
    map_y: Positive
    seed: Count
    start_date: Count
    landscape: Annotated[int, Field(strict=True, ge=0, le=3)]


class Source(Contract):
    candidate: Input
    source_freeze_sha256: Digest
    canonical_inputs_sha256: Digest
    ownership_sha256: Digest
    materializations_sha256: Digest
    historical_integrity_sha256: Digest
    recipe: Recipe
    recipe_sha256: Digest


class FrameCaps(Contract):
    post_auth_frames: Positive
    pre_auth_frames: Positive
    post_auth_stream_bytes: Positive
    pre_auth_stream_bytes: Positive


class Budgets(Contract):
    per_sweep: SweepBudget
    combined: CombinedBudget
    frames: FrameCaps


class Resources(Contract):
    startup_ns: Positive
    query_ns: Positive
    marker_ns: Positive
    acquisition_ns: Positive
    cleanup_ns: Positive
    finalization_ns: Positive
    raw_reader_bytes: Positive
    frame_queue_count: Positive
    frame_queue_bytes: Positive
    decrypted_queue_count: Positive
    decrypted_queue_bytes: Positive
    host_admission_bytes: Positive
    process_rss_bytes: Positive
    memory_monitor_interval_ns: Positive
    stdout_bytes: Positive
    stderr_bytes: Positive
    paired_bytes: Positive
    outer_bytes: Positive
    outer_files: Positive
    admission_evidence: tuple[Commitment, ...]


class EndpointContract(Contract):
    policy: Literal["linux-kernel-endpoint-closure-v1"]
    family: Literal["AF_INET"]
    host: Literal["127.0.0.1"]
    required: tuple[str, ...]
    kernel_tables: tuple[Literal["tcp", "tcp6", "udp", "udp6"], ...]
    allowed_residual_state: Literal["TCP_TIME_WAIT_ONLY"]
    ambiguous_state: Literal["FAIL_CLOSED"]
    ipv6_wildcard: Literal["FAIL_CLOSED_UNLESS_COVERAGE_DISPROVED"]
    immediate_rebindability_required: Literal[False]
    connection_probe: Literal[False]
    sleeps: Literal[0]
    retries: Literal[0]


class EndpointIdentity(Contract):
    family: Literal["AF_INET"]
    host: Literal["127.0.0.1"]
    game_port: Port
    admin_port: Port

    @model_validator(mode="after")
    def distinct_ports(self):
        if self.game_port == self.admin_port:
            raise ValueError("Distinct endpoints required")
        return self


class EndpointPolicy(EndpointIdentity):
    policy: EndpointContract
    client_public_key: Digest
    client_public_key_sha256: Digest


class ArtifactPolicy(Contract):
    schema_id: Literal["terrain-native-paired-evidence-v1"] = Field(alias="schema")
    version: Literal[1]


class HistoricalAuthority(Contract):
    role: Literal["historical"]
    provenance_base: AbsolutePath
    identity: Identifier
    inventory_sha256: Digest
    policy: Literal["historical-exact-paths-v1"]


class Prelaunch(Contract):
    schema_id: Literal["terrain-native-paired-prelaunch-v1"] = Field(alias="schema")
    version: Literal[1]
    mode: Literal["REAL"]
    operation: Literal["openttd-15.3.tile_facts_page.two_sweeps"]
    attempt: Attempt
    runtime: RuntimePreparation
    source: Source
    context: Context
    plan: Commitment
    budgets: Budgets
    resources: Resources
    endpoint_policy: EndpointPolicy
    artifact_policy: ArtifactPolicy
    required_gates: tuple[str, ...]
    commitments: tuple[Commitment, ...]
    external_authorities: tuple[HistoricalAuthority]

    @model_validator(mode="after")
    def fixed_plan_and_gates(self):
        if self.plan.path != "seal/page-plan.json" or self.required_gates != GATES:
            raise ValueError("Incorrect required plan or gates")
        return self


class Completion(ArtifactPolicy):
    mode: Literal["REAL"]
    operation: Literal["openttd-15.3.tile_facts_page.two_sweeps"]
    attempt_identity: Identifier
    prelaunch_sha256: Digest
    status: Literal["REAL_PASS", "REAL_FAIL"]
    terminal_phase: Phase
    paired_descriptor_sha256: Digest | None
    artifacts: tuple[Commitment, ...]


class Grant(Contract):
    schema_id: Literal["terrain-native-paired-local-grant-v1"] = Field(alias="schema")
    version: Literal[1]
    authorization_mode: Literal["OPERATOR_ATTENDED_LOCAL_PROOF"]
    trust: Literal["LOCAL_OPERATOR_ATTESTED"]
    proof_operation: Literal["openttd-15.3.tile_facts_page.two_sweeps"]
    seal_sha256: Digest
    attempt_identity: Identifier
    attempt_directory: AbsolutePath
    owner_pid: Positive
    owner_start: Start
    owner_nonce: Nonce
    launch_allowance: Literal[1]
    connection_allowance: Literal[1]
    request_allowance: Positive
    no_reconnect: Literal[True]
    no_relaunch: Literal[True]
    no_resume: Literal[True]
    state: Literal["STARTED"]
    no_retry: Literal[True]


class Claim(ArtifactPolicy):
    mode: Literal["REAL"]
    attempt_identity: Identifier
    attempt_directory: AbsolutePath
    seal_sha256: Digest
    consumed_record_sha256: Digest
    owner_pid: Positive
    owner_start: Start
    owner_nonce: Nonce
    no_retry: Literal[True]


class Invocation(Claim):
    launch_claim_sha256: Digest
    launch_invocations: Literal[1]


class Unavailable(Contract):
    available: Literal[False]
    reason: Annotated[Identifier, Field(max_length=64)]
    phase: Phase


class Available(Contract):
    available: Literal[True]


class ProcessIdentity(Contract):
    pid: Positive
    start: Start


class Runtime(Available):
    owner: ProcessIdentity
    child: ProcessIdentity | None
    launch_argv_sha256: Digest
    configuration_sha256: Digest
    bridge_sha256: Digest
    executable_sha256: Digest
    process_instances: Count
    network_namespace: Identifier
    endpoints: EndpointIdentity
    launched_ns: Count | None
    exited_ns: Count | None
    reaped_ns: Count | None


class AuthEvent(Contract):
    ordinal: Positive
    state: AuthState
    time_ns: Count


class Frequency(Contract):
    update_type: Count
    frequency: Count


class ProtocolFacts(Contract):
    version: int
    frequencies: tuple[Frequency, ...]


class WelcomeFacts(Contract):
    revision: Text
    dedicated: bool
    width: Positive
    height: Positive
    seed: Count
    landscape: Count
    start_date: Count


class HandshakeFrame(Contract):
    ordinal: Positive
    direction: Direction
    packet_type: Count
    encoded_byte_length: Positive
    encoded_sha256: Digest
    state: AuthState


class Authentication(Available):
    session_id: Identifier
    process: ProcessIdentity
    endpoints: EndpointIdentity
    public_key: Digest
    public_key_sha256: Digest
    method: Literal["X25519_AuthorizedKey"] | None
    encrypted: bool
    state: AuthState
    states: tuple[AuthEvent, ...]
    protocol: ProtocolFacts | None
    welcome: WelcomeFacts | None
    handshake: tuple[HandshakeFrame, ...]


class Error(Contract):
    stage: Phase
    type: Identifier


class Failure(Contract):
    code: Annotated[Identifier, Field(max_length=64)]
    phase: Phase
    message: Annotated[Text, Field(max_length=1024)]
    cause_type: Identifier | None


class LifecycleEvent(Contract):
    ordinal: Positive
    phase: Phase
    event: Literal[
        "prepared",
        "sealed",
        "authorized",
        "claimed",
        "invocation_recorded",
        "launched",
        "connected",
        "subscribed",
        "sweep_started",
        "request_sent",
        "response_received",
        "page_admitted",
        "sweep_completed",
        "pair_verified",
        "rejected",
        "cleanup_started",
        "cleaned",
        "cleanup_failed",
        "finalized",
    ]
    time_ns: Count
    session_id: Identifier | None
    sweep: Positive | None
    page: Positive | None
    request_id: Identifier | None


class Lifecycle(Available):
    events: tuple[LifecycleEvent, ...]
    failure: Failure | None
    cleanup_errors: tuple[Error, ...]


class Frame(Contract):
    ordinal: Positive
    direction: Direction
    phase: FramePhase
    session_id: Identifier
    request_id: Identifier | None
    packet_type: Count
    plaintext_byte_length: Positive
    encoded_byte_length: Positive
    plaintext_sha256: Digest | None
    encoded_sha256: Digest


class PageDelta(Contract):
    sweep: Positive
    page: Positive
    request_id: Identifier
    first_frame: Positive
    last_frame: Positive
    admitted: bool
    request_bytes: Count
    response_bytes: Count
    query_operations: Count
    request_sha256: Digest
    response_sha256: Digest | None


class FrameTotals(Contract):
    establishment: Count
    setup: Count
    sweep1: Count
    sweep2: Count
    cleanup: Count
    handshake: Count
    query_operations: Count
    post_auth_frames: Count
    pre_auth_frames: Count
    request_bytes: Count
    response_bytes: Count
    inbound_stream_bytes: Count
    outbound_stream_bytes: Count


class RejectedFrame(Contract):
    direction: Direction
    phase: FramePhase
    packet_type: Count | None
    captured_byte_length: Count
    sha256: Digest
    reason: Annotated[Identifier, Field(max_length=64)]


class ByteDigest(Contract):
    byte_length: Count
    sha256: Digest


class PendingExchange(Contract):
    sweep: Positive
    page: Positive
    request_id: Identifier
    request: ByteDigest
    response: ByteDigest | None
    delivery: Literal["SENT", "UNKNOWN"]
    admitted: Literal[False]


class FrameAccounting(Available):
    frames: tuple[Frame, ...]
    page_deltas: tuple[PageDelta, ...]
    totals: FrameTotals
    rejected: RejectedFrame | None
    pending: PendingExchange | None


class Disposal(Contract):
    identity: Identifier
    commitment_sha256: Digest
    removed: bool
    observed_ns: Count


class CredentialDisposal(Available):
    materializations: tuple[Disposal, ...]
    workspace_disposed: bool
    retained_secret_count: Count


class IntegrityCheck(Contract):
    identity: Identifier
    phase: Literal["final_pre_popen", "post_run"]
    expected_sha256: Digest
    observed_sha256: Digest | None
    checked_ns: Count
    outcome: Literal["MATCH", "MISSING", "CHANGED"]


class HistoryCheck(Contract):
    identity: Identifier
    inventory_sha256: Digest
    validated_paths: Count
    missing: tuple[Text, ...]
    changed: tuple[Text, ...]


class PostRunIntegrity(Available):
    before_disposal: tuple[IntegrityCheck, ...]
    history: HistoryCheck
    workspace_disposed: bool


class RawCleanup(Contract):
    pid: Positive | None
    graceful_attempted: bool
    quit_command: Literal["quit"]
    returncode: int | None
    reaped: bool
    remaining_processes: tuple[ProcessIdentity, ...]
    events: tuple[Text, ...]
    cleanup_error: tuple[Error, ...]
    admin_frame_accounting: FrameTotals


class CleanupRaw(Available):
    cleanup: RawCleanup
    completed_ns: Count


class SocketRow(Contract):
    table: Literal["tcp", "tcp6", "udp", "udp6"]
    local: Text
    local_port: Annotated[int, Field(strict=True, ge=0, le=65535)]
    remote: Text
    remote_port: Annotated[int, Field(strict=True, ge=0, le=65535)]
    state: Literal["TIME_WAIT"]
    inode: Count


class EndpointVerification(EndpointIdentity):
    policy: Literal["linux-kernel-endpoint-closure-v1"]
    process_reaped: bool
    reservation_released: bool
    listener_closed: bool
    connection_closed: bool
    kernel_states: tuple[SocketRow, ...]
    immediate_rebindability_required: Literal[False]
    connection_probe: Literal[False]


class EndpointCleanup(Contract):
    sockets_closed: bool
    endpoint_verification: EndpointVerification | None


class Cleanup(CleanupRaw):
    endpoints: EndpointCleanup


class Gates(Contract):
    authorization: bool
    source_integrity: bool
    runtime_identity: bool
    authentication: bool
    coverage: bool
    equality: bool
    accounting: bool
    liveness: bool
    log_integrity: bool
    cleanup: bool
    credential_disposal: bool
    post_run_integrity: bool


class Result(Available):
    status: Literal["REAL_PASS", "REAL_FAIL"]
    terminal_phase: Phase
    failure: Failure | None
    gates: Gates


class Snapshot(Contract):
    artifact: Literal["stderr.log"]
    start_offset: Count
    end_offset: Count
    byte_length: Count
    sha256: Digest


class Marker(Contract):
    marker: Text
    start_offset: Count
    end_offset: Count


class LogPage(Contract):
    sweep: Positive
    page: Positive
    request_id: Identifier
    request_artifact: ArtifactPath
    response_artifact: ArtifactPath
    exchange_artifact: ArtifactPath
    response_sha256: Digest
    snapshot: Snapshot
    markers: tuple[Marker, Marker, Marker, Marker]


class PendingLogPage(Contract):
    sweep: Positive
    page: Positive
    request_id: Identifier
    request_artifact: ArtifactPath
    response_artifact: ArtifactPath | None
    exchange_artifact: ArtifactPath
    response_sha256: Digest | None
    snapshot: Snapshot
    markers: tuple[Marker, ...]


class FinalLog(Contract):
    artifact: Literal["stdout.log", "stderr.log"]
    byte_length: Count
    sha256: Digest


class FinalLogs(Contract):
    stdout: FinalLog
    stderr: FinalLog


class ExecutionLog(Available):
    policy: Literal["terrain-execution-log-multi-page-v1"]
    pages: tuple[LogPage, ...]
    pending: PendingLogPage | None
    final: FinalLogs


class Envelope(ArtifactPolicy):
    attempt_identity: Identifier
    prelaunch_sha256: Digest


class RuntimeRecord(Envelope):
    kind: Literal["runtime"]
    observations: Runtime | Unavailable


class AuthenticationRecord(Envelope):
    kind: Literal["authentication"]
    observations: Authentication | Unavailable


class LifecycleRecord(Envelope):
    kind: Literal["lifecycle"]
    observations: Lifecycle | Unavailable


class FrameAccountingRecord(Envelope):
    kind: Literal["frame-accounting"]
    observations: FrameAccounting | Unavailable


class CredentialDisposalRecord(Envelope):
    kind: Literal["credential-disposal"]
    observations: CredentialDisposal | Unavailable


class PostRunIntegrityRecord(Envelope):
    kind: Literal["post-run-integrity"]
    observations: PostRunIntegrity | Unavailable


class CleanupRawRecord(Envelope):
    kind: Literal["cleanup.raw"]
    observations: CleanupRaw | Unavailable


class CleanupRecord(Envelope):
    kind: Literal["cleanup"]
    observations: Cleanup | Unavailable


class ResultRecord(Envelope):
    kind: Literal["result"]
    observations: Result | Unavailable


class ExecutionLogRecord(Envelope):
    kind: Literal["execution-log"]
    observations: ExecutionLog | Unavailable


Record = Annotated[
    RuntimeRecord
    | AuthenticationRecord
    | LifecycleRecord
    | FrameAccountingRecord
    | CredentialDisposalRecord
    | PostRunIntegrityRecord
    | CleanupRawRecord
    | CleanupRecord
    | ResultRecord
    | ExecutionLogRecord,
    Field(discriminator="kind"),
]


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _nfc(value: object) -> None:
    if isinstance(value, str) and unicodedata.normalize("NFC", value) != value:
        raise ValueError("Noncanonical NFC string")
    if isinstance(value, dict):
        for key, item in value.items():
            _nfc(key)
            _nfc(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _nfc(item)


def encode(value: Contract) -> bytes:
    """Encode strict models with wire aliases and the shared canonical JSON conventions."""
    fields = value.model_dump(mode="json", by_alias=True)
    _nfc(fields)
    return json.dumps(
        fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def parse[Model: Contract](raw: bytes, model: type[Model]) -> Model:
    json.loads(raw, object_pairs_hook=_pairs)
    value = model.model_validate_json(raw)
    if encode(value) != raw:
        raise ValueError("Noncanonical metadata bytes")
    return value


def parse_prelaunch(raw: bytes) -> Prelaunch:
    return parse(raw, Prelaunch)


def parse_completion(raw: bytes) -> Completion:
    return parse(raw, Completion)


def parse_record(raw: bytes) -> Record:
    json.loads(raw, object_pairs_hook=_pairs)
    value = TypeAdapter(Record).validate_json(raw)
    if encode(value) != raw:
        raise ValueError("Noncanonical metadata bytes")
    return value


def argv_sha256(argv: tuple[str, ...]) -> str:
    return hashlib.sha256(canonical_bytes(Argv(argv=argv))).hexdigest()


def validate_argv_configuration(
    prelaunch: Prelaunch,
    *,
    actual_argv: tuple[str, ...],
    configuration_bytes: bytes,
    config_origin: str,
) -> tuple[str, str]:
    """Validate launch bytes; package verification checks provenance and ownership."""
    if actual_argv != prelaunch.runtime.argv or not actual_argv:
        raise ValueError("Launch argv differs from sealed sequence")
    if actual_argv[0] != prelaunch.runtime.executable.origin:
        raise ValueError("Executable argument identity mismatch")
    if actual_argv.count("-c") != 1 or actual_argv.index("-c") + 1 >= len(actual_argv):
        raise ValueError("One sealed configuration target required")
    selected = [
        item
        for item in prelaunch.runtime.public_config
        if item.identity == "candidate:materialization-inputs/openttd.cfg"
    ]
    if len(selected) != 1 or selected[0].origin != config_origin:
        raise ValueError("Missing or substituted main configuration commitment")
    config = selected[0]
    digest = hashlib.sha256(configuration_bytes).hexdigest()
    if len(configuration_bytes) != config.byte_length or digest != config.sha256:
        raise ValueError("Main configuration bytes mismatch")
    return argv_sha256(actual_argv), digest


class PlannedPage(Contract):
    ordinal: Positive
    request_id: Identifier
    cursor: Count
    tile_ids: tuple[Count, ...]
    request_byte_length: Count
    request_sha256: Digest


class SweepIdentity(Contract):
    acquisition_id: Identifier
    ordinal: Positive


class PlannedSweep(Contract):
    identity: SweepIdentity
    pages: tuple[PlannedPage, ...]


class PagePlan(ArtifactPolicy):
    context: Context
    sweeps: tuple[PlannedSweep, PlannedSweep]


class CanonicalEntry(Contract):
    identity: Text
    origin: Text
    artifact: ArtifactPath
    sha256: Digest


class CanonicalIndex(Contract):
    policy: Literal["terrain-native-durable-canonical-v1"]
    candidate_path: AbsolutePath
    entries: tuple[CanonicalEntry, ...]


def parse_grant(raw: bytes) -> Grant:
    return parse(raw, Grant)


def parse_claim(raw: bytes) -> Claim:
    return parse(raw, Claim)


def parse_invocation(raw: bytes) -> Invocation:
    return parse(raw, Invocation)
