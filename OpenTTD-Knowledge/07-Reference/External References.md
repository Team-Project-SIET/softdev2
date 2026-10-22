---
title: "External References"
type: reference
status: current
updated: 2026-10-22
tags:
  - openttd
  - reference
  - external
---

# External References

## Project repositories and docs

- Project repository: https://github.com/Team-Project-SIET/softdev2.git (branch `devmodule2`)
- Project-local OpenTTD documentation repository (intended; availability/completeness **unverified**):
  https://github.com/AgnesTachyon-feet/OpenTTD-Docs.git
- Context on using it: [[99-Source-Documents/CONTEXT]] §4 (preference order for evidence).

## Official OpenTTD 15.3 material

- Download CDN (pinned distribution): https://cdn.openttd.org/openttd-releases/15.3/openttd-15.3-linux-generic-amd64.tar.xz
- OpenGFX 8.0 archive: https://cdn.openttd.org/opengfx-releases/8.0/opengfx-8.0-all.zip
- Engine API headers referenced by the project's records (tagged `15.3` raw GitHub links):
  - Engine API: https://raw.githubusercontent.com/OpenTTD/OpenTTD/15.3/src/script/api/script_engine.hpp
  - Road API: https://raw.githubusercontent.com/OpenTTD/OpenTTD/15.3/src/script/api/script_road.hpp
- Industry planning rule examined by the project (Attempt 10 root cause):
  https://github.com/OpenTTD/OpenTTD/blob/15.3/src/industry_cmd.cpp
- Tree growth/death mechanics (V1/V2 reconciliation reference):
  `src/tree_cmd.cpp` `TileLoop_Trees` (15.3 tree)

Care: every console command or engine assumption referenced even from official sources
must still be verified against the pinned 15.3 binary/sources when used in execution
records (CONTEXT §18).

## Historical (explicitly not current target)

- OpenTTDLab / OpenTTD 13.4 environment: historical experiments and P03/P06 proofs live
  there. Keep separate; never import as 15.3 fact ([[01-Architecture/System Architecture]]).

## Reference-value project docs (repository-internal, linked for completeness)

- Secure admin transport: `docs/secure-admin-transport.md`
- Admin–GameScript bridge: `docs/admin-gamescript-bridge.md`
- First freight delivery proof: `docs/first-freight-delivery-proof.md`
- P08-native integrations: `docs/p08-controlled-native-integration.md`, `docs/structural-world-observation.md`
