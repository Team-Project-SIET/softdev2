"""Execute the actual thin adapter in Squirrel; native APIs are controlled stubs."""

import json
from pathlib import Path

import pytest
from squirrel import SQVM
from test_two_rollover_qualification import reading

from app.simulation.openttd.gamescript_protocol import BridgeProtocolError
from app.simulation.openttd.qualification_bridge import (
    qualification_bridge_source,
    stage_qualification_bridge,
)
from app.simulation.openttd.qualification_clock import (
    EconomyClockRequest,
    IndustryLifetimeRequest,
    NativeReadReceipt,
    NativeReadResponse,
)


def vm_for(sample=None, construction=1):
    sample = sample or reading(month=2)
    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(f"""
        ::date <- {sample.economy_date}; ::year <- {sample.economy_year};
        ::month <- {sample.economy_month}; ::day <- {sample.economy_day};
        ::start <- {sample.month_start}; ::end <- {sample.month_end};
        ::construction <- {construction};
                ::native_calls <- [];
        class GSDate {{
            static function GetCurrentDate() {{ ::native_calls.append("GetCurrentDate");
                return ::date; }}
            static function GetYear(d) {{ ::native_calls.append("GetYear");
                if(d!=::date) throw "wrong date";
                return ::year; }}
            static function GetMonth(d) {{ ::native_calls.append("GetMonth");
                if(d!=::date) throw "wrong date";
                return ::month; }}
            static function GetDayOfMonth(d) {{ ::native_calls.append("GetDayOfMonth");
                if(d!=::date) throw "wrong date";
                return ::day; }}
            static function GetDate(y,m,d) {{ ::native_calls.append("GetDate");
                if(d!=1) throw "wrong day";
                if(y==::year && m==::month) return ::start;
                if(y==(::month==12 ? ::year+1 : ::year) &&
                     m==(::month==12 ? 1 : ::month+1)) return ::end;
                throw "wrong boundary"; }}
        }}
        class GSIndustry {{
            static function IsValidIndustry(id) {{ return id==2; }}
            static function GetConstructionDate(id) {{ ::native_calls.append("GetConstructionDate");
                if(id!=2) return -1;
                return ::construction; }}
        }}
    """)
    vm.execute(qualification_bridge_source())
    return vm


def reply(vm):
    response = vm.get_roottable()["replies"][0]
    keys = [str(k) for k in response.keys()]
    return json.dumps(
        {
            k: str(response[k]) if k in ("type", "status", "request_id") else int(response[k])
            for k in keys
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


@pytest.mark.parametrize(
    "sample", [reading(), reading(day=15), reading(1950, 12), reading(2000, 2, 29)]
)
def test_actual_clock_handler_fields_and_exact_native_calls(sample):
    vm = vm_for(sample)
    vm.execute(
        '::b <- NoMutationBridge(); b.Handle({protocol=1,type="economy_clock",request_id="clock"});'
    )
    q = EconomyClockRequest("clock")
    assert NativeReadResponse.parse_for(q, reply(vm)).reading == sample
    assert [str(v) for v in vm.get_roottable()["native_calls"]] == [
        "GetCurrentDate",
        "GetYear",
        "GetMonth",
        "GetDayOfMonth",
        "GetDate",
        "GetDate",
    ]


@pytest.mark.parametrize("construction", [0, 1, 2147483647])
def test_actual_lifetime_native_calendar_identity_not_economy_date(construction):
    vm = vm_for(construction=construction)
    vm.execute(
        "::b <- NoMutationBridge(); "
        'b.Handle({protocol=1,type="industry_lifetime",request_id="life",industry_id=2});'
    )
    q = IndustryLifetimeRequest("life", 2)
    assert NativeReadResponse.parse_for(q, reply(vm)).reading.construction_date == construction
    assert [str(v) for v in vm.get_roottable()["native_calls"]] == [
        "GetCurrentDate",
        "GetConstructionDate",
        "GetCurrentDate",
    ]
    NativeReadReceipt.correlate(q.to_bytes(), reply(vm))


@pytest.mark.parametrize(
    "wire_request",
    [
        '{protocol=1,type="economy_clock",request_id="clock",extra=1}',
        '{protocol=true,type="economy_clock",request_id="clock"}',
        '{protocol=1,type="industry_lifetime",request_id="life",industry_id=3}',
        '{protocol=1,type="industry_lifetime",request_id="life",industry_id=true}',
        '{protocol=1,type="industry_lifetime",request_id="life",industry_id=-1}',
        '{protocol=1,type="industry_lifetime",request_id="life"}',
    ],
)
def test_adapter_rejects_invalid_envelopes_and_industries(wire_request):
    vm = vm_for()
    vm.execute("::b <- NoMutationBridge(); b.Handle(" + wire_request + ");")
    assert len(vm.get_roottable()["replies"]) == 0


@pytest.mark.parametrize("command", ["economy_clock", "industry_lifetime"])
def test_actual_start_loop_post_response_liveness_and_semantic_evidence(command):
    from app.simulation.openttd.qualification_clock import NativeReadExchange
    from app.simulation.openttd.qualification_evidence import parse_native_read_evidence

    vm = vm_for()
    suffix = ",industry_id=2" if command == "industry_lifetime" else ""
    vm.execute(
        '::events.append(ControlledAdminEvent({protocol=1,type="'
        + command
        + '",request_id="proof"'
        + suffix
        + "})); ::b <- NoMutationBridge(); try { b.Start(); } "
        'catch(e) {if(e!="CONTROLLED_STOP") throw e;}'
    )
    payload = reply(vm)
    q = (
        EconomyClockRequest("proof")
        if command == "economy_clock"
        else IndustryLifetimeRequest("proof", 2)
    )
    raw = "".join(
        "dbg: [script:4] [18] [I] " + str(v) + "\n" for v in vm.get_roottable()["markers"]
    ).encode()
    network = (
        command.upper() + "_REQUEST_SENT",
        command.upper() + "_RESPONSE_RECEIVED",
        "TRANSPORT_RECEIPT_CREATED",
        command.upper() + "_VALIDATED",
    )
    exchange = NativeReadExchange(
        q.to_bytes(), payload, NativeReadReceipt.correlate(q.to_bytes(), payload), network, 4
    )
    parse_native_read_evidence(raw, "proof", command).require_complete(exchange)
    assert vm.get_roottable()["ticks"] == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", "wrong"),
        ("type", "world_info_result"),
        ("economy_day", 32),
        ("economy_month", 13),
        ("economy_date", -1),
        ("month_start", 0),
        ("status", "bad"),
    ],
)
def test_response_correlation_and_clock_coherence(field, value):
    q = EconomyClockRequest("clock")
    vm = vm_for()
    vm.execute('NoMutationBridge().Handle({protocol=1,type="economy_clock",request_id="clock"});')
    obj = json.loads(reply(vm))
    obj[field] = value
    with pytest.raises((BridgeProtocolError, ValueError)):
        NativeReadResponse.parse_for(q, json.dumps(obj).encode())


def test_qualification_package_composes_in_ephemeral_workspace(tmp_path):
    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY
    from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace

    before = (BRIDGE_DIRECTORY / "main.nut").read_bytes()
    workspace = RuntimeWorkspace.create(tmp_path)
    try:
        workspace.write_config(AdminSettings(password="controlled"))
        package = stage_qualification_bridge(workspace)
        assert "GetConstructionDate" in (package.directory / "main.nut").read_text()
        assert len(package.sha256) == 64
    finally:
        workspace.close()
    assert before == (BRIDGE_DIRECTORY / "main.nut").read_bytes()


def test_native_adapter_has_no_qualification_or_polling_state():
    source = Path("app/simulation/openttd/qualification_bridge.nut").read_text()
    assert "while (" not in source and "Sleep(" not in source
    assert "qualified_for_planning" not in source and "production_level" not in source


def test_native_maximum_year_unavailable_next_month_boundary_rejected():
    from app.simulation.openttd.qualification_clock import EconomyClockReading, calendar_bounds

    start, end = calendar_bounds(5000000, 12)
    with pytest.raises(BridgeProtocolError, match="unavailable"):
        EconomyClockReading(start, 5000000, 12, 1, start, end)
