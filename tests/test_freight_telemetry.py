import json

import pytest

from app.simulation.openttd.freight_telemetry import (
    SampleWindow,
    decode_telemetry,
    telemetry_request,
)


def read(tick=1, load=20, tile=10, **changes):
    q = telemetry_request(f"t-{tick}", 1, 7)
    value = dict(
        protocol=1,
        type="continuous-telemetry-result",
        status="ok",
        request_id=f"t-{tick}",
        service=1,
        vehicle=7,
        tick=tick,
        economy_date=100,
        tile=tile,
        state=1,
        speed=0,
        load=load,
        capacity=20,
        queue=1000,
        stopped_in_depot=False,
        at_station=False,
        source_tile=10,
        destination_tile=20,
    )
    value.update(changes)
    return decode_telemetry(json.dumps(value).encode(), q)


def test_point_samples_infer_bracketed_changes_never_completed_delivery():
    window = SampleWindow(10)
    window.append(read())
    window.append(read(5, 0, 20))
    report = window.report()
    assert report["transitions"][0] == dict(
        evidence="inferred_between_samples",
        from_tick=1,
        to_tick=5,
        labels=["net_load_decrease", "possible_source_departure", "possible_destination_arrival"],
        net_load_change=-20,
    )
    assert report["cargo_per_completed_cycle"] is None
    assert report["completed_delivery_frequency"] is None
    assert report["idle_time"] is None
    assert report["servicing_time"] is None


def test_gap_suppresses_transition_inference():
    window = SampleWindow(2)
    window.append(read())
    window.append(read(5, 0, 20))
    assert window.report()["transitions"][0]["labels"] == ["sampling_gap"]
    assert window.report()["transitions"][0]["net_load_change"] is None


@pytest.mark.parametrize(
    "changes",
    [dict(load=21), dict(queue=-1), dict(vehicle=9), dict(tick=True), dict(protocol=True)],
)
def test_reject_invalid_samples(changes):
    with pytest.raises(ValueError):
        read(**changes)


def test_duplicates_size_identity_and_finite_budgets():
    q = telemetry_request("t-1", 1, 7)
    with pytest.raises(ValueError, match="duplicate"):
        decode_telemetry(b'{"protocol":1,"protocol":1}', q)
    with pytest.raises(ValueError, match="bound"):
        decode_telemetry(b" " * 1451, q)
    window = SampleWindow(10, max_samples=1)
    window.append(read())
    with pytest.raises(ValueError, match="budget"):
        window.append(read(2))
    window = SampleWindow(10)
    window.append(read())
    with pytest.raises(ValueError, match="clock"):
        window.append(read())
    with pytest.raises(ValueError, match="identity"):
        window.append(read(2, capacity=30))


def test_depot_presence_does_not_claim_servicing():
    window = SampleWindow(10)
    window.append(read())
    window.append(read(2, stopped_in_depot=True))
    assert window.report()["transitions"][0]["labels"] == ["stopped_in_depot_change"]
    assert window.report()["servicing_time"] is None


def test_candidate_cycle_carries_sampled_load_and_retains_censoring():
    window = SampleWindow(10)
    window.append(read(1, 20, 10, at_station=True))
    window.append(read(2, 20, 15))
    window.append(read(3, 0, 20, at_station=True))
    report = window.report()
    assert report["candidate_cycles"] == [
        dict(
            evidence="inferred_censored_candidate_cycle",
            departure=dict(from_tick=1, to_tick=2, carried_at_last_source_sample=20),
            unloading_interval=[2, 3],
            observed_net_load_decrease=20,
            missed_cycles_possible=True,
        )
    ]
    assert report["inferred_candidate_cycles_per_script_tick"] == 0.5
    assert report["transitions"][-1]["labels"][-1] == "possible_unloading_episode"
    assert report["queue_series"][-1] == dict(tick=3, economy_date=100, queue=1000)
    assert report["zero_speed_sample_count"] == 3
    assert report["completed_delivery_frequency"] is None


def test_sampling_gap_discards_pending_candidate_cycle():
    window = SampleWindow(2)
    window.append(read(1, 20, 10))
    window.append(read(2, 20, 15))
    window.append(read(9, 20, 19))
    window.append(read(10, 0, 20, at_station=True))
    assert window.report()["candidate_cycles"] == []


def test_native_depot_readback_names_only_stopped_in_depot():
    from pathlib import Path

    source = Path("app/simulation/openttd/freight_delivery_package/continuous.nut").read_text()
    assert "stopped_in_depot=GSVehicle.IsInDepot(v)" in source
    assert "stopped_in_depot_change" not in source


@pytest.mark.parametrize(
    "changes", [dict(stopped_in_depot=True, speed=1), dict(stopped_in_depot=True, at_station=True)]
)
def test_reject_incoherent_stopped_depot_state(changes):
    with pytest.raises(ValueError, match="coherence"):
        read(**changes)


def test_first_sample_cannot_bypass_measurement_validation():
    sample = read().model_copy(update={"queue": -1})
    with pytest.raises(ValueError, match="measurement"):
        SampleWindow(10).append(sample)


def telemetry_vm():
    from pathlib import Path

    from squirrel import SQVM

    vm = SQVM()
    vm.execute("""
        ::owner <- 0; ::orders <- 2; ::capacity <- 20; ::replies <- [];
        class NetworkFreightProof {
            services=null;
            function GetTick() { return 10; }
            /* continuous.nut resolves NetworkFreightProof.PrepareDemo at class evaluation
                time (real parent defines it in network.nut); these tests exercise the
                telemetry Handle seam, so an inert member satisfies the binding. */
            function PrepareDemo() {}
        }
        class GSCompanyMode {
            constructor(c) {}
            static function IsValid() { return true; }
        }
        class GSVehicle {
            static VS_AT_STATION=3;
            static function IsValidVehicle(v) { return v==7||v==2; }
            static function GetOwner(v) { return ::owner; }
            static function GetEngineType(v) { return 4; }
            static function GetCapacity(v,c) { return ::capacity; }
            static function GetLocation(v) { return 10; }
            static function GetState(v) { return 3; }
            static function GetCurrentSpeed(v) { return 0; }
            static function GetCargoLoad(v,c) { return 20; }
            static function IsInDepot(v) { return false; }
            static function GetProfitThisYear(v) { return 3; }
            static function GetProfitLastYear(v) { return 2; }
            static function GetRunningCost(v) { return 421; }
        }
        class GSOrder {
            static OF_FULL_LOAD=1; static OF_NO_LOAD=2;
            static function GetOrderCount(v) { return ::orders; }
            static function GetOrderDestination(v,n) { return n==0?10:20; }
            static function IsGotoStationOrder(v,n) { return true; }
            static function GetOrderFlags(v,n) { return n==0?1:2; }
        }
        class GSStation {
            static function GetStationID(t) { return t; }
            static function GetCargoWaiting(s,c) { return 1000; }
        }
        class GSDate { static function GetCurrentDate() { return 100; } }
        class GSAdmin { static function Send(r) { ::replies.append(r); return true; } }
        class GSLog { static function Info(t) {} }
    """)
    source = Path("app/simulation/openttd/freight_delivery_package/continuous.nut").read_text()
    vm.execute(source.replace('require("continuous-parent.nut");', ""))
    vm.execute("""
        ::b <- ContinuousFreightProof(); b.cbegun=true;
        b.capacity_vehicle=7;b.capacity_service=1;
        b.services=[null,{dvehicle=2,choice={a=[0,1,2,0,10,0,20]}},null];
        ::q <- {protocol=1,type="continuous-telemetry",request_id="t-1",service=1,vehicle=7};
    """)
    return vm


def test_actual_squirrel_producer_decodes_and_rejects_duplicate():
    vm = telemetry_vm()
    vm.execute("b.Handle(q);")
    reply = vm.get_roottable()["replies"][0]
    raw = json.dumps({str(k): reply[k] for k in reply.keys()}).encode()
    sample = decode_telemetry(raw, telemetry_request("t-1", 1, 7))
    assert (sample.queue, sample.load, sample.capacity, sample.at_station) == (1000, 20, 20, True)
    assert not sample.stopped_in_depot
    assert len(raw) <= 1450
    vm.execute("b.Handle(q);")
    assert vm.get_roottable()["replies"][1]["error"] == "TELEMETRY_REQUEST_BUDGET"


@pytest.mark.parametrize(
    "setup,error",
    [
        ("b.tpolls=20000;", "TELEMETRY_REQUEST_BUDGET"),
        ("::owner=1;", "TELEMETRY_VEHICLE_IDENTITY"),
        ("::orders=3;", "TELEMETRY_VEHICLE_IDENTITY"),
        ("::capacity=0;", "TELEMETRY_VEHICLE_IDENTITY"),
    ],
)
def test_actual_squirrel_producer_rejects_budget_and_invalid_identity(setup, error):
    vm = telemetry_vm()
    vm.execute(setup + "b.Handle(q);")
    assert vm.get_roottable()["replies"][0]["status"] == "rejected"
    assert vm.get_roottable()["replies"][0]["error"] == error


def test_actual_squirrel_rejects_unbound_vehicle_with_identical_orders():
    vm = telemetry_vm()
    vm.execute("b.capacity_vehicle=-1;b.capacity_service=-1;b.Handle(q);")
    assert vm.get_roottable()["replies"][0]["error"] == "TELEMETRY_VEHICLE_IDENTITY"
