import hashlib
import re
from pathlib import Path

import pytest

from app.simulation.openttd.proof.industry_contract import INDUSTRY_REQUEST
from app.simulation.openttd.proof.industry_evidence import parse_industry_proof_evidence


def test_attempt1_null_cursor_reproduction():
    raw = Path("tests/fixtures/industry_page_attempt1.log").read_bytes()
    response = Path("tests/fixtures/industry_page_attempt1_response.json").read_bytes()
    with pytest.raises(ValueError, match="read/send metadata mismatch"):
        parse_industry_proof_evidence(raw, INDUSTRY_REQUEST.request_id).correlate(
            INDUSTRY_REQUEST, response
        )


def test_project_formatter_handles_null_without_native_rendering():
    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute("::formatted <- NoMutationBridge().EvidenceOptionalInt(null);")
    assert str(vm.get_roottable()["formatted"]) == "null"


@pytest.mark.parametrize(
    "value,expected", [("null", "null"), ("0", "0"), ("17", "17"), ("63999", "63999")]
)
def test_optional_scalar_native_vm(value, expected):
    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(f"::formatted <- NoMutationBridge().EvidenceOptionalInt({value});")
    assert str(vm.get_roottable()["formatted"]) == expected


@pytest.mark.parametrize("value", ["true", '"17"', "17.0", "{}"])
def test_optional_scalar_rejects_non_integer(value):
    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    with pytest.raises(RuntimeError, match="non-integer evidence scalar"):
        vm.execute(f"NoMutationBridge().EvidenceOptionalInt({value});")


@pytest.mark.parametrize("value,expected", [("true", "true"), ("false", "false")])
def test_boolean_formatter(value, expected):
    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(f"::formatted <- NoMutationBridge().EvidenceBool({value});")
    assert str(vm.get_roottable()["formatted"]) == expected


@pytest.mark.parametrize(
    "ids,after,limit,expected",
    [
        (
            (),
            None,
            3,
            "after_id=null limit=3 returned_count=0 first_id=null last_id=null "
            "next_after_id=null has_more=false",
        ),
        (
            (17,),
            None,
            3,
            "after_id=null limit=3 returned_count=1 first_id=17 last_id=17 "
            "next_after_id=null has_more=false",
        ),
        (
            (31, 17, 22),
            17,
            1,
            "after_id=17 limit=1 returned_count=1 first_id=22 last_id=22 "
            "next_after_id=22 has_more=true",
        ),
    ],
)
def test_actual_handler_canonical_markers(ids, after, limit, expected):
    from test_industry_page import squirrel_page

    from app.simulation.openttd.industry_page import IndustryPageRequest
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence

    response, raw, reads = squirrel_page(ids=ids, after=after, limit=limit)
    evidence = parse_industry_page_evidence(raw, "page")
    evidence.require_complete(IndustryPageRequest("page", after, limit), response)
    marker = next(line for line in raw.decode().splitlines() if "INDUSTRY_PAGE_READ" in line)
    assert marker == "dbg: [script:4] [18] [I] INDUSTRY_PAGE_READ request_id=page " + expected
    assert not re.search(r"0x[0-9a-fA-F]+", marker)
    assert reads == len(response.industries)


@pytest.mark.parametrize(
    "token", ["(null : 0x00000000)", "(null)", "NULL", " null", "null ", "0x00000000"]
)
def test_noncanonical_null_is_strictly_rejected(token):
    raw = Path("tests/fixtures/industry_page_attempt1.log").read_bytes()
    raw = raw.replace(b"(null : 0x00000000)", token.encode())
    response = Path("tests/fixtures/industry_page_attempt1_response.json").read_bytes()
    with pytest.raises(ValueError, match="read/send metadata mismatch"):
        parse_industry_proof_evidence(raw, INDUSTRY_REQUEST.request_id).correlate(
            INDUSTRY_REQUEST, response
        )


def test_corrected_synthetic_trace_preserves_response_digest_and_partial_order():
    from app.simulation.openttd.proof.industry_contract import (
        INDUSTRY_INTERNAL_CHAIN,
        INDUSTRY_NETWORK_CHAIN,
    )

    raw = Path("tests/fixtures/industry_page_attempt1.log").read_bytes()
    corrected = raw.replace(b"after_id=(null : 0x00000000)", b"after_id=null")
    response = Path("tests/fixtures/industry_page_attempt1_response.json").read_bytes()
    evidence = parse_industry_proof_evidence(corrected, INDUSTRY_REQUEST.request_id).correlate(
        INDUSTRY_REQUEST, response
    )
    assert evidence.ordered_sequence == INDUSTRY_INTERNAL_CHAIN
    assert INDUSTRY_NETWORK_CHAIN == (
        "INDUSTRY_PAGE_REQUEST_SENT",
        "INDUSTRY_PAGE_RESPONSE_RECEIVED",
        "TRANSPORT_RECEIPT_CREATED",
        "PAGE_VALIDATED",
    )
    assert evidence.response_digest == hashlib.sha256(response).hexdigest()
    assert b"(null : 0x00000000)" in raw  # Captured historical fixture remains unchanged.


@pytest.mark.parametrize("token", ["017", "+17", "0x11", "17.0", "(integer : 0x00000011)"])
def test_noncanonical_integer_cursor_is_rejected(token):
    from test_industry_page import squirrel_page

    from app.simulation.openttd.industry_page import IndustryPageRequest
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence

    response, raw, _ = squirrel_page(ids=(22, 31), after=17, limit=1)
    raw = raw.replace(b"after_id=17 ", f"after_id={token} ".encode())
    with pytest.raises(ValueError, match="read/send metadata mismatch"):
        parse_industry_page_evidence(raw, "page").require_complete(
            IndustryPageRequest("page", 17, 1), response
        )


def test_attempt_two_identity_and_canonical_policy_are_frozen(tmp_path):
    import json

    from test_industry_page_proof import make_industry_prepared

    from app.simulation.openttd.proof.industry_contract import industry_contract
    from app.simulation.openttd.proof.native import load_prepared

    prepared = make_industry_prepared(tmp_path)
    try:
        metadata_path = prepared.directory / "PRELAUNCH.json"
        metadata = json.loads(metadata_path.read_text())
        assert metadata["attempt"] == metadata["prelaunch_revision"] == 2
        assert industry_contract()["evidence_scalars"]["native_debug_representations"] is False
        metadata["attempt"] = metadata["prelaunch_revision"] = 1
        metadata_path.write_text(json.dumps(metadata))
        with pytest.raises(ValueError, match="frozen request/preparation required"):
            load_prepared(prepared.directory, mode="industry-page")
    finally:
        prepared.dispose()


def test_exact_15_3_rendering_source_authority():
    import json

    directory = Path("tests/reference/industry_evidence_15_3")
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, entry in manifest["files"].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == entry["sha256"]
    source = (directory / "sqvm.cpp").read_text()
    conversion = source.split("void SQVM::ToString", 1)[1].split("bool SQVM::StringCat", 1)[0]
    assert "case OT_NULL:" not in conversion
    assert 'fmt::format("({} : 0x{:08X})"' in conversion
    assert "ToString(obj, b);" in source
    assert 'fmt::format("{}",_integer(o))' in conversion
