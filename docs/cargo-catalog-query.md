# OpenTTD 15.3 structural cargo catalog (controlled V1)

Checkpoint baseline: `0f8dd6f89d55c9390873b59163085729407ac74b`.
The complete V4 inventory/capability real proof passed before this slice. This
catalog implementation is controlled only. Real native catalog binding is **NOT
YET PROVEN**. No OpenTTD gameplay launch, live Admin connection or real request
is part of this work. Historical proofs and preparation identities remain immutable.

## Purpose and boundary

An industry capability contains cargo IDs, not cargo definitions. A separate
`CargoCatalogObservation` gives those IDs stable structural meaning without repeating
strings in every industry response. `IndustryInventoryObservation`,
`IndustryCapabilityObservation` and the catalog can feed a future prepared-world
observation. Transport does not import or call P08. There is no production-history,
income, payment, refit, engine, station-acceptance, stockpile or analytics query.

## Exact 15.3 authority

Pinned source hashes and URLs are in
[the source manifest](../tests/reference/cargo_catalog_15_3/manifest.json).

- [ScriptCargoList implementation](https://raw.githubusercontent.com/OpenTTD/OpenTTD/15.3/src/script/api/script_cargolist.cpp)
  enumerates `CargoSpec::Iterate()` (valid active specs), not validity-probing all slots.
- [ScriptCargo API](https://raw.githubusercontent.com/OpenTTD/OpenTTD/15.3/src/script/api/script_cargo.hpp)
  and [implementation](https://raw.githubusercontent.com/OpenTTD/OpenTTD/15.3/src/script/api/script_cargo.cpp)
  expose `IsValidCargo`, `GetCargoLabel`, `IsFreight`, `GetTownEffect`, `HasCargoClass`
  to both AI and game scripts.
- The pinned export generator replaces the `Script` prefix with `GS`, preserving
  method and enum constant names: `GSCargoList`, `GSCargo` and `GSCargo.CC_*`.
  `GSList.Sort(GSList.SORT_BY_ITEM, GSList.SORT_ASCENDING)` orders item IDs ascending.
- The optional-string return binding pushes the returned `std::string` as a
  length-aware `std::string_view`; it does not format a native object or localize it.

## Stable field semantics

`GetCargoLabel` returns four raw bytes extracted most-significant-byte first from
an unsigned 32-bit packed label. Validity is based on the cargo spec bit number;
source does not impose an ASCII-only alphabet on the label. V1 normalizes those
bytes losslessly as **eight uppercase hexadecimal digits** in `label` / `cargo_label`.
For example, native `COAL` becomes `434F414C`, and native `OIL_` becomes `4F494C5F`.
NUL, quotes and high bytes require no JSON escaping or UTF-8 interpretation after
hex encoding. Wrong length or null returned for a valid ID fails the query.

Labels uniquely identify a particular cargo within an industry set. Generic
planning should use the generic properties where they express the behavior, not
hard-code a base-game label to a planning action. NewGRFs may define different
cargoes, labels and combinations of properties. IDs may be sparse and are local
to the runtime configuration; neither numeric IDs nor labels authorize assumptions
about routes, production quantities or town requirements.

`IsFreight` is retained as `freight` / `is_freight`: it controls the freight-train
weight multiplier. It does not mean "must use truck" or "industry cargo".
`GetTownEffect` supplies a structural numeric effect: 0 NONE, 1 PASSENGERS, 2 MAIL,
3 GOODS, 4 WATER, 5 FOOD, from the exact 15.3 town-acceptance enum. This is not a
query for town goals or current growth/acceptance state.

`classes` / `cargo_classes` is **project mask v1**, with bits 0..14 corresponding,
in order, to the named Script API constants:
PASSENGERS, MAIL, EXPRESS, ARMOURED, BULK, PIECE_GOODS, LIQUID, REFRIGERATED,
HAZARDOUS, COVERED, OVERSIZED, POWDERIZED, NON_POURABLE, POTABLE, NON_POTABLE.
Each bit is determined with `GSCargo.HasCargoClass(id, GSCargo.CC_<name>)`.
The project map is frozen in `CARGO_CLASS_NAMES` and the handler. Numeric native
class semantics are not guessed. Native special bit 15 is not exposed by the
Script API and is absent from this projection. No localized cargo name is queried
or included in the canonical observation/digest.

## Page protocol and payload bound

Canonical request:

```json
{"after_id":null,"limit":2,"protocol":1,"request_id":"catalog-p001","type":"cargo_page"}
```

Response schema: protocol 1, type `cargo_page_result`, matching request_id, status
`ok`, cargoes array of `{id,label,freight,town_effect,classes}`, next_after_id, has_more.
Only exact fields and typed scalars are accepted. IDs are 0..63, unique and strictly
ascending. The native active list is sorted by ID before selection. All returned
IDs exceed after_id. A nonterminal page is full and points to its last ID; a
terminal page has has_more=false and next_after_id=null. Empty active catalogs
terminate with an empty final page. Cursor IDs need not be contiguous.

Default limit: **2**. Hard maximum: **4**. Application limit remains **512 bytes**;
GSAdmin.Send native ceiling remains **1450 bytes**.

Worst-case record, including all fields, is 76 bytes:

```json
{"classes":32767,"freight":false,"id":63,"label":"FFFFFFFF","town_effect":5}
```

The largest empty envelope is 186 bytes (64-byte safe request ID, terminal null
cursor, false has_more). With N records: `186 + 76*N + (N-1)` for N>=1.
Four records: **493 bytes**, 19-byte application headroom, 957-byte native headroom.
Five records: **570 bytes**, prohibited. Default two-record maximum: 339 bytes.
Key order cannot change length. No arbitrary input or localized strings enter
this bound. Literal serializer-length tests lock the calculation to the schema.

## Models, collection and identity

Frozen `CargoCatalogRecord`, page request/response/receipt/exchange and native
page evidence form one transaction. `GameScriptTransport.cargo_page` uses the
existing secure read-only query path, duplicate-response barrier, request-ID
correlation and operation accounting. It opens no connection.

`CargoCatalogSession` is single-use, with deterministic request IDs `<session>-pNNN`.
Default hard ceilings: 64 pages, 64 records, 32768 cumulative response bytes and
512 Admin frames. Limits may be lowered, never raised past those maxima. Timeout,
disconnect, transport ambiguity, invalid cursor, replaced connection, malformed
response or missing liveness fails the session; no retry, reconnect or resume.
Completed exchanges remain available in session failure evidence. A complete
observation exists only after one validated terminal chain and all bounds validate.
It retains ordered records, pages, receipts and raw payload digests, first/last ID,
byte/frame totals, and optional caller-supplied runtime identity/world ID. Those
provenance fields are not invented snapshot/version identifiers.

The catalog digest is SHA-256 over compact sorted-key JSON of ascending semantic
records with fields cargo_id, cargo_label, is_freight, town_effect, cargo_classes.
Page boundaries, request IDs, receipts, runtime paths, timestamps, logs, packet
boundaries and localization are excluded. Tests collect the same catalog with
multiple page sizes and require identical logical records and digest.

## Capability referential integrity and evidence

`validate_capability_catalog` accepts complete typed observations and checks every
ID in produces/accepts against the unique catalog IDs. Missing IDs invalidate the
join; no metadata is fabricated and neither input changes. Caller remains
responsible for collecting sources in the same stable runtime configuration.
No same-run integration with enrichment or P08 is added in this slice.

The catalog is another Script API query, **not an independent second source** for
industry relationships. It confirms cargo existence/metadata, not that an
industry produces or accepts it. Independent capability verification: NONE.
Production history: NOT INCLUDED.

Per-page GameScript evidence is BRIDGE_REQUEST_RECEIVED -> CARGO_PAGE_READ ->
BRIDGE_RESPONSE_SENT -> BRIDGE_POST_RESPONSE_ALIVE. The typed compact read marker
retains cursor, limit, returned count, first/last ID, next cursor and has_more.
Python evidence is CARGO_PAGE_REQUEST_SENT -> CARGO_PAGE_RESPONSE_RECEIVED ->
TRANSPORT_RECEIPT_CREATED -> CARGO_PAGE_VALIDATED. Receipts bind raw request and
response SHA-256; the native log digest binds the retained local marker chain.
The native API does not independently emit the response-payload SHA-256.

Session evidence is CARGO_CATALOG_SESSION_STARTED -> validated pages ->
FINAL_PAGE_VALIDATED -> CARGO_CATALOG_ASSEMBLED -> CARGO_CATALOG_SESSION_COMPLETED.
Evidence validates local partial orders and correlation, never a global ordering
of timestamps from separate processes.

The SQVM tests execute the real handler against controlled, source-checked API
fixtures, including raw label bytes, sorting, sparse lists, classes and liveness.
They do not execute OpenTTD's generated native wrappers or CargoSpec storage and
cannot establish real native binding, native JSON serialization or stable-world
behavior. Those require a separately prepared and authorized real catalog proof.
Historical V4 bridge/transaction fixtures retain the old exact contract instead
of altering its digest to match the new catalog handler.
