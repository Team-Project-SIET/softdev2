"""Canonical requests use the existing encrypted freight transport and wire bounds."""

import asyncio
import json
import struct
from types import SimpleNamespace

import pytest

from app.simulation.openttd.freight_canonical_dispatch import BoundaryRequest
from app.simulation.openttd.freight_canonical_runtime import CanonicalPage, CanonicalRequest
from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript
from app.simulation.openttd.proof.freight_delivery import (
    PlannerDeliverySession,
    exchange,
    staged_package,
)
from app.simulation.openttd.secure_admin import AuthState


@pytest.mark.parametrize(
    "query", [CanonicalRequest("read-1", "header"), BoundaryRequest("ready-1")]
)
def test_canonical_outbound_uses_existing_active_session(query):
    session = SimpleNamespace(state=AuthState.ACTIVE)
    frame = encode_gamescript(query.to_bytes())
    PlannerDeliverySession.validate_outbound(session, frame)
    body = json.loads(query.to_bytes())
    body["extra"] = True
    with pytest.raises(ValueError):
        PlannerDeliverySession.validate_outbound(
            session, encode_gamescript(json.dumps(body).encode())
        )
    session.state = AuthState.CLOSED
    with pytest.raises(ValueError, match="active"):
        PlannerDeliverySession.validate_outbound(session, frame)


@pytest.mark.parametrize("defect", [None, "terminator", "bound", "correlation"])
def test_existing_exchange_retains_exact_canonical_wire(tmp_path, defect):
    request = CanonicalRequest("read-1", "header")
    body = json.dumps(
        dict(
            protocol=1,
            type="canonical-page-result",
            request_id="read-1",
            section="header",
            offset=0,
            status="ok",
            total=1,
            records=[{}],
            tick=10,
            economy_date=100,
            paused=True,
            restored=True,
        )
    ).encode()
    if defect == "correlation":
        body = body.replace(b'"read-1"', b'"read-2"')
    if defect == "bound":
        body += b" " * 1451
    wire = body + (b"\0" if defect != "terminator" else b"x")

    class Session:
        async def send(self, frame):
            assert frame == encode_gamescript(request.to_bytes())

        async def receive(self):
            return struct.pack("<HB", len(wire) + 3, SERVER_GAMESCRIPT) + wire

    if defect:
        with pytest.raises(ValueError):
            asyncio.run(exchange(Session(), request, tmp_path, response_type=CanonicalPage))
    else:
        response = asyncio.run(exchange(Session(), request, tmp_path, response_type=CanonicalPage))
        assert response.request_id == request.request_id
        assert (tmp_path / "read-1-response.json").read_bytes() == body
    assert (tmp_path / "read-1-request.json").read_bytes() == request.to_bytes()


def test_canonical_staging_is_opt_in():
    normal = staged_package(True, True, True, "high-budget-500k", 3, 5)
    canonical = staged_package(True, True, True, "high-budget-500k", 3, 5, canonical=True)
    assert "canonical-parent.nut" not in normal
    assert "canonical-collector.nut" not in normal
    assert canonical["canonical-parent.nut"] == normal["main.nut"]
    assert b'"CanonicalFreightProof"' in canonical["info.nut"]
    with pytest.raises(ValueError, match="requires"):
        staged_package(True, canonical=True)
