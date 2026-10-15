"""Frozen qualification proof configuration; no runtime authorization."""

import hashlib
import json

from app.simulation.openttd.qualification_clock import EconomyClockRequest
from app.simulation.openttd.qualification_policy import qualification_resource_contract

PRELAUNCH_DIRECTORY = "openttd-15.3-two-rollover-qualification-real-prelaunch-v5"
ATTEMPT_DIRECTORY = "openttd-15.3-two-rollover-qualification-real-attempt4"
KIND = "two-rollover-qualification"
REVISION = 5
MODEL = "two-rollover-qualification-correlated-channels-v1"
SESSION_ID = "openttd15-qualification-001"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def first_request():
    return EconomyClockRequest(SESSION_ID + "-clock-1")


def qualification_contract():
    resources = qualification_resource_contract()
    if tuple(
        resources[k]
        for k in (
            "clock_requests",
            "application_requests",
            "response_bytes",
            "query_operations",
            "lifecycle_frames",
            "post_auth_frames",
        )
    ) != (304, 1072, 368080, 9088, 6, 9094):
        raise ValueError("Qualification accounting changed; controlled decision required")
    return dict(
        proof_kind=KIND,
        revision=REVISION,
        session_id=SESSION_ID,
        resources=resources,
        deadline_contract={
            "overall": "300 seconds from collect entry, including polling and collections",
            "polling": "same fixed overall deadline; no renewal after rollover",
            "request": "fresh relative timeout at each query, min(5, remaining overall)",
            "evidence": "fresh relative timeout at each callback, min(5, remaining overall)",
            "structural": (
                "fresh single-use session constructed at phase entry; no absolute phase deadline"
            ),
        },
        dispatch_contract="15.3 Squirrel explicit RawObservationBridge.Handle.call(this, request)",
        baseline_request=json.loads(first_request().to_bytes()),
        phase_order=[
            "baseline",
            "first_poll",
            "anchor_structural",
            "anchor_lifetime",
            "second_poll",
            "final_structural",
            "final_lifetime",
            "production",
            "final_guard",
            "qualification",
        ],
        native_clock={
            "C++": [
                "ScriptDate::" + n
                for n in ("GetCurrentDate", "GetYear", "GetMonth", "GetDayOfMonth", "GetDate")
            ],
            "GameScript": [
                "GSDate." + n
                for n in ("GetCurrentDate", "GetYear", "GetMonth", "GetDayOfMonth", "GetDate")
            ],
            "domain": (
                "economy ordinal; Gregorian conversion only in "
                "synchronized generated calendar profile"
            ),
            "api_types": {
                "GetCurrentDate": "() -> ScriptDate::Date, GameScript integer",
                "GetYear": "(ScriptDate::Date) -> SQInteger, GameScript integer",
                "GetMonth": "(ScriptDate::Date) -> SQInteger, 1-based integer",
                "GetDayOfMonth": "(ScriptDate::Date) -> SQInteger, 1-based integer",
                "GetDate": "(SQInteger year, month, day) -> ScriptDate::Date integer",
            },
            "invalid": (
                "negative date components return -1; unavailable next-month date rejects sample"
            ),
            "conversion": "TimerGameEconomy ConvertDateToYMD / ConvertYMDToDate",
            "year_zero": "Gregorian leap year; December wraps to January of next year",
            "date_role": "current native economy state, not elapsed wall-clock evidence",
            "year_range": [0, 5000000],
            "month_range": [1, 12],
            "day_range": [1, 31],
            "adjacency": "exact next month, including December->January; observed day 1",
            "brackets": "current capture metadata; equal allowed; never qualified month boundaries",
        },
        lifetime={
            "C++": "ScriptIndustry::GetConstructionDate",
            "GameScript": "GSIndustry.GetConstructionDate",
            "domain": "CALENDAR identity, -1 unavailable/invalid",
            "target": "ascending unique industries in produces targets",
            "rule": (
                "exact identity and fingerprint equality; "
                "conservative pre-M1 calendar construction eligibility"
            ),
        },
        profile={
            "timekeeping_units": 0,
            "starting_year": 1950,
            "no_newgrf": True,
            "generated_world": True,
            "calendar_synchronized": True,
            "normal_network_speed": True,
            "no_load_save": True,
        },
        stability="T1 == T2 and L1 == L2; no intersection or omitted targets",
        zero_targets_allowed=True,
        qualified_month="M1",
        final_month="M2",
        final_source="fresh M2 structural digest",
        initial_production_used=False,
        clocks_semantic=True,
        wall_clock_role="bounded operational liveness only",
        qualification=(
            "complete coverage + adjacent M0/M1/M2 + native evidence + stability + "
            "fresh M2 collection + final M2 guard + all budgets"
        ),
        production_level="DEFERRED / NOT INCLUDED",
        production_response_bound=335,
        application_payload=512,
        native_payload_ceiling=1450,
        launches=1,
        connections=1,
        retries=0,
        reconnects=0,
        resume=False,
        phase_transition_frames=0,
        admission_frames=0,
        evidence_frames=0,
        continuous_accounting=True,
        continuous_lineage=True,
        atomic_snapshot=False,
        pre_decision=True,
        p08_integration=False,
        future_destination=ATTEMPT_DIRECTORY,
    )
