"""Bounded public diagnostics: no source lines, locals, credentials or environment."""

import json
import re
import stat
import traceback
from pathlib import Path


class RuntimeInputMismatch(ValueError):
    def __init__(self, message, **details):
        super().__init__(message)
        self.validation_details = details


def _failure_diagnostics(error, prepared, backend, destination):
    secrets = list(dict(getattr(prepared.spec, "environment", ())).values())
    key = getattr(backend, "_key", None)
    if key is not None:
        secrets.append(key._secret.hex())
        secrets.append(repr(key._secret))
    # Read only an owned key file; never retain its bytes in diagnostics.
    key_path = getattr(prepared, "key_path", None)
    if key_path is not None and key_path.is_file() and not key_path.is_symlink():
        raw = key_path.read_bytes()
        secrets.extend((raw.hex(), repr(raw)))

    def clean(value):
        text = str(value)
        for secret in secrets:
            if secret:
                text = text.replace(secret, "<REDACTED>")
        text = re.sub(
            r"(?i)((?:password|secret|private[_ -]?key|token)\s*[:=]\s*)\S+", r"\1<REDACTED>", text
        )
        return text[:512]

    chain = []
    seen = set()
    cause = error
    details = {}
    while cause is not None and id(cause) not in seen and len(chain) < 4:
        seen.add(id(cause))
        frames = traceback.extract_tb(cause.__traceback__)[-12:]
        chain.append(
            dict(
                type=type(cause).__name__,
                message=clean(cause),
                frames=[
                    dict(file=Path(f.filename).name, line=f.lineno, function=f.name) for f in frames
                ],
            )
        )
        details.update(getattr(cause, "validation_details", {}))
        cause = cause.__cause__
    manifest_path = prepared.directory / "runtime-materializations.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {"entries": []}
    inputs = {r["path"] for r in manifest["entries"]} | (
        {str(key_path)} if key_path is not None else set()
    )
    outputs = {str(prepared.spec.stdout_path), str(prepared.spec.stderr_path)}
    actual = {str(p) for p in prepared.spec.workspace.root.rglob("*") if not p.is_dir()}
    details.setdefault("expected_runtime_input_count", len(inputs))
    details.setdefault("actual_runtime_input_count", len(actual - outputs))
    details.setdefault("unexpected_paths", sorted(actual - inputs - outputs))
    frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
    from .harness import sha256

    mismatches = []
    for path, expected in frozen.items():
        p = Path(path)
        if not p.exists() or not stat.S_ISREG(p.lstat().st_mode):
            mismatches.append(dict(path=path, expected=expected, actual=None))
        else:
            actual_hash = sha256(p)
            if actual_hash != expected:
                mismatches.append(dict(path=path, expected=expected, actual=actual_hash))
        if len(mismatches) == 16:
            break
    for row in manifest["entries"]:
        p = Path(row["path"])
        actual_hash = sha256(p) if p.exists() and stat.S_ISREG(p.lstat().st_mode) else None
        if actual_hash != row["sha256"]:
            mismatches.append(dict(path=row["path"], expected=row["sha256"], actual=actual_hash))
    details.setdefault("identity_mismatches", mismatches[:16])

    def sanitize(value):
        if isinstance(value, str):
            return clean(value)
        if isinstance(value, dict):
            return {k: sanitize(v) for k, v in list(value.items())[:32]}
        if isinstance(value, list):
            return [sanitize(v) for v in value[:32]]
        return value

    return dict(
        failure_stage=getattr(backend, "failure_stage", "execution"),
        failing_function=chain[-1]["frames"][-1]["function"] if chain[-1]["frames"] else None,
        exception_causes=chain,
        validation=sanitize(details),
        claim_state="CONSUMED" if destination.exists() else "UNCONSUMED",
        popen_invoked=getattr(backend, "popen_invoked", False),
        launches=backend.launches,
    )


def failure_diagnostics(error, prepared, backend, destination):
    """A damaged diagnostic input must never suppress the original failure/cleanup."""
    try:
        return _failure_diagnostics(error, prepared, backend, destination)
    except Exception as diagnostic_error:
        frames = traceback.extract_tb(error.__traceback__)[-12:]
        return dict(
            failure_stage=getattr(backend, "failure_stage", "execution"),
            failing_function=frames[-1].name if frames else None,
            exception_causes=[
                dict(
                    type=type(error).__name__,
                    message="<Unavailable>",
                    frames=[
                        dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                        for f in frames
                    ],
                )
            ],
            diagnostics_error=type(diagnostic_error).__name__,
            claim_state="CONSUMED" if destination.exists() else "UNCONSUMED",
            popen_invoked=getattr(backend, "popen_invoked", False),
            launches=backend.launches,
        )
