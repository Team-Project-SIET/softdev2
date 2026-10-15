# OpenTTD 13.4 Admin protocol test provenance

The packet bytes assembled in `tests/test_admin_protocol.py` are **synthesized
source-derived fixtures**. They were reconstructed with `struct.pack` from the
OpenTTD 13.4 tag, and are not captured wire traces. The earlier prototype has a
decoded real-session example in `prototype/live_admin/proof.json`; it does not
provide raw packet bytes for these tests.

Source definitions used:

- [Admin Network documentation](https://github.com/OpenTTD/OpenTTD/blob/13.4/docs/admin_network.md): framing, update frequencies, version guidance.
- [Packet declarations](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/core/tcp_admin.h): packet IDs and declared fields.
- [Admin packet serialization](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/network_admin.cpp): actual Protocol, Welcome, CompanyInfo, CompanyEconomy and CompanyStats field order and values.
- [Packet primitives](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/core/packet.cpp): little-endian integers, booleans and NUL-terminated strings.
- [Network bounds](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/core/config.h): TCP MTU and Admin protocol version.
- [OpenTTD day type](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/date_type.h): day numbering and year-zero leap rule.

The synthetic examples deliberately include negative signed money, both
completed-quarter history slots, cargo value 65535, every exposed statistics
category, fragmented/coalesced frames, unknown IDs, trailing fields and malformed
frames. These assert the source-defined layout without claiming a real-session
capture.
