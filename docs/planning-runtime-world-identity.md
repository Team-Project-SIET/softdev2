# P03 world identity boundary

The full prepared-world manifest hash is unchanged. It binds save provenance,
planner labels, candidate facilities and runtime facts. The setup receipt's v1
`world_fingerprint` continues to mean that full manifest identity.

Runtime identity v1 is a distinct projection: width, height, generation seed,
and the set of required existing industry/station objects (kind, object ID,
x and y). Unbuilt candidates and planner/provenance metadata are excluded. It
identifies these required world facts, not every tile or every object in a save.

`runtime_projection_from_manifest` produces expected facts. `runtime_world_hash`
sorts objects by (kind, object_id), then uses existing `canonical_bytes` and
SHA-256. Objects must be nonempty, unique and within the map. Integer values
remain JSON integers. The canonical schema includes `schema_version: 1`.

The script observation envelope is:

```
P03_EXECUTOR_AI|P03_RUNTIME_WORLD_V1|<plan_hash>|<width>|<height>|<seed>|<kind>:<id>:<x>:<y>,...
```

The plan hash only correlates the envelope; it is not a runtime hash input.
Dimensions use AIMap.GetMapSizeX/Y. Seed uses AIGameSettings.GetValue after
IsValid. Object locations use AIIndustry/AIStation.GetLocation after validity
checks. Station IDs are obtained again from the returned tile via GetStationID.
Industry IDs are obtained from AIIndustryList before
GetLocation. This matters because AIIndustry.GetLocation returns the bounding-box
origin, which is not guaranteed to be an industry tile for irregular layouts and
therefore is not a valid input for a reverse GetIndustryID query. Coordinates use
AIMap.GetTileX/Y. Kind is the API namespace whose query succeeded. Expected object
IDs select the queries; the emitted ID must also be present in the runtime list.

Resolution failures use a separate bounded `P03_WORLD_RESOLUTION_V1` diagnostic.
It records the plan hash, reason code, planned site identifier and kind, expected
ID and coordinates, and the observed value. The terminal receipt remains the
authoritative failed outcome.

OpenTTD 13.4 declarations:

- https://github.com/OpenTTD/OpenTTD/blob/13.4/src/script/api/script_map.hpp
- https://github.com/OpenTTD/OpenTTD/blob/13.4/src/script/api/script_gamesettings.hpp
- https://github.com/OpenTTD/OpenTTD/blob/13.4/src/script/api/script_industry.hpp
- https://github.com/OpenTTD/OpenTTD/blob/13.4/src/script/api/script_station.hpp

Python requires one observation, followed by one WORLD_VALIDATION_SUCCEEDED
marker, followed by the separately validated terminal receipt, all from the
same instance. Duplicate, missing, malformed or mismatching observations fail.
The observed hash receives only the parsed observation; expected data is used
only for the subsequent equality comparison.

Retained proof distinguishes manifest_world_fingerprint,
expected_runtime_world_hash, runtime_world_observation (and its raw message),
observed_runtime_world_hash, runtime_world_hash_match and
thin_ai_world_validation_result. Prelaunch records retain only expected identity
and runtime observation schema version; they do not invent runtime observations.

## Unbuilt candidate validation

Unbuilt candidates have no world object reference. They must pass the existing
AIMap.IsValidTile check, then skip existing-object queries and observation
emission. This does not claim facility existence, buildability or construction
success. Industry/station validity, ID and location checks remain required for
all referenced existing objects. Partial or unsupported references still fail.

## Repeated references and proof status

Every planner site reference is independently checked for object validity, ID and
location before observation deduplication. The emitted runtime objects are unique
by `(kind, object_id)` and sorted by kind and numeric object ID, matching Python's
canonical projection. Coordinates remain the independently validated runtime
facts; planner site IDs do not determine runtime identity. A later invalid alias
still fails even if an earlier reference to that object validated successfully.

Attempt #5 remains immutable historical evidence for its then-current source.
The separately authorized **Attempt #6** now covers the current thin-AI source and
is retained under `artifacts/planning/p03-proof-attempt6-20261003/`:

- [Prelaunch record](../artifacts/planning/p03-proof-attempt6-20261003/p03-proof-prelaunch.json)
  records attempt number 6 and staged source hashes. Its `main.nut` SHA-256 is
  `9ae9312479b7b0d2fe35cf3af14d40c875fd8de114e71c0232ea6c5e6a96bdc1`,
  and its `info.nut` SHA-256 is
  `fcdec167438bdf3162bd7b6e49cbc4ca1bacc52658a38231c7d935ab3a42f51c`;
  both match the current files in `app/planning/thin_ai/`.
- [Runtime evidence](../artifacts/planning/p03-proof-attempt6-20261003/p03-proof-evidence.json)
  records `status: accepted`, `failure_code: NONE`,
  `WORLD_VALIDATION_SUCCEEDED` and matching independently parsed observed/expected
  runtime-world hashes. It acknowledges the supplied road route, fleet group and
  infrastructure-action IDs from runtime instance 0.
- [Diagnostics](../artifacts/planning/p03-proof-attempt6-20261003/p03-proof-diagnostics.json)
  and [cleanup](../artifacts/planning/p03-proof-attempt6-20261003/p03-proof-cleanup.json)
  record process exit 0, a reaped process and removed owned workspace.

P03 is completed in commit `7260f8c`. Attempt #6 executed the current source,
including validation-before-deduplication and canonical object ordering, against
the retained fixture. Specific duplicate-alias and mixed-kind/numeric-order cases
remain covered by static AI assertions and independent Python parsing/hash checks
in `tests/test_planning_world_evidence.py`; the real fixture observes two distinct
industries and does not prove every such case in OpenTTD.

This proves plan transport, decoding, runtime-world validation and acknowledgement.
It does not prove infrastructure construction, vehicle purchase, service-order
execution or economic performance. The retained proof artifacts are unchanged;
they are local retained evidence under the ignored artifacts tree, not files
embedded in the P03 commit.
