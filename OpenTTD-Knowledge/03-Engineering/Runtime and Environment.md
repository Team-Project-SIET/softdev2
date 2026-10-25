---
title: "Runtime and Environment"
type: engineering
status: current
updated: 2026-10-24
tags:
  - openttd
  - engineering
  - environment
---

# Runtime and Environment

**Sources:** [[99-Source-Documents/README]] (requirements, pinned assets, configuration),
[[99-Source-Documents/REPRODUCE]] (environment provisioning rules), repo files
(`pyproject.toml`, `uv.lock`, `mise.toml`, `.env.example`).

## Platform and toolchain

- Host platform: **Linux amd64** (supported demo platform), graphical desktop for the
  spectator client.
- **Python 3.14+** (this work used 3.14.6); `mise.toml` pins `python = "3.14.6"`.
- Dependency authority: `pyproject.toml` + `uv.lock`. Provision with
  `uv sync --locked` (or `--locked --group dev` — the dev group is required for the
  controlled GameScript tests). Preserve the existing environment for inspection;
  check local resources before installing anything.
- Not required for the demo: **PostgreSQL and Docker** (they belong to the legacy
  `transport-experiment` path). Basic Fedora tools: `sudo dnf install git curl tar xz`.

## Pinned OpenTTD 15.3 assets

| Asset | Requirement | SHA-256 |
|---|---|---|
| OpenTTD 15.3 Linux generic amd64 binary | whole extracted distribution kept together (`lib`, `lang`, …); no system substitute | `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c` |
| OpenGFX 8.0 all-ZIP | verified archive | `43a0c1dabf39cb865394f3a6cc36d4da5c10ecfaaf55652043104806810903be` |
| Download tarball | `openttd-15.3-linux-generic-amd64.tar.xz` from cdn.openttd.org | `f49eb25d61b00f8f4d332fee02b530ad75552d1efb8f2bb01e7ca5e6540fe059` |

⚠ All three hashes are also printed with `sha256sum --check` commands in
[[99-Source-Documents/README]] ("Install the pinned OpenTTD assets") — when in doubt, use
that file, not this table.

Historical local default (README): `/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd`
without `OPENTTD_BINARY` set. Language/distribution assets stay beside the executable.

## Configuration variables

| Variable | Use |
|---|---|
| `OPENTTD_BINARY` | Freight demo executable path; bytes must match the pinned 15.3 binary |
| `OPENTTD_OPENGFX_ARCHIVE` | OpenGFX 8.0 ZIP path; default `artifacts/runtime/verified-assets/opengfx-8.0-all.zip` |
| `UV_CACHE_DIR`, `UV_TOOL_DIR` | Optional writable uv cache/tool dirs (e.g. `/tmp/softdev2-uv-cache`) |
| `DATABASE_URL`, `APP_ENV`, `SQL_ECHO` | Optional database-backed experiment configuration; not needed by the freight demo |

Export the asset variables in the shell; the proof CLI does not read them from `.env`.
The repository keeps `.env` / account/cache folders out of transfers (credentials
excluded; [[99-Source-Documents/AI_HANDOFF]] "Checkout and transfer").

## Operator key material (operator-only; not runtime configuration)

The operator's Ed25519 private key is operator-held material **outside Git**
(`~/.local/share/openttd-operator/operator-private.pem` in the local development
proof). It is not a configuration variable and never enters the repository, this
vault, chat logs, screenshots or a candidate directory.

- Provisioning/extraction procedure:
  `docs/handoff/2026-10-17/operator-key-provisioning.md` §1 (corrected
  2026-10-24; validated with **synthetic keys only**; the production key was
  not accessed or tested).
- The tested extraction pipeline requires a Bash-compatible shell, `pipefail`,
  and `tail`/`od`/`tr`. In this environment `xxd` is absent, and
  `openssl pkey ... -noout -outform DER` emitted **zero bytes** on OpenSSL
  3.6.3; the corrected form omits `-noout` and formats with `od`/`tr`.
- The seed must never be printed to a terminal, written to a file, or passed
  as a command-line argument. It is captured only into a shell
  variable/environment consumed by the signing process.
- Documentation is **not** authorization. Signing, authorization consumption
  and native launches each require their own explicit operator decision.

## Run commands (public surface)

```bash
.venv/bin/python -m app.openttd_demo check                       # binary/assets/desktop validation
.venv/bin/python -m app.openttd_demo --view-seconds 300          # native demo (separate authorization)
.venv/bin/python -m app.openttd_demo plan                        # offline scenario selection
.venv/bin/python -m app.openttd_demo report|compare …            # offline P07 outputs
```

Proof-runner ceremony and D-chain runners: [[03-Engineering/Reproduction Guide]].
Generated run directories use fresh UUIDs/NIDs; consumed attempt directories are immutable.

## Retained artifacts location map

```text
artifacts/demos/…                            demo attempts (fixed + random), classification capture
artifacts/runtime/…                          freight delivery attempts, verified assets/tools
artifacts/experiments/…                      offline analyses/experiment records
```

Ignored by Git → check presence/hashes from `docs/handoff/2026-10-17/` inventories;
absent bytes are UNKNOWN, never regenerated ([[04-Evidence/Evidence Preservation]]).

## Known environment quirks

- A stray untracked root file named `--version` exists in the checkout: **preserve it and
  do not execute it** (AI_HANDOFF).
- uv cache/tool locations may be redirected via `UV_CACHE_DIR`/`UV_TOOL_DIR` when the
  default caches are unwritable (README Troubleshooting).
- Docker Compose + Alembic remain available for the legacy experiment path
  (`docker compose up -d postgres`, `alembic upgrade head`), untouched by the 15.3 demo.
