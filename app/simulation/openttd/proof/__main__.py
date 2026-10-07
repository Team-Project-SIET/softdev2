"""Preparation by default; real execution needs a separately authorized explicit flag."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .attempt import execute_attempt
from .cargo_contract import CARGO_PRELAUNCH_DIRECTORY
from .cargo_native import CargoNativeBackend
from .cargo_page_contract import PAGE_PRELAUNCH_DIRECTORY
from .cargo_page_native import CargoPageNativeBackend
from .catalog_contract import (
    CATALOG_PRELAUNCH_DIRECTORY,
)
from .catalog_native import CatalogNativeBackend
from .enrichment_contract import ENRICHMENT_PRELAUNCH_DIRECTORY
from .enrichment_native import EnrichmentNativeBackend
from .harness import PROJECT, prepare_proof
from .industry_contract import INDUSTRY_PRELAUNCH_DIRECTORY
from .industry_native import IndustryNativeBackend
from .inventory_contract import INVENTORY_PRELAUNCH_DIRECTORY
from .inventory_native import InventoryNativeBackend
from .native import NativeBackend, load_prepared
from .preflight import preflight_prepared
from .structural_contract import STRUCTURAL_PRELAUNCH_DIRECTORY
from .structural_native import StructuralNativeBackend
from .world_native import WorldNativeBackend


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "preflight", "run"))
    parser.add_argument(
        "--directory",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--mode",
        choices=(
            "ack",
            "world-info",
            "industry-page",
            "industry-inventory",
            "industry-cargo",
            "industry-enrichment",
            "cargo-page",
            "cargo-catalog",
            "structural-world",
        ),
        default="ack",
    )
    parser.add_argument("--authorize-one-launch", action="store_true")
    args = parser.parse_args()
    if args.directory is None:
        name = (
            STRUCTURAL_PRELAUNCH_DIRECTORY
            if args.mode == "structural-world"
            else CATALOG_PRELAUNCH_DIRECTORY
            if args.mode == "cargo-catalog"
            else PAGE_PRELAUNCH_DIRECTORY
            if args.mode == "cargo-page"
            else ENRICHMENT_PRELAUNCH_DIRECTORY
            if args.mode == "industry-enrichment"
            else CARGO_PRELAUNCH_DIRECTORY
            if args.mode == "industry-cargo"
            else INVENTORY_PRELAUNCH_DIRECTORY
            if args.mode == "industry-inventory"
            else INDUSTRY_PRELAUNCH_DIRECTORY
            if args.mode == "industry-page"
            else "openttd-15.3-world-info-real-prelaunch"
            if args.mode == "world-info"
            else "openttd-15.3-real-ack-attempt2-prelaunch-v3"
        )
        args.directory = PROJECT / "artifacts/runtime" / name
    backend_type = {
        "ack": NativeBackend,
        "world-info": WorldNativeBackend,
        "industry-page": IndustryNativeBackend,
        "industry-inventory": InventoryNativeBackend,
        "industry-cargo": CargoNativeBackend,
        "industry-enrichment": EnrichmentNativeBackend,
        "cargo-page": CargoPageNativeBackend,
        "cargo-catalog": CatalogNativeBackend,
        "structural-world": StructuralNativeBackend,
    }[args.mode]
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
            result["process_creation_blocked"] = True
            print(json.dumps(result, sort_keys=True))
        except Exception as error:
            if args.mode in (
                "industry-page",
                "industry-inventory",
                "industry-cargo",
                "industry-enrichment",
                "cargo-page",
                "cargo-catalog",
                "structural-world",
            ):
                from .world_attempt import record_prelaunch_failure

                failure = args.directory.with_name(args.directory.name + "-gate-failure")
                if not failure.exists():
                    record_prelaunch_failure(args.directory, error)
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
        if args.mode == "structural-world":
            from .structural_attempt import execute_structural_attempt
            from .world_attempt import record_prelaunch_failure

            try:
                prepared = load_prepared(args.directory, mode=args.mode)
            except Exception as error:
                record_prelaunch_failure(args.directory, error)
                raise SystemExit("PRELAUNCH_FAILED; no execution") from None
            result = asyncio.run(
                execute_structural_attempt(
                    prepared, StructuralNativeBackend(authorized_one_launch=True)
                )
            )
        elif args.mode == "cargo-catalog":
            from .catalog_attempt import execute_catalog_attempt
            from .world_attempt import record_prelaunch_failure

            try:
                prepared = load_prepared(args.directory, mode=args.mode)
            except Exception as error:
                record_prelaunch_failure(args.directory, error)
                raise SystemExit("PRELAUNCH_FAILED; no execution") from None
            result = asyncio.run(
                execute_catalog_attempt(prepared, CatalogNativeBackend(authorized_one_launch=True))
            )
        elif args.mode == "cargo-page":
            from .cargo_page_attempt import execute_page_attempt
            from .world_attempt import record_prelaunch_failure

            try:
                prepared = load_prepared(args.directory, mode=args.mode)
            except Exception as error:
                record_prelaunch_failure(args.directory, error)
                raise SystemExit("PRELAUNCH_FAILED; no execution") from None
            result = asyncio.run(
                execute_page_attempt(prepared, CargoPageNativeBackend(authorized_one_launch=True))
            )
        elif args.mode == "industry-enrichment":
            from .enrichment_attempt import execute_enrichment_attempt
            from .world_attempt import record_prelaunch_failure

            try:
                prepared = load_prepared(args.directory, mode=args.mode)
            except Exception as error:
                record_prelaunch_failure(args.directory, error)
                raise SystemExit("PRELAUNCH_FAILED; no execution") from None
            result = asyncio.run(
                execute_enrichment_attempt(
                    prepared, EnrichmentNativeBackend(authorized_one_launch=True)
                )
            )
        elif args.mode == "industry-cargo":
            from .cargo_attempt import execute_cargo_attempt
            from .world_attempt import record_prelaunch_failure

            try:
                prepared = load_prepared(args.directory, mode=args.mode)
            except Exception as error:
                record_prelaunch_failure(args.directory, error)
                raise SystemExit("PRELAUNCH_FAILED; no execution") from None
            result = asyncio.run(
                execute_cargo_attempt(prepared, CargoNativeBackend(authorized_one_launch=True))
            )
        elif args.mode == "industry-inventory":
            from .inventory_attempt import execute_inventory_attempt
            from .world_attempt import record_prelaunch_failure

            try:
                prepared = load_prepared(args.directory, mode=args.mode)
            except Exception as error:
                record_prelaunch_failure(args.directory, error)
                raise SystemExit("PRELAUNCH_FAILED; no execution") from None
            result = asyncio.run(
                execute_inventory_attempt(
                    prepared, InventoryNativeBackend(authorized_one_launch=True)
                )
            )
        elif args.mode == "industry-page":
            from .industry_attempt import execute_industry_attempt
            from .world_attempt import record_prelaunch_failure

            try:
                prepared = load_prepared(args.directory, mode=args.mode)
            except Exception as error:
                record_prelaunch_failure(args.directory, error)
                raise SystemExit("PRELAUNCH_FAILED; no execution") from None
            result = asyncio.run(
                execute_industry_attempt(
                    prepared, IndustryNativeBackend(authorized_one_launch=True)
                )
            )
        elif args.mode == "world-info":
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
