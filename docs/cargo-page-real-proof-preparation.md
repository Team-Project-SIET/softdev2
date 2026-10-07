# OpenTTD 15.3 first native cargo-page proof preparation

The public production CLI owns this proof kind:

```sh
.venv/bin/python -m app.simulation.openttd.proof prepare --mode cargo-page
.venv/bin/python -m app.simulation.openttd.proof preflight --mode cargo-page
```

Preparation and guarded preflight create no native process, Admin connection, or application request. A future `run --mode cargo-page --authorize-one-launch` requires separate explicit authorization against the exact preparation identity. No real execution is authorized by preparation.

The immutable request is protocol 1, `cargo_page`, request ID `openttd15-cargo-page-001`, null `after_id`, limit 2. The production serializer freezes its exact bytes, size and SHA-256. The destination is exactly `artifacts/runtime/openttd-15.3-cargo-page-real-attempt1/`; an alternate destination fails the gate.

The frozen V1 record contains `id`, `label`, `freight`, `town_effect`, and `classes`. This preserves the controlled catalog schema. Labels are the lossless uppercase hexadecimal encoding of the four native label bytes, including nonprintable bytes; they identify cargo within the active set. Generic planning should prefer structural properties over hard-coded labels, including for NewGRF cargoes. Freight is the Script API freight weight multiplier property. Town effect is the native structural numeric effect, not planner behavior. Classes use the existing frozen 15-bit normalized Script API mapping. Localized `GetName` and economic, dynamic, production, payment, acceptance and vehicle APIs are excluded.

Exact OpenTTD 15.3 sources and generated-binding registration excerpts are retained in `tests/reference/cargo_catalog_15_3/manifest.json`. The handler uses `GSCargoList`, sorted by `GSList.SORT_BY_ITEM` and `GSList.SORT_ASCENDING`, and `GSCargo.IsValidCargo`, `GetCargoLabel`, `IsFreight`, `GetTownEffect`, and `HasCargoClass`. Controlled SQVM execution validates the handler against those API fixtures; real native catalog bindings remain unproven.

The generic maximum is 4 records: 186-byte worst-case envelope plus four 76-byte records and three commas equals 493 bytes. Default remains 2. The fixed proof request ID gives a 146-byte envelope: two 76-byte records plus one comma equals 299 bytes. Headroom is 213 bytes below the 512-byte application limit; the native ceiling stays 1450 bytes. Terminal null cursor and false `has_more` maximize the envelope. The proof cannot increase its limit.

Generic empty catalog pages are valid. This proof requires at least one record so it actually exercises metadata bindings. Frozen support consists of the prior successful V4 native capability reads of valid cargo IDs under the identical pinned binary, graphics and generation configuration. This support is not independent same-run catalog equivalence. Any protocol-valid terminal first page can pass; `has_more=true` is not required. This proof never assembles or claims a complete catalog.

Lifecycle: PREPARED → LAUNCHED → ADMIN_ACTIVE → CARGO_PAGE_REQUEST_SENT → CARGO_PAGE_RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED → CARGO_PAGE_VALIDATED → POST_RESPONSE_LIVENESS_VERIFIED → COMPLETED, or explicit FAILED. EndpointReservation owns loopback availability. The production backend owns one process, one continuous secure X25519 Admin connection, and exactly one application request. Retries, reconnect, resend, other queries and gameplay mutation are prohibited. Cleanup closes Admin, stops and reaps the process, verifies endpoint closure, and removes the fresh private credential. Private key bytes are mode 0600 and excluded from public evidence.

Transport receipt correlation is separate from metadata/cursor validation. Immutable CargoPageVerification retains request/response digests, cursor, limit, record count and IDs, payload size, semantic flags, and runtime/bridge identities. GameScript evidence is BRIDGE_STARTED → BRIDGE_REQUEST_RECEIVED → CARGO_PAGE_READ → BRIDGE_RESPONSE_SENT → BRIDGE_POST_RESPONSE_ALIVE. Python/Admin evidence is CARGO_PAGE_REQUEST_SENT → CARGO_PAGE_RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED → CARGO_PAGE_VALIDATED. Correlation binds typed metadata and response digest; ordering applies locally, never as a global cross-process clock order.

Attempt identities include proof kind `cargo-page`. Enrichment failures are not cargo-page predecessors. Unknown relevant cargo-page failures fail prelaunch; continuation requires a newer frozen revision, exact acknowledged PRELAUNCH predecessor evidence with activity 0/0/0, and fresh authorization. Runtime failures cannot enter the harmless-prelaunch lineage exception. No force/ignore mechanism exists.

Independent second-source cargo catalog: NONE. Independent capability verification: NONE. Production history: NOT INCLUDED. P08 completion: NO. Neither transport nor this proof couples to P08.
