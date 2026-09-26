"""One-shot final-save parser child; does not launch or control OpenTTD."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from app.experiments.domain import ExperimentConfig
from app.simulation.openttd.final_result import FinalResultError, FinalResultProcessor


@dataclass(frozen=True)
class _SaveLocation:
    workspace: Path
    final_save_path: Path


@dataclass(frozen=True)
class _ProgressInfo:
    run_id: int
    artifact_dir: Path
    target_day: int
    last_observed_day: int


def main() -> int:
    try:
        request = json.load(sys.stdin)
        prepared = _SaveLocation(
            workspace=Path(request["workspace"]), final_save_path=Path(request["save_path"])
        )
        progress = _ProgressInfo(
            run_id=request["run_id"],
            artifact_dir=Path(request["artifact_dir"]),
            target_day=request["target_day"],
            last_observed_day=request["last_observed_day"],
        )
        result = FinalResultProcessor().process(
            prepared, progress, ExperimentConfig.model_validate(request["config"])
        )
    except FinalResultError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    except Exception:
        print(json.dumps({"error": "final save could not be parsed"}))
        return 1
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
