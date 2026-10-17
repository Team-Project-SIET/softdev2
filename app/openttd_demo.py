"""Public OpenTTD 15.3 demo: check, plan offline, or run a visible local game."""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid

from app.simulation.openttd.proof import freight_delivery as native
from app.simulation.openttd.proof.harness import BINARY_SHA256, PROJECT, sha256
from app.simulation.openttd.runtime.config import RuntimeWorkspace

BINARY = native.BINARY

SAMPLE = PROJECT / "examples/openttd-demo/scenario.json"
RUNS = PROJECT / "artifacts/demos"


def check(*, graphical=True):
    if not BINARY.is_file() or sha256(BINARY) != BINARY_SHA256:
        raise ValueError(f"Install the pinned OpenTTD 15.3 binary at {BINARY}")
    if (
        not native.GRAPHICS_ARCHIVE.is_file()
        or sha256(native.GRAPHICS_ARCHIVE) != native.ARCHIVE_SHA256
    ):
        raise ValueError(f"Pinned OpenGFX archive missing or changed: {native.GRAPHICS_ARCHIVE}")
    if graphical and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise ValueError(
            "No graphical desktop detected; run from a desktop terminal or use --headless"
        )


def selections(directory):
    plan = json.loads((directory / "execution-plan.json").read_bytes())
    scenario = json.loads((directory / "planning-scenario.json").read_bytes())
    demands = {d["demand_id"]: d for d in scenario["cargo_demands"]}
    rows = []
    for index, route in enumerate(plan["routes"], 1):
        assignment = route["cargo_assignments"][0]
        d = demands[assignment["demand_id"]]
        rows.append(
            f"Service {index}: {d['origin_id']} -> {d['destination_id']}, "
            f"{assignment['quantity']} cargo units"
        )
    return rows


def show_results(directory):
    receipt = json.loads((directory / "receipt.json").read_bytes())
    print("\nVerified delivery batches:", flush=True)
    for index, service in enumerate(receipt["services"], 1):
        print(
            f"  Service {index} ({service['source']} -> {service['destination']}): "
            f"{service['delivered']} cargo; "
            f"revenue GBP {service['payment_income']}",
            flush=True,
        )
    finance = json.loads((directory / "financial-reconciliation.json").read_bytes())
    print(
        f"Cash GBP {finance['final_cash']}; revenue GBP {finance['freight_revenue']}; "
        f"construction/vehicles GBP {finance['command_construction_purchase_costs']}",
        flush=True,
    )
    print(
        f"Unallocated cash decrease GBP {finance['unallocated_company_cash_decrease']} "
        "(expense category UNKNOWN)",
        flush=True,
    )
    print("Operating costs / ROI: UNKNOWN. These are short delivery batches.", flush=True)


class Viewer:
    """Own only the GUI client launched for this run; never touch a user's client."""

    def __init__(self, root, *, headless, view_seconds):
        self.root = root
        self.headless = headless
        self.view_seconds = view_seconds
        self.process = None
        self.log = None
        self.watcher = None

    async def ready(self, backend, prepared):
        self.watcher = asyncio.create_task(self.progress(prepared.directory))
        if self.headless:
            print("Headless mode: GUI/playability is not being tested.", flush=True)
            return
        client = self.root / "client"
        client.mkdir()
        # Isolate client settings and content from both server secrets and user profile.
        shutil.copytree(prepared.spec.workspace.root / "baseset", client / "baseset")
        cfg = client / "openttd.cfg"
        cfg.write_text(
            "[misc]\ngraphicsset = OpenGFX\n[network]\nclient_name = Python Demo Viewer\n"
        )
        self.log = (client / "client.log").open("wb")
        self.process = subprocess.Popen(
            [
                str(BINARY),
                "-c",
                str(cfg),
                "-x",
                "-X",
                "-n",
                f"127.0.0.1:{prepared.endpoints[0]}#255",
            ],
            cwd=client,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        await asyncio.sleep(1)
        self.require_alive()
        print(
            "GUI client started (connection/visibility requires live verification). "
            "Inspect vehicles, stations and company finances as a spectator. "
            "Use Multiplayer to create a separate company for manual building.",
            flush=True,
        )

    def require_alive(self):
        if self.process is not None and self.process.poll() is not None:
            raise RuntimeError(
                f"Graphical client exited ({self.process.returncode}); "
                f"see {self.root / 'client/client.log'}"
            )

    async def progress(self, directory):
        shown = set()
        while True:
            self.require_alive()
            if "plan" not in shown:
                try:
                    rows = selections(directory)
                except FileNotFoundError, json.JSONDecodeError:
                    pass
                else:
                    print("\nP08/P05 selected:\n  " + "\n  ".join(rows), flush=True)
                    shown.add("plan")
            for n in range(3):
                path = directory / f"service-receipt-{n}.json"
                if n not in shown and path.exists():
                    try:
                        row = json.loads(path.read_bytes())
                    except json.JSONDecodeError:
                        continue
                    print(
                        f"Service {n + 1} delivered: "
                        f"{row['delivered']} cargo, GBP {row['payment_income']}",
                        flush=True,
                    )
                    shown.add(n)
            await asyncio.sleep(0.5)

    async def delivered(self, backend, prepared):
        if self.watcher is not None and self.watcher.done():
            await self.watcher  # Surface a client startup/runtime failure.
        self.require_alive()
        show_results(prepared.directory)
        if self.headless or self.view_seconds == 0:
            return
        print(
            f"Deliveries complete. Game stays open for up to {self.view_seconds}s. "
            "Close the client or press Ctrl+C to finish. "
            "Python's three trucks are parked after their delivery batches.",
            flush=True,
        )
        if self.process is None:
            raise RuntimeError("Graphical client was not started")
        deadline = asyncio.get_running_loop().time() + self.view_seconds
        while self.process.poll() is None and asyncio.get_running_loop().time() < deadline:
            backend.health()
            await asyncio.sleep(0.5)

    async def close(self):
        if self.watcher is not None:
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)
        try:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        await asyncio.to_thread(self.process.wait, timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        await asyncio.to_thread(self.process.wait, timeout=5)
                else:
                    self.process.wait()
        finally:
            if self.log is not None:
                self.log.close()


def report(directory, output):
    from app.planning.network_cli import main as p07

    result = p07(
        [
            str(directory / "planning-scenario.json"),
            "--native-network-directory",
            str(directory),
            "--output",
            str(output),
        ]
    )
    evaluation = json.loads((output / "evaluation.json").read_bytes())
    lines = [
        "# OpenTTD freight results",
        "",
        "P07 verified native delivery batches.",
        "",
        "| Metric | Actual | Unit |",
        "|---|---:|---|",
    ]
    for metric in evaluation["metrics"]:
        actual = metric["actual"] if metric["actual"] is not None else "UNKNOWN"
        lines.append(f"| {metric['name']} | {actual} | {metric['unit']} |")
    lines.extend(
        [
            "",
            "Services:",
            "",
            *("- " + row for row in selections(directory)),
            "",
            "These services ran serially. Full operating costs and ROI are UNKNOWN.",
            "Source: " + str(directory),
            "",
        ]
    )
    (output / "results.md").write_text("\n".join(lines))
    return result


def run_demo(*, headless=False, view_seconds=120):
    check(graphical=not headless)
    root = RUNS / ("playable-demo-" + uuid.uuid4().hex)
    print(f"Preparing deterministic seed-42, 64x64 freight world. Run: {root}", flush=True)
    try:
        prepared = native.prepare(
            root,
            demo=True,
            planner=True,
            network=True,
            scenario="high-budget-500k",
            network_service_limit=3,
        )
        viewer = Viewer(root, headless=headless, view_seconds=view_seconds)
        result = asyncio.run(
            native.run(
                prepared,
                on_ready=viewer.ready,
                on_delivered=viewer.delivered,
                on_closing=viewer.close,
            )
        )
    except KeyboardInterrupt:
        print(f"Stopped. Partial observations and cleanup: {root}", flush=True)
        return 130
    finally:
        # Preparation/preflight failures occur before the native runner owns cleanup.
        if not (root / "CLAIM.json").exists():
            for workspace in (root / "isolated").glob("openttd-15.3-*"):
                RuntimeWorkspace.reopen(workspace).close()
    if result["status"] != "NATIVE_MULTI_SERVICE_DELIVERY_VERIFIED":
        print(
            f"Demo failed: {result.get('error', result['status'])}. Logs: {root}", file=sys.stderr
        )
        return 1
    output = RUNS / (root.name + "-report")
    report(root, output)
    print(f"P07 results: {output / 'results.md'}\nGame save: {root / 'after.sav'}", flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "plan", "run"), nargs="?", default="run")
    parser.add_argument("--headless", action="store_true", help="Server only; no GUI validation")
    parser.add_argument(
        "--view-seconds",
        type=int,
        default=120,
        help="Keep game open after all three deliveries (0..300 seconds)",
    )
    parser.add_argument(
        "--stop-on-delivery",
        action="store_true",
        help="Close after all three services deliver; no viewing hold",
    )
    args = parser.parse_args(argv)
    if not 0 <= args.view_seconds <= 300:
        parser.error("--view-seconds must be between 0 and 300")
    try:
        if args.command == "check":
            check(graphical=not args.headless)
            print("Binary, assets and desktop prerequisites found; no game launched.")
            return 0
        if args.command == "plan":
            from app.planning.network_cli import main as planner

            output = RUNS / ("offline-plan-" + uuid.uuid4().hex)
            return planner([str(SAMPLE), "--output", str(output)])
        return run_demo(
            headless=args.headless, view_seconds=0 if args.stop_on_delivery else args.view_seconds
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Demo startup/run failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
