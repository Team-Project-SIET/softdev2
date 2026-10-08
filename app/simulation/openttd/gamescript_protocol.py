"""Compatibility exports for the unchanged version-one wire contract."""

from app.simulation.openttd.observation_protocol import (
    _REQUEST_ID as _REQUEST_ID,
)
from app.simulation.openttd.observation_protocol import (
    MAX_PAYLOAD_BYTES as MAX_PAYLOAD_BYTES,
)
from app.simulation.openttd.observation_protocol import (
    MAX_REQUEST_ID_BYTES as MAX_REQUEST_ID_BYTES,
)
from app.simulation.openttd.observation_protocol import (
    PROTOCOL_VERSION as PROTOCOL_VERSION,
)
from app.simulation.openttd.observation_protocol import (
    Ack as Ack,
)
from app.simulation.openttd.observation_protocol import (
    BridgeProtocolError as BridgeProtocolError,
)
from app.simulation.openttd.observation_protocol import (
    CommunicationReceipt as CommunicationReceipt,
)
from app.simulation.openttd.observation_protocol import (
    MalformedMessage as MalformedMessage,
)
from app.simulation.openttd.observation_protocol import (
    PingRequest as PingRequest,
)
from app.simulation.openttd.observation_protocol import (
    _object as _object,
)
from app.simulation.openttd.observation_protocol import (
    _serialize as _serialize,
)
from app.simulation.openttd.observation_protocol import (
    _unique_object as _unique_object,
)
from app.simulation.openttd.observation_protocol import (
    handle_ping as handle_ping,
)
from app.simulation.openttd.observation_protocol import (
    validate_request_id as validate_request_id,
)
