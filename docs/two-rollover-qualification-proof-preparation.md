# OpenTTD 15.3 two-rollover qualification proof preparation

Public mode: `python -m app.simulation.openttd.proof --mode two-rollover-qualification`.
The public owner validates the immutable preparation, distinct attempt lineage,
shared ownership graph, native authority, polling policy and accounting before
EndpointReservation.allocate and the final subprocess boundary. Guarded preflight
blocks subprocess creation. Preparation itself performs no native runtime activity.

The controlled coordinator is unchanged: M0 baseline, adjacent first-day M1,
M1 structural/lifetime anchor, adjacent first-day M2, fresh final structural and
lifetime observations, exact target/lifetime stability, fresh complete production,
final M2 guard, then qualification. Zero stable produced targets remain valid.
Dedicated native rollover evidence bounds M1; production brackets capture current M2
state. Construction identity is CALENDAR-domain data, not economy qualification time.
The restricted generated synchronized-calendar/no-NewGRF profile is mandatory.

Polling cadence is one second. Collection deadline is 300 seconds; paced requests
start strictly before the deadline. ceil(300/1)-1=299 shared paced polls plus baseline
and four guards gives 304 clocks. Operational time controls bounded liveness only.
Native date transitions establish qualification. Skips, regressions, lineage changes,
anchor/final month crossing, instability, incomplete evidence and budget overflow fail.

Independent phase request/byte/query limits:

| Phase | Requests | Bytes | Query operations |
|---|---:|---:|---:|
| Clock | 304 | 82384 | 2432 |
| Anchor structural | 96 | 49152 | 1024 |
| Anchor lifetime | 32 | 7936 | 256 |
| Final structural | 96 | 49152 | 1024 |
| Final lifetime | 32 | 7936 | 256 |
| Final production | 512 | 171520 | 4096 |
| Total | 1072 | 368080 | 9088 |

The existing native observer counts one continuous session: two establishment,
three subscription/barrier frames and one graceful QUIT. 9088+6=9094. Phase changes,
rollover transitions, Python evidence and qualification admission add zero frames.
No reset, borrowing, retry, reconnect or resume is permitted.

The future evidence destination is exactly
`artifacts/runtime/openttd-15.3-two-rollover-qualification-real-attempt1/`.
Final proof PASS is permitted only after owned cleanup, process reap, endpoints
closed, credential removal, workspace disposal, persistent/history integrity and
COMPLETED. The controlled semantic coordinator's completion alone is insufficient.
Partial native evidence is retained truthfully on failure and cannot qualify.

Native APIs and tagged source identities are retained in qualification-native-authority.json.
The bridge is derived from the proven raw package plus the thin qualification adapter;
the old package and historical proofs remain unchanged. No GameScript qualification
state or polling is added. Existing production protocol and 335-byte bound are preserved;
production_level remains deferred/excluded. Observation is non-atomic and PRE-DECISION.
P08 adaptation and optimizer execution remain excluded. Real qualification is unproven
until a separately authorized one-attempt native proof succeeds.
