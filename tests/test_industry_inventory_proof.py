"""Controlled production inventory proof preparation; no native gameplay."""

import asyncio
import hashlib
import json
import sys

import pytest

from app.simulation.openttd.proof import __main__ as cli


def test_public_inventory_mode_routes_preparation(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace

    calls = []

    def prepare(directory, *, mode):
        calls.append((directory, mode))
        return SimpleNamespace(directory=directory)

    monkeypatch.setattr(cli, "prepare_proof", prepare)
    monkeypatch.setattr(
        sys,
        "argv",
        ["proof", "prepare", "--mode", "industry-inventory", "--directory", str(tmp_path)],
    )
    cli.main()
    assert calls == [(tmp_path, "industry-inventory")]


def make_prepared(tmp_path):
    from test_real_ack_graphics import graphics_archive

    from app.simulation.openttd.proof.harness import prepare_proof

    binary = tmp_path / "openttd"
    binary.write_bytes(b"controlled binary")
    binary.chmod(0o700)
    archive = tmp_path / "graphics.zip"
    digest = graphics_archive(archive)
    return prepare_proof(
        tmp_path / "prelaunch",
        mode="industry-inventory",
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=archive,
        graphics_sha256=digest,
    )


class ControlledInventoryBackend:
    kind = "CONTROLLED"

    def __init__(self, ids=(0, 1, 2), **wire_options):
        self.ids, self.options = ids, wire_options
        self.launches = self.closed = 0
        self.session = self.transport = None
        self.network = []
        self.inventory_session = None

    def preflight(self, prepared):
        pass

    async def launch(self, prepared):
        self.launches += 1
        prepared.spec.stdout_path.write_text("controlled output\n")
        prepared.spec.stderr_path.write_text(
            "dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15\n"
        )

    async def authenticate(self, prepared, gates):
        from dataclasses import asdict

        from test_industry_inventory import InventoryWire

        from app.simulation.openttd.admin_protocol import ServerWelcome

        self.wire = InventoryWire(ids=self.ids, **self.options)
        from app.simulation.openttd.proof.inventory_native import InventoryRecordedSession

        self.transport = self.wire.transport
        self.inventory_session = InventoryRecordedSession(self.transport.session)
        self.transport.session = self.inventory_session
        self.session = self.inventory_session.session
        self.welcome = ServerWelcome("Server", "15.3", True, "", 42, 0, 712223, 64, 64)
        return dict(
            auth=dict(method="X25519_AuthorizedKey", encrypted=True),
            protocol=dict(version=3),
            welcome=asdict(self.welcome),
        )

    async def wait_inventory_startup(self, prepared):
        pass

    async def inventory_evidence(self, prepared, request, exchange):
        native = await self.wire.evidence(request, exchange)
        with prepared.spec.stderr_path.open("ab") as out:
            out.write(native.raw_log)
        assert self.inventory_session is not None
        self.inventory_session.validated(exchange)
        return native

    def inventory_network_evidence(self):
        return [] if self.inventory_session is None else self.inventory_session.snapshot()

    def health(self):
        pass

    async def cleanup(self, prepared):
        self.closed += 1
        return dict(reaped=True, remaining_processes=[], graceful_attempted=True, returncode=0)


@pytest.mark.parametrize(
    "ids,pages,passed",
    [
        ((), 1, False),
        ((0,), 1, False),
        ((0, 1), 1, False),
        ((0, 1, 2), 2, True),
        ((0, 1, 2, 5, 8), 3, True),
        (tuple(range(32)), 16, True),
    ],
)
def test_production_inventory_lifecycle_terminal_policy(tmp_path, ids, pages, passed):
    from app.simulation.openttd.proof.inventory_attempt import execute_inventory_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledInventoryBackend(ids)
    result = asyncio.run(execute_inventory_attempt(prepared, backend))
    assert result["status"] == ("CONTROLLED_SUCCESS" if passed else "CONTROLLED_FAILED"), result
    assert (backend.launches, backend.closed) == (1, 1)
    assert len(backend.wire.requests) == pages
    assert [r.limit for r in backend.wire.requests] == [2] * pages
    assert [r.request_id for r in backend.wire.requests] == [
        f"openttd15-industry-inventory-001-p{i:03d}" for i in range(1, pages + 1)
    ]
    assert backend.wire.requests[0].after_id is None
    assert not prepared.key_path.exists()
    if not passed:
        assert result["error"] == "MULTI-PAGE CONDITION NOT ESTABLISHED"
    attempt = prepared.directory.with_name("openttd-15.3-industry-inventory-real-attempt1")
    observation = json.loads((attempt / "inventory-observation.json").read_text())
    assert observation["complete"] is passed and observation["page_count"] == pages
    assert observation["cursor_chain_complete"]
    assert len((attempt / "page-receipts.jsonl").read_text().splitlines()) == pages
    assert len((attempt / "gamescript-page-evidence.jsonl").read_text().splitlines()) == pages
    with pytest.raises(ValueError, match="claimed"):
        asyncio.run(execute_inventory_attempt(prepared, backend))


def test_inventory_preparation_and_public_guarded_preflight(tmp_path, monkeypatch, capsys):
    import socket
    import subprocess

    from app.simulation.openttd.proof import native
    from app.simulation.openttd.proof.harness import EndpointReservation

    prepared = make_prepared(tmp_path)
    try:
        monkeypatch.setattr(native, "BINARY", prepared.spec.identity.executable)
        monkeypatch.setattr(native, "BINARY_SHA256", prepared.spec.identity.sha256)
        monkeypatch.setattr(
            cli, "InventoryNativeBackend", lambda **kw: ControlledInventoryBackend()
        )
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("No process"))
        monkeypatch.setattr(socket.socket, "connect", lambda *a, **kw: pytest.fail("No connection"))
        monkeypatch.setattr(sys, "addaudithook", lambda guard: None)
        calls = []
        allocate = EndpointReservation.allocate

        def reserve(*args):
            calls.append(args)
            return allocate(*args)

        monkeypatch.setattr(EndpointReservation, "allocate", reserve)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "proof",
                "preflight",
                "--mode",
                "industry-inventory",
                "--directory",
                str(prepared.directory),
            ],
        )
        cli.main()
        value = json.loads(capsys.readouterr().out)
        assert value["state"] == "READY_TO_LAUNCH" and value["process_creation_blocked"]
        assert value["welcome_bounds_validator_wired"] and value["canonical_evidence_policy_loaded"]
        assert value["inventory_session"]["page_size"] == 2
        assert calls == [prepared.endpoints]
        assert not prepared.directory.with_name(
            "openttd-15.3-industry-inventory-real-attempt1"
        ).exists()
        key = prepared.key_path.read_bytes()
        assert prepared.key_path.stat().st_mode & 0o777 == 0o600
        assert all(
            key not in p.read_bytes() and key.hex().encode() not in p.read_bytes()
            for p in prepared.directory.iterdir()
            if p.is_file()
        )
    finally:
        prepared.dispose()


@pytest.mark.parametrize(
    "case",
    [
        "repeated_cursor",
        "regression",
        "duplicate",
        "ordering",
        "wrong_id",
        "wrong_type",
        "empty_more",
        "bounds",
        "tile",
        "oversize",
        "timeout",
        "disconnect",
        "duplicate_response",
    ],
)
def test_failed_inventory_retains_partial_evidence_and_never_retries(tmp_path, monkeypatch, case):
    from app.simulation.openttd.industry_query import IndustryInventorySession
    from app.simulation.openttd.proof import inventory_attempt

    class FastSession(IndustryInventorySession):
        def __init__(self, *args, **kwargs):
            kwargs["timeout"] = 0.02
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(inventory_attempt, "IndustryInventorySession", FastSession)

    def change(obj, number):
        if number != 2:
            return
        if case == "repeated_cursor":
            obj["next_after_id"] = 1
        elif case == "regression":
            obj["next_after_id"] = 0
        elif case == "duplicate":
            obj["industries"][0]["id"] = 1
        elif case == "ordering":
            obj["industries"].reverse()
        elif case == "wrong_id":
            obj["request_id"] = "wrong"
        elif case == "wrong_type":
            obj["type"] = "world_info_result"
        elif case == "empty_more":
            obj["industries"] = []
        elif case == "bounds":
            obj["industries"][0]["x"] = 64
        elif case == "tile":
            obj["industries"][0]["tile"] = 1
        elif case == "oversize":
            obj["padding"] = "x" * 512

    options: dict = dict(change=change)
    if case in ("timeout", "disconnect"):
        options.update(fail_page=2, failure=case)
    elif case == "duplicate_response":
        options.update(failure="duplicate")
    prepared = make_prepared(tmp_path)
    backend = ControlledInventoryBackend((0, 1, 2, 5, 8), **options)
    result = asyncio.run(inventory_attempt.execute_inventory_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED" and result["error"]
    assert backend.launches == backend.closed == 1
    assert len(backend.wire.requests) <= 2
    assert not prepared.key_path.exists()
    attempt = prepared.directory.with_name("openttd-15.3-industry-inventory-real-attempt1")
    assert json.loads((attempt / "inventory-observation.json").read_text())["complete"] is False
    assert (attempt / "gamescript-supporting.log").exists()
    assert (attempt / "page-requests.jsonl").exists()
    assert result["source_integrity"]


@pytest.mark.parametrize(
    "marker", ["INDUSTRY_PAGE_READ", "BRIDGE_RESPONSE_SENT", "BRIDGE_POST_RESPONSE_ALIVE"]
)
def test_each_page_requires_native_evidence(tmp_path, marker):
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence
    from app.simulation.openttd.proof.inventory_attempt import execute_inventory_attempt

    class MissingEvidence(ControlledInventoryBackend):
        async def inventory_evidence(self, prepared, request, exchange):
            evidence = await super().inventory_evidence(prepared, request, exchange)
            if request.after_id is not None:
                raw = b"".join(
                    line
                    for line in evidence.raw_log.splitlines(keepends=True)
                    if marker.encode() not in line
                )
                prepared.spec.stderr_path.write_bytes(
                    prepared.spec.stderr_path.read_bytes().replace(evidence.raw_log, raw)
                )
                return parse_industry_page_evidence(raw, request.request_id)
            return evidence

    prepared = make_prepared(tmp_path)
    backend = MissingEvidence()
    result = asyncio.run(execute_inventory_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED"
    assert len(backend.wire.requests) == 2 and backend.closed == 1


def test_proof_inventory_digest_independent_of_page_boundaries():
    from test_industry_inventory import InventoryWire, world_context

    from app.simulation.openttd.industry_query import IndustryInventorySession
    from app.simulation.openttd.proof.inventory_contract import INVENTORY_SESSION_ID

    async def scenario():
        results = []
        for size in (2, 3, 5):
            wire = InventoryWire()
            results.append(
                await IndustryInventorySession(
                    INVENTORY_SESSION_ID, world_context(), page_size=size
                ).collect(wire.transport, wire.evidence)
            )
        assert [r.page_count for r in results] == [4, 3, 2]
        assert len({r.inventory_digest for r in results}) == 1
        assert len({r.to_bytes() for r in results}) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "page,after,canonical",
    [
        (
            1,
            None,
            b'{"after_id":null,"limit":2,"protocol":1,"request_id":"openttd15-industry-inventory-001-p001","type":"industry_page"}',
        ),
        (
            2,
            1,
            b'{"after_id":1,"limit":2,"protocol":1,"request_id":"openttd15-industry-inventory-001-p002","type":"industry_page"}',
        ),
    ],
)
def test_frozen_request_generation(page, after, canonical):
    from app.simulation.openttd.proof.inventory_contract import inventory_request

    request = inventory_request(page, after)
    assert request.to_bytes() == canonical
    assert request.to_bytes() == inventory_request(page, after).to_bytes()
    assert hashlib.sha256(request.to_bytes()).hexdigest() == hashlib.sha256(canonical).hexdigest()


@pytest.mark.parametrize(
    "name",
    [
        "inventory-contract.json",
        "request.json",
        "PRELAUNCH.json",
        "source-authority.json",
        "world-support.json",
    ],
)
def test_prelaunch_tampering_stops_before_launch_and_cannot_retry(tmp_path, name):
    from app.simulation.openttd.proof.inventory_attempt import execute_inventory_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledInventoryBackend()
    path = prepared.directory / name
    original = path.read_bytes()
    try:
        path.write_bytes(original + b" ")
        with pytest.raises(ValueError):
            asyncio.run(execute_inventory_attempt(prepared, backend))
        assert backend.launches == 0 and backend.session is None
        path.write_bytes(original)
        with pytest.raises(ValueError, match="no retry"):
            asyncio.run(execute_inventory_attempt(prepared, backend))
        assert not prepared.directory.with_name(
            "openttd-15.3-industry-inventory-real-attempt1"
        ).exists()
    finally:
        prepared.dispose()


def test_preparation_fresh_keys_and_bridge_identity(tmp_path):
    from app.simulation.openttd.industry_inventory import DEFAULT_INDUSTRY_PAGE_SIZE
    from app.simulation.openttd.industry_page import MAX_PAGE_SIZE
    from app.simulation.openttd.proof.inventory_contract import inventory_contract_digest

    assert DEFAULT_INDUSTRY_PAGE_SIZE == 3 and MAX_PAGE_SIZE == 5
    first = make_prepared(tmp_path)
    other = tmp_path / "second"
    other.mkdir()
    second = make_prepared(other)
    try:
        assert first.key_path.read_bytes() != second.key_path.read_bytes()
        a = json.loads((first.directory / "bridge-package-identity.json").read_text())
        b = json.loads((second.directory / "bridge-package-identity.json").read_text())
        assert (
            a == b
            and a["sha256"] == "2151a6a4b9669c3e9a0fef595c758f6f8aeae20a21a26c6f808ab23fcefdccfc"
        )
        assert (
            json.loads((first.directory / "PRELAUNCH.json").read_text())["proof_config_sha256"]
            == inventory_contract_digest()
        )
        assert (
            json.loads((first.directory / "inventory-contract.json").read_text())[
                "independent_industry_inventory"
            ]
            is None
        )
    finally:
        first.dispose()
        second.dispose()


@pytest.mark.parametrize("change", ["evidence", "connection", "network_digest", "cleanup"])
def test_failure_after_transport_cannot_pass(tmp_path, change):
    from app.simulation.openttd.proof.inventory_attempt import execute_inventory_attempt

    class Failure(ControlledInventoryBackend):
        async def inventory_evidence(self, prepared, request, exchange):
            value = await super().inventory_evidence(prepared, request, exchange)
            if change == "evidence":
                raise ValueError("evidence failed")
            if change == "connection":
                self.session = object()
            return value

        def inventory_network_evidence(self):
            value = super().inventory_network_evidence()
            if change == "network_digest" and value:
                value[-1]["response_sha256"] = "a" * 64
            return value

        async def cleanup(self, prepared):
            value = await super().cleanup(prepared)
            if change == "cleanup":
                value["returncode"] = 1
            return value

    prepared = make_prepared(tmp_path)
    backend = Failure()
    result = asyncio.run(execute_inventory_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED" and result["error"]
    assert backend.closed == 1 and not prepared.key_path.exists()
    attempt = prepared.directory.with_name("openttd-15.3-industry-inventory-real-attempt1")
    assert json.loads((attempt / "inventory-observation.json").read_text())["complete"] is False


@pytest.mark.parametrize(
    "name", ["page-receipts.jsonl", "gamescript-page-evidence.jsonl", "inventory-observation.json"]
)
def test_retention_failure_still_reaps_and_removes_credential(tmp_path, monkeypatch, name):
    from app.simulation.openttd.proof import inventory_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledInventoryBackend()
    original_json = inventory_attempt.write_json
    original_lines = inventory_attempt.json_lines

    def write(path, value):
        if path.name == name:
            raise OSError("retention failure")
        return original_json(path, value)

    def lines(path, values):
        if path.name == name:
            raise OSError("retention failure")
        return original_lines(path, values)

    monkeypatch.setattr(inventory_attempt, "write_json", write)
    monkeypatch.setattr(inventory_attempt, "json_lines", lines)
    result = asyncio.run(inventory_attempt.execute_inventory_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED"
    assert backend.closed == 1 and not prepared.key_path.exists()


@pytest.mark.parametrize("query", ["ping", "world_info", "wrong_id", "wrong_limit", "resend"])
def test_native_recorder_rejects_unapproved_requests(query):
    from test_industry_inventory import InventoryWire

    from app.simulation.openttd.gamescript_protocol import PingRequest
    from app.simulation.openttd.gamescript_transport import encode_gamescript
    from app.simulation.openttd.industry_page import IndustryPageRequest
    from app.simulation.openttd.proof.inventory_contract import INVENTORY_FIRST_REQUEST
    from app.simulation.openttd.proof.inventory_native import InventoryRecordedSession
    from app.simulation.openttd.world_info import WorldInfoRequest

    async def scenario():
        wire = InventoryWire()
        recorder = InventoryRecordedSession(wire.transport.session)
        if query == "resend":
            await recorder.send(encode_gamescript(INVENTORY_FIRST_REQUEST.to_bytes()))
        request = {
            "ping": PingRequest("no"),
            "world_info": WorldInfoRequest("no"),
            "wrong_id": IndustryPageRequest("no", None, 2),
            "wrong_limit": IndustryPageRequest(INVENTORY_FIRST_REQUEST.request_id, None, 3),
            "resend": INVENTORY_FIRST_REQUEST,
        }[query]
        with pytest.raises(ValueError):
            await recorder.send(encode_gamescript(request.to_bytes()))
        assert len(wire.requests) == int(query == "resend")

    asyncio.run(scenario())


def test_inventory_runner_rejects_over_record_budget(tmp_path):
    from app.simulation.openttd.proof.inventory_attempt import execute_inventory_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledInventoryBackend(tuple(range(33)))
    result = asyncio.run(execute_inventory_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED"
    assert backend.closed == 1 and len(backend.wire.requests) == 17
    attempt = prepared.directory.with_name("openttd-15.3-industry-inventory-real-attempt1")
    assert not json.loads((attempt / "inventory-observation.json").read_text())["complete"]


def test_proof_modules_have_no_planning_imports():
    import ast
    from pathlib import Path

    for path in Path("app/simulation/openttd/proof").glob("inventory_*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.planning")
            if isinstance(node, ast.Import):
                assert all(not n.name.startswith("app.planning") for n in node.names)


def test_preparation_preserves_existing_history(tmp_path):
    historical = tmp_path / "old-failed-proof"
    historical.mkdir()
    report = historical / "final-report.md"
    report.write_bytes(b"FAILED -- NO RETRY\n")
    prepared = make_prepared(tmp_path)
    try:
        assert report.read_bytes() == b"FAILED -- NO RETRY\n"
        history = json.loads((prepared.directory / "historical-integrity.json").read_text())
        assert (
            history["old-failed-proof"]["final-report.md"]
            == hashlib.sha256(report.read_bytes()).hexdigest()
        )
    finally:
        prepared.dispose()


def test_post_cleanup_copy_failure_keeps_failed_classification(tmp_path, monkeypatch):
    from app.simulation.openttd.proof import inventory_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledInventoryBackend()
    original = inventory_attempt.shutil.copyfile

    def fail(source, destination):
        if destination.name == "stdout.log":
            raise OSError("post-cleanup copy failed")
        return original(source, destination)

    monkeypatch.setattr(inventory_attempt.shutil, "copyfile", fail)
    result = asyncio.run(inventory_attempt.execute_inventory_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED" and backend.closed == 1
    assert result["states"][-1] == "FAILED" and not prepared.key_path.exists()
    attempt = prepared.directory.with_name("openttd-15.3-industry-inventory-real-attempt1")
    assert not json.loads((attempt / "inventory-observation.json").read_text())["complete"]
    assert not json.loads((attempt / "inventory-session.json").read_text())["complete"]
    assert (
        json.loads((attempt / "proof-evidence.json").read_text())["status"] == "CONTROLLED_FAILED"
    )


def test_missing_native_liveness_does_not_claim_page_validated(tmp_path):
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence
    from app.simulation.openttd.proof.inventory_attempt import execute_inventory_attempt

    class MissingAlive(ControlledInventoryBackend):
        async def inventory_evidence(self, prepared, request, exchange):
            value = await self.wire.evidence(request, exchange)
            raw = b"".join(
                line
                for line in value.raw_log.splitlines(keepends=True)
                if b"BRIDGE_POST_RESPONSE_ALIVE" not in line
            )
            with prepared.spec.stderr_path.open("ab") as stream:
                stream.write(raw)
            return parse_industry_page_evidence(raw, request.request_id)

    prepared = make_prepared(tmp_path)
    result = asyncio.run(execute_inventory_attempt(prepared, MissingAlive()))
    assert result["status"] == "CONTROLLED_FAILED"
    attempt = prepared.directory.with_name("openttd-15.3-industry-inventory-real-attempt1")
    page = json.loads((attempt / "page-verifications.jsonl").read_text().splitlines()[0])
    assert (
        page["record_semantics_valid"]
        and not page["gamescript_correlated"]
        and not page["page_valid"]
    )
    assert not json.loads((attempt / "inventory-observation.json").read_text())["complete"]
