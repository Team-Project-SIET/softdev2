"""Explicit attended local terrain proof CLI. Help/import/preflight never execute."""

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from .terrain_authorization import (
    _CONTROLLED_GRANT,
    _LOCAL_GRANT,
    FailureCode,
    LocalOperatorAuthorization,
    LocalProofFailure,
    LocalTrust,
    process_start_identity,
)


def _confirmation(prepared, terminal, *, controlled, output=None):
    from .harness import sha256
    from .terrain_attempt import validate_immutable_seal
    from .terrain_authorization import LOCAL_POLICY

    row = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    destination = Path(row["attempt_directory"])
    try:
        validate_immutable_seal(prepared, destination)
    except (ValueError, OSError, PermissionError) as error:
        raise LocalProofFailure(FailureCode.SOURCE_INTEGRITY_FAILED, str(error)) from error
    if row.get("authorization_policy") != LOCAL_POLICY:
        raise LocalProofFailure(FailureCode.AUTHORIZATION_INVALID, "Seal does not select Model A")
    output = terminal if output is None else output
    if not terminal.isatty() or not output.isatty():
        raise LocalProofFailure(FailureCode.AUTHORIZATION_INVALID, "Interactive terminal required")
    if destination.exists():
        raise LocalProofFailure(FailureCode.ATTEMPT_ALREADY_CONSUMED, "No resume/retry")
    digest = sha256(prepared.directory / "PRELAUNCH.json")
    expected = f"CONFIRM {digest} {row['attempt_identity']} {destination}"
    output.write(
        f"OpenTTD {prepared.spec.identity.version}: {prepared.spec.identity.executable}\n"
        f"Seal SHA256: {digest}\nAttempt: {row['attempt_identity']}\nDestination: {destination}\n"
        f"Command: tile_facts_page; rectangle {row['region']}; tiles {row['expected_tiles']}\n"
        "Maximum launches: 1; application requests: 1; no retry/reconnect/resume\n"
        "Source integrity: PASS; LOCAL_OPERATOR_ATTESTED, no independent authentication\n"
        f"Type exactly: {expected}\n> "
    )
    output.flush()
    if terminal.readline(4096).rstrip("\n") != expected:
        raise LocalProofFailure(
            FailureCode.OPERATOR_CONFIRMATION_DECLINED, "Exact confirmation absent"
        )
    # Capture the precise interactive action; no persisted record can reconstruct this grant.
    return LocalOperatorAuthorization(
        digest,
        row["attempt_identity"],
        str(destination),
        os.getpid(),
        process_start_identity(),
        uuid.uuid4().hex,
        LocalTrust.CONTROLLED_OPERATOR_ATTESTED
        if controlled
        else LocalTrust.LOCAL_OPERATOR_ATTESTED,
        _grant=_CONTROLLED_GRANT if controlled else _LOCAL_GRANT,
    )


def controlled_confirmation(prepared, terminal):
    """Controlled terminal tests always produce non-production authorization."""
    return _confirmation(prepared, terminal, controlled=True)


def attended_confirmation(prepared):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise LocalProofFailure(FailureCode.AUTHORIZATION_INVALID, "Noninteractive run rejected")
    try:
        # Buffered update streams require seeking; a terminal is nonseekable.
        # Nested contexts also close the reader if opening the writer fails.
        with Path("/dev/tty").open("r") as reader:
            with Path("/dev/tty").open("w", buffering=1) as writer:
                return _confirmation(prepared, reader, output=writer, controlled=False)
    except LocalProofFailure:
        raise
    except (OSError, ValueError, UnicodeError) as error:
        raise LocalProofFailure(
            FailureCode.OPERATOR_CONFIRMATION_DECLINED, "Terminal confirmation unavailable"
        ) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run-attended"))
    parser.add_argument("--seal-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    from .terrain_attempt import authorized_native_run, validate_immutable_seal
    from .terrain_preparation import load_terrain_prepared

    row = json.loads((args.seal_directory / "PRELAUNCH.json").read_text())
    prepared = load_terrain_prepared(Path(row["candidate_path"]), args.seal_directory)
    destination = Path(row["attempt_directory"])
    validate_immutable_seal(prepared, destination)
    if args.command == "preflight":
        print("PREFLIGHT_PASS; unauthorized; no attempt consumed")
        return
    authorization = attended_confirmation(prepared)
    print(
        json.dumps(
            asyncio.run(authorized_native_run(prepared, destination, authorization=authorization)),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
