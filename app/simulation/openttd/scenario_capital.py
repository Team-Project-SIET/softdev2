"""Finite scenario capital presets; planning caps and native company cash stay distinct."""

from typing import Literal

from pydantic import StrictBool, StrictInt

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract

PRESET_NAME = "high-budget-500k"
TARGET_BALANCE_GBP = 500000


def financial_preset(name: str) -> dict:
    if name != PRESET_NAME:
        raise ValueError("unsupported financial preset")
    return dict(
        name=name,
        company=0,
        target_balance_gbp=TARGET_BALANCE_GBP,
        infinite_money=False,
        loan_policy="unchanged",
        funding_policy="once-before-planning",
    )


def capital_request(request_id: str, op: str) -> dict:
    if op not in ("initialize", "read") or not request_id or len(request_id) > 64:
        raise ValueError("invalid scenario capital request")
    return dict(
        type="scenario_capital",
        protocol=1,
        request_id=request_id,
        op=op,
        company=0,
        target=TARGET_BALANCE_GBP,
        preset=PRESET_NAME,
    )


def validate_capital_response(request: dict, response: dict, *, independent: bool = False) -> dict:
    expected = capital_request(request["request_id"], request["op"])
    if request != expected:
        raise ValueError("scenario capital request differs from preset")
    if any(
        response.get(key) != expected[key]
        for key in ("type", "protocol", "request_id", "company", "target", "preset")
    ):
        raise ValueError("scenario capital response identity mismatch")
    wanted = "READ" if request["op"] == "read" else "FUNDED"
    if response.get("status") != wanted:
        raise ValueError(f"scenario capital rejected: {response.get('status')}")
    for key in (
        "balance_before",
        "balance_after",
        "loan_before",
        "loan_after",
        "delta",
        "income_before",
        "income_after",
        "expenses_before",
        "expenses_after",
        "vehicles",
    ):
        if type(response.get(key)) is not int:
            raise ValueError("scenario capital requires integer currency readback")
    if (
        response.get("infinite_money") is not False
        or response.get("completed") is not True
        or response.get("attempted") is not True
        or response.get("resumed") is not False
        or response["balance_after"] != TARGET_BALANCE_GBP
        or response["delta"] != TARGET_BALANCE_GBP - response["balance_before"]
        or response["loan_before"] != response["loan_after"]
        or response["income_before"] != response["income_after"]
        or response["expenses_before"] != response["expenses_after"]
        or response["vehicles"] != 0
    ):
        raise ValueError("scenario capital cash/loan/readback mismatch")
    if independent and request["op"] != "read":
        raise ValueError("independent capital verification requires read operation")
    return response


class ScenarioCapitalRequest(Contract):
    type: Literal["scenario_capital"] = "scenario_capital"
    protocol: Literal[1] = 1
    request_id: str
    op: Literal["initialize", "read"]
    company: Literal[0] = 0
    target: Literal[500000] = 500000
    preset: Literal["high-budget-500k"] = PRESET_NAME

    def to_bytes(self) -> bytes:
        capital_request(self.request_id, self.op)
        return canonical_bytes(self)


class ScenarioCapitalReadback(Contract):
    type: Literal["scenario_capital"]
    protocol: Literal[1]
    request_id: str
    preset: Literal["high-budget-500k"]
    status: str
    company: StrictInt
    target: StrictInt
    balance_before: StrictInt
    balance_after: StrictInt
    loan_before: StrictInt
    loan_after: StrictInt
    delta: StrictInt
    infinite_money: StrictBool
    attempted: StrictBool
    completed: StrictBool
    resumed: StrictBool
    income_before: StrictInt
    income_after: StrictInt
    expenses_before: StrictInt
    expenses_after: StrictInt
    vehicles: StrictInt

    @classmethod
    def parse_for(cls, request: ScenarioCapitalRequest, raw: bytes):
        response = cls.model_validate_json(raw)
        validate_capital_response(
            request.model_dump(), response.model_dump(), independent=request.op == "read"
        )
        return response


def verify_capital(initial: ScenarioCapitalReadback, check: ScenarioCapitalReadback) -> dict:
    for response, op in ((initial, "initialize"), (check, "read")):
        request = capital_request(response.request_id, op)
        validate_capital_response(request, response.model_dump(), independent=op == "read")
    initial_fields = initial.model_dump(exclude={"request_id", "status"})
    if initial_fields != check.model_dump(exclude={"request_id", "status"}):
        raise ValueError("independent capital read differs from initialization")
    return dict(**initial_fields, independently_verified=True)
