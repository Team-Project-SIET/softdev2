# OpenTTD 15.3 proof CLI

The production module CLI is the only supported Attempt #2 execution entrypoint. Retire the previous one-off import/accessor gate procedures; their failure reports remain immutable historical evidence.

Read-only preflight:

```sh
.venv/bin/python -m app.simulation.openttd.proof preflight --directory artifacts/runtime/openttd-15.3-real-ack-attempt2-prelaunch-v3/
```

Preflight loads the typed preparation, verifies its manifest/source inventory, frozen inputs and historical identities, validates secure configuration and private-key handling, and reserves/releases loopback game TCP/UDP and Admin TCP endpoints. An audit guard rejects subprocess creation and socket connections. It writes no preparation/runtime evidence and does not dispose the workspace.

A future real execution requires fresh explicit authorization against the new v3 freeze:

```sh
.venv/bin/python -m app.simulation.openttd.proof run --directory artifacts/runtime/openttd-15.3-real-ack-attempt2-prelaunch-v3/ --authorize-one-launch
```

Run delegates the same prelaunch gates, re-reserves endpoints immediately before the one launch, and uses the existing no-retry harness. No manual internal imports or object reconstruction are required. The internal reservation API is EndpointReservation.allocate(), not PortReservation.

V2 is preserved as historical preparation and cannot authorize changed production source. Request 002, the frozen bridge, and the two semantically correlated local evidence chains remain unchanged. No real Attempt #2 has been performed during this CLI repair.
