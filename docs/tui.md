# Read-only evidence TUI

`app.tui` is an optional Textual console for the JSON and Markdown artifacts that
the OpenTTD demo already writes. It is additive: no planner, executor, Admin
client or native runtime module imports it. The TUI never launches OpenTTD,
opens an Admin connection, consumes a one-shot authorization/claim, or writes
into an evidence directory.

## Install and run

Textual is an optional dependency group so the core install stays unchanged:

```bash
uv sync --group tui
uv run --group tui openttd-tui
# equivalent:
uv run --group tui python -m app.tui
```

Common options:

```bash
# Scan a parent directory of runs/reports (default: artifacts/demos)
uv run --group tui python -m app.tui --root artifacts/demos

# Inspect one run or P07 report directly
uv run --group tui python -m app.tui --root artifacts/demos/<attempt>

# Do not fall back to the bundled sample when the root is empty
uv run --group tui python -m app.tui --no-sample

# Print the catalog without starting the UI (works without Textual)
python -m app.tui --root examples/openttd-demo/sample-report --dump
```

When the configured root contains no artifacts, the app falls back to the
bundled read-only sample at `examples/openttd-demo/sample-report` and labels it
`sample-report (bundled)`. If Textual is missing, `openttd-tui` exits with code
2 and prints the install command; `--dump` still works.

## Screens

| Screen | Contents |
| --- | --- |
| Summary | Artifact path/kind/status, world and experiment identity, network finance readback, evidence limitations |
| Services | Per-service delivered cargo, vehicle count, CAPEX, backlog and delivery date where retained |
| Metrics | P07 planned-versus-actual rows, scope, difference, unit and comparison status |
| Charts | Milestone bars derived only from retained operational-history points, plus network CAPEX |
| Evidence | Files in the artifact directory with sizes and manifest SHA-256 digests |

The sidebar lists every discovered run and P07 report directory. Discovery scans
the root, its immediate children and one nested level, so `--root artifacts` also
finds `artifacts/runtime/<attempt>`. A directory is a run when it contains
`result.json`, `receipt.json`, `PRELAUNCH.json`, `planning-scenario.json` or
`execution-plan.json`; it is a report when it contains `evaluation.json`,
`operational-history.json` or `results.md`. Status falls back to a proof
attempt's `classification` when no result/evaluation classification is present.

## Keys

| Key | Action |
| --- | --- |
| Up / Down | Move through the artifact list |
| Tab | Move focus into the detail tabs |
| r | Rescan the artifact root |
| ? | Show help |
| q | Quit |

## Evidence rules

* `UNKNOWN` means the retained evidence does not establish the value. It is not
  zero, and the TUI never substitutes zero for missing data.
* A retained numeric zero is shown as `£0`/`0`; only absent values are `UNKNOWN`.
* Per-service revenue stays `UNKNOWN` unless the retained evaluation marks it
  comparable for that service. Network revenue is shown only when recorded.
* OPEX, net profit, ROI and throughput are never estimated. They stay `UNKNOWN`
  unless the artifact records them.
* Charts use retained readback points only. There is no interpolation,
  projection or synthetic series; an empty series renders `UNKNOWN`.
* Partial, invalid, non-object or oversized JSON makes that field unknown instead
  of crashing the view. Reads are bounded (4 MiB generally, 8 MiB for receipts,
  2 MiB for `PRELAUNCH.json`).
* File digests come from `artifact-manifest.sha256`/`manifest.sha256` when
  present; otherwise the digest cell is `UNKNOWN`.

The Services screen intentionally does not attribute company-level cash or
revenue to a service unless the evaluation records a comparable per-service
value. Revenue is not profit.

## Tests

The data layer has no Textual import, so its tests run with the core suite. The
screen smoke tests skip when Textual is not installed.

```bash
uv run --group tui pytest tests/test_tui_data.py tests/test_tui_app.py
```

The tests cover the bundled sample, missing-versus-zero semantics, partial and
invalid JSON, manifest digests, discovery/deduplication, the bundled-sample
fallback, `--dump`, and a Textual render/help smoke test.
