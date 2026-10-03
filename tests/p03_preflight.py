"""Exercise the live P03 prelaunch boundary; never start OpenTTD."""

import json
import os
import sys
import tempfile
from pathlib import Path

from tests.test_planning_transport_live import ATTEMPT2_ROOT, run_p03_proof


def main() -> None:
    candidate = Path(os.environ["P03_ARTIFACT_ROOT"])
    assert candidate.is_absolute() and not candidate.exists()
    attempt1 = Path("/tmp/softdev2-p03-proof-20260928")
    assert not candidate.is_relative_to(attempt1) and not attempt1.is_relative_to(candidate)
    cache = Path(os.environ["P03_RUNTIME_CACHE_ROOT"]).resolve()
    for protected in (attempt1, ATTEMPT2_ROOT.resolve(), cache):
        assert not candidate.resolve().is_relative_to(protected)
        assert not protected.is_relative_to(candidate.resolve())
    assert not any(
        path.read_text().strip() == "openttd"
        for path in Path("/proc").glob("[0-9]*/comm")
        if path.exists()
    )

    # Enforce the no-process contract even if the shared path later regresses.
    def forbid_process(event, args):
        if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
            raise AssertionError("preflight must not launch a process")

    sys.addaudithook(forbid_process)
    # A disposable proof root exercises all live preparation, persistence and
    # reread checks. The requested real attempt candidate remains absent.
    with tempfile.TemporaryDirectory(prefix="p03-preflight-") as directory:
        os.environ["P03_ARTIFACT_ROOT"] = directory
        try:
            record = run_p03_proof(prelaunch_only=True)
        finally:
            os.environ["P03_ARTIFACT_ROOT"] = str(candidate)
        assert record is not None
        assert not Path(record["owned_workspace"]).exists()
        print(
            json.dumps(
                {
                    "artifact_root_candidate": str(candidate),
                    "prelaunch": record,
                    "workspace_cleaned": True,
                    "openttd_launched": False,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
