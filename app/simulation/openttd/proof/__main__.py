"""Preparation by default; real execution needs a separately authorized explicit flag."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .attempt import execute_attempt
from .harness import PROJECT, prepare_proof
from .native import NativeBackend, load_prepared
from .preflight import preflight_prepared
from .world_native import WorldNativeBackend


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "preflight", "run"))
    parser.add_argument(
        "--directory",
        type=Path,
        default=None,
    )
    parser.add_argument("--mode", choices=("ack", "world-info"), default="ack")
    parser.add_argument("--authorize-one-launch", action="store_true")
    args = parser.parse_args()
    if args.directory is None:
        name = (
            "openttd-15.3-world-info-real-prelaunch"
            if args.mode == "world-info"
            else "openttd-15.3-real-ack-attempt2-prelaunch-v3"
        )
        args.directory = PROJECT / "artifacts/runtime" / name
    backend_type = WorldNativeBackend if args.mode == "world-info" else NativeBackend
    if args.command == "prepare":
        prepared = prepare_proof(args.directory, mode=args.mode)
        print(f"PRELAUNCH only: {prepared.directory}")
    elif args.command == "preflight":

        def guard(event, arguments):
            if event in ("subprocess.Popen", "socket.connect"):
                raise PermissionError("Dry-run process/connection guard")

        sys.addaudithook(guard)
        try:
            result = preflight_prepared(
                load_prepared(args.directory, mode=args.mode),
                backend_type(authorized_one_launch=True),
            )
            print(json.dumps(result, sort_keys=True))
        except Exception as error:
            print(
                json.dumps(
                    {
                        "state": "PREFLIGHT_FAILED",
                        "reason": str(error),
                        "launches": 0,
                        "connections": 0,
                        "requests": 0,
                    }
                )
            )
            raise SystemExit(1) from None
    else:
        if not args.authorize_one_launch:
            parser.error("Separate explicit one-launch authorization required")
        if args.mode == "world-info":
            from .world_attempt import execute_world_attempt, record_prelaunch_failure

            try:
                prepared = load_prepared(args.directory, mode=args.mode)
            except Exception as error:
                record_prelaunch_failure(args.directory, error)
                raise SystemExit("PRELAUNCH_FAILED; no execution") from None
            result = asyncio.run(
                execute_world_attempt(
                    prepared,
                    WorldNativeBackend(authorized_one_launch=True),
                )
            )
        else:
            result = asyncio.run(
                execute_attempt(
                    load_prepared(args.directory),
                    NativeBackend(authorized_one_launch=True),
                )
            )
        print(
            f"{result['status']}: launches={result['launches']}, requests={result['requests_sent']}"
        )
        if result["status"] != "REAL_SUCCESS":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
