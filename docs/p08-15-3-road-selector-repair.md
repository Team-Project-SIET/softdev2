# Controlled ordinary-road selector repair

The consumed real attempt `terrain-single-page-699fc83ba4814b39bb6b6f055b896fae`
used seal `db06fcacccda05c0ef2559948b6f18d24dfb372d95e3ca4b3d2b3d6713052f6b`.
It launched once, connected once and sent one application request, but failed
with `UNSUPPORTED_ROAD_TYPE` before tile observations. Cleanup passed. Its records
remain immutable and the attempt cannot be reused. Native tile facts remain unproven.

Tagged OpenTTD 15.3 `ScriptStorage` initializes its road selector to internal
`INVALID_ROADTYPE=63`. This differs from API `ROADTYPE_INVALID=-1`.
`GSRoad.GetCurrentRoadType()` reads this script setting, not a tile's road type.
The handler formerly required selector 0 without establishing it. The controlled
fixture started at 0 and masked native startup. Diagnosis reconstructed the error
envelope with `failed_tile=null`; its encoded frame SHA256 matched retained accounting.

Each `tile_facts_page` now checks `GSRoad.ROADTYPE_ROAD` availability, calls
`SetCurrentRoadType(ROADTYPE_ROAD)`, then verifies an integer selector equal to
that constant. Unavailable road types and failed selection reject before tile reads.
The setter changes script-local selection only: no company switch, construction
command or game-map mutation is introduced. Availability uses the current valid
deity/company context. Deity availability considers introduction and hidden-type
rules; company availability considers the company's available road types.

The existing compact `road0` remains a presence bit. `road` conservatively combines
road-tile, road-transport and ordinary-road presence predicates. Tram/custom road
occupancy must not become vacant or buildable, and is not admitted as ordinary-road
reuse. Unknown native scalars and getter exceptions fail acquisition. Directed
connectivity is still assessed only for in-region neighbors with ordinary-road
presence, using the selected road category; this does not prove engine routing.
Python parsing and P08 placement/corridor exclusions are unchanged.

Explicit read-call accounting remains six page overhead getters plus at most
44 per tile: `5*44+6=226`. Availability and selector readback replace the former
two reads; one selector setter is additional and counted separately. As in the
existing accounting contract, internal C++ calls, arithmetic and serialization
are excluded from the getter count. The setter internally checks availability.
Request bytes remain 111, selected response bound 420, absolute ceiling 512,
query-operation cap 8, lifecycle frames 6 and post-auth cap 14. Selection adds no
wire fields or Admin frames, and no limit increases.

Controlled tests use startup selector 63, also test 0/1, unavailable ordinary road,
setter refusal, repeated operations, ordinary/tram/custom/non-road occupancy,
directed connections, invalid tiles and getter failure. The exact tagged Squirrel
VM and tagged native JSON serializer execute the production composed handler,
then Python parses and correlates the controlled response. Offline API fixtures
are not native observations and do not prove actual world facts.

This document updates the earlier design's assumption that the handler never
changes the selector; historical reports are preserved. The changed handler
invalidates source identity of prior seals without altering their bytes. Fresh
preparation, one new immutable seal, separate direct operator authorization and
a new attempt are required before any future real proof. None is created here.

Authority: tagged [storage](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/script_storage.hpp),
[road implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_road.cpp)
and [road API](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_road.hpp).
