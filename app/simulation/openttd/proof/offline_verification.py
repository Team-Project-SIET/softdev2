"""Bind mandatory offline acceptance independently of native lifecycle success."""

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree


def failed_offline_verification(directory: Path, native: dict) -> dict:
    """Return a manifest-bound failed verdict; never infer acceptance from COMPLETED."""
    verification = directory.with_name(directory.name + "-postrun-verification")
    if not verification.exists():
        return {}
    from .harness import manifest

    if verification.is_symlink() or (
        verification / "artifact-manifest.sha256"
    ).read_text() != manifest(verification):
        raise ValueError("Offline verification manifest mismatch")
    record = json.loads((verification / "verification.json").read_text())
    if (
        record.get("native_status") != native.get("status", native.get("state"))
        or record.get("native_lifecycle") != native.get("states", [None])[-1]
        or record.get("final_acceptance") != "FAILED_POSTRUN_VERIFICATION"
        or not record.get("terminal_reason")
        or record.get("integrity", {}).get("integrity") != "PASS"
        or not (verification / "final-report.md").is_file()
    ):
        raise ValueError("Contradictory offline verification authority")
    failures = 0
    for name in ("focused", "ordinary"):
        expected = record["tests"][name]
        suite = ElementTree.parse(verification / f"{name}.xml").getroot()
        if suite.tag == "testsuites":
            suite = suite.find("testsuite")
        if suite is None or any(
            suite.get(k) != expected[k] for k in ("tests", "failures", "errors", "skipped")
        ):
            raise ValueError("Offline verification result mismatch")
        failures += int(expected["failures"]) + int(expected["errors"])
    if failures == 0:
        raise ValueError("Failed offline verdict requires failed mandatory verification")
    public_files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(verification.iterdir())
        if p.is_file()
    }
    return dict(
        classification="POST_LAUNCH_FAILURE",
        terminal_status="FAILED_POSTRUN_VERIFICATION",
        overall_acceptance="FAILED",
        failure_phase="POST_RUN_OFFLINE_VERIFICATION",
        offline_verification="FAILED",
        terminal_failure_reason=record["terminal_reason"],
        native_terminal_status=record["native_status"],
        native_lifecycle=record["native_lifecycle"],
        postrun_evidence_directory=verification.name,
        postrun_evidence_files=public_files,
    )
