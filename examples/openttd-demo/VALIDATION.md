# Checkpoint validation

Validation used an isolated export of HEAD plus only the selected demo changes.
It contained no unrelated untracked Python modules or historical runtime evidence.
The Python environment came from the existing locked project environment.
No OpenTTD process or Admin connection was started.

The dependency closure reuses the committed P08/P05, native three-service executor,
secure transport, GameScript assets, and P07 modules. New files are the public
wrapper, its tests, and example scenario/reports/documentation. The only staged
executor changes are the demo directory namespace and viewer lifecycle hooks.
Canonical fleet, continuous monitoring, capacity, terrain acquisition, and planner
allocation experiments remain outside this checkpoint. Root research documentation
changes already in the worktree remain unstaged.

## Checks

- CLI `--help`, dependency compatibility (`uv pip check`), and imports passed.
- Public wrapper, freight network, high-budget selection, world preparation,
  delivery, and P07 network tests: 112 passed, six skipped, eight deselected.
- Scoped Ruff lint, formatting, and ty checks passed.
- Documentation flags and output paths were checked against source.
- Staged whitespace and file inventory were reviewed before commit.

The six skipped tests require optional retained evidence. Eight historical-file
cases were explicitly excluded from this clean export. An initial broad run
without external assets had 11 missing-file failures; these were not runtime
failures. Preparation tests need the pinned OpenGFX archive described in the guide.

Run the focused checks from the repository root after dependency installation:

```bash
.venv/bin/python -m app.openttd_demo --help
uv pip check --python .venv/bin/python
.venv/bin/pytest tests/test_openttd_demo.py tests/test_native_freight_network.py \
  tests/test_high_budget_network_scaling.py tests/test_network_world_preparation.py \
  tests/test_freight_delivery.py tests/test_freight_network.py \
  -k 'not attempt10_exact_same_town_failure_replay and not attempt11_frozen_config_replays_zero_mutation_guard_failure and not controlled_one_shot_runner_receipt_and_failure_cleanup and not retained_attempt_has_no_gate_diagnostics'
.venv/bin/ruff check app/openttd_demo.py app/simulation/openttd/proof/freight_delivery.py tests/test_openttd_demo.py
.venv/bin/ruff format --check app/openttd_demo.py app/simulation/openttd/proof/freight_delivery.py tests/test_openttd_demo.py
uvx ty check --python .venv/bin/python app/openttd_demo.py app/simulation/openttd/proof/freight_delivery.py
git diff --cached --check
```

The native verification described in the guide is retained evidence, not a fresh
launch during this checkpoint. The bundled sample remains Attempt 17's offline
report; it does not claim the latest demo's revenue.

The latest retained demo also passed independent P07 offline replay with process
creation and socket connections blocked. The standalone offline planning command
selected three services. The historical sample normalizes its evidence directory
to a repository-relative path; its measured values are unchanged.
