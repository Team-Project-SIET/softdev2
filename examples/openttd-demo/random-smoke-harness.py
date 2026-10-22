"""Consume exactly one independently reviewed prepared smoke. No retries."""

import asyncio
import ctypes as c
import json
import os
import subprocess
import sys
from pathlib import Path

from app.demo_smoke_preflight import require_independent_preflight
from app.openttd_demo import Viewer, report
from app.simulation.openttd.proof import freight_delivery as native
from app.simulation.openttd.proof.harness import manifest, sha256
from app.simulation.openttd.proof.road_mutation import console

review = Path(sys.argv[1]).resolve()
intent = json.loads((review / "frozen-inputs.json").read_bytes())
root = Path(intent["run_directory"])
assert (
    sha256(review / "frozen-inputs.json") == (review / "frozen-inputs.sha256").read_text().strip()
)
independent = json.loads((review / "independent-preflight.json").read_bytes())
require_independent_preflight(
    independent,
    frozen_inputs_sha256=sha256(review / "frozen-inputs.json"),
    prelaunch_sha256=intent["prelaunch_sha256"],
)
assert sha256(Path(__file__)) == (review / "launch-harness.sha256").read_text().strip()
assert os.environ.get("SDL_VIDEODRIVER") == "x11"
for path, digest in intent["extra_source_hashes"].items():
    assert sha256(Path(path)) == digest, "Reviewed source changed: " + path
assert sha256(root / "PRELAUNCH.json") == intent["prelaunch_sha256"]
assert not (root / "CLAIM.json").exists()
prepared = native.reopen(root)
native.preflight(prepared)
viewer = Viewer(root, headless=False, view_seconds=intent["view_seconds"])


def owned_window(pid):
    x = c.CDLL("libX11.so.6")
    x.XOpenDisplay.argtypes = [c.c_char_p]
    x.XOpenDisplay.restype = c.c_void_p
    display = x.XOpenDisplay(None)
    if not display:
        return None
    x.XDefaultRootWindow.argtypes = [c.c_void_p]
    x.XDefaultRootWindow.restype = c.c_ulong
    x.XInternAtom.argtypes = [c.c_void_p, c.c_char_p, c.c_int]
    x.XInternAtom.restype = c.c_ulong
    atom = x.XInternAtom(display, b"_NET_WM_PID", 1)
    x.XQueryTree.argtypes = [
        c.c_void_p,
        c.c_ulong,
        c.POINTER(c.c_ulong),
        c.POINTER(c.c_ulong),
        c.POINTER(c.POINTER(c.c_ulong)),
        c.POINTER(c.c_uint),
    ]
    x.XGetWindowProperty.argtypes = [
        c.c_void_p,
        c.c_ulong,
        c.c_ulong,
        c.c_long,
        c.c_long,
        c.c_int,
        c.c_ulong,
        c.POINTER(c.c_ulong),
        c.POINTER(c.c_int),
        c.POINTER(c.c_ulong),
        c.POINTER(c.c_ulong),
        c.POINTER(c.POINTER(c.c_ubyte)),
    ]
    x.XFree.argtypes = [c.c_void_p]
    found = []

    def scan(window, depth=0):
        actual = c.c_ulong()
        fmt = c.c_int()
        count = c.c_ulong()
        after = c.c_ulong()
        data = c.POINTER(c.c_ubyte)()
        x.XGetWindowProperty(
            display,
            window,
            atom,
            0,
            1,
            0,
            0,
            c.byref(actual),
            c.byref(fmt),
            c.byref(count),
            c.byref(after),
            c.byref(data),
        )
        if data:
            if fmt.value == 32 and count.value and c.cast(data, c.POINTER(c.c_ulong))[0] == pid:
                found.append(window)
            x.XFree(data)
        if depth >= 6:
            return
        parent = c.c_ulong()
        tree = c.c_ulong()
        children = c.POINTER(c.c_ulong)()
        n = c.c_uint()
        if x.XQueryTree(
            display, window, c.byref(tree), c.byref(parent), c.byref(children), c.byref(n)
        ):
            for i in range(n.value):
                scan(children[i], depth + 1)
            if children:
                x.XFree(children)

    scan(x.XDefaultRootWindow(display))
    if not found:
        x.XCloseDisplay.argtypes = [c.c_void_p]
        x.XCloseDisplay(display)
        return None
    return x, display, found[-1]


async def ready(backend, p):
    await viewer.ready(backend, p)
    assert viewer.process is not None
    actual_argv = (
        (Path("/proc") / str(viewer.process.pid) / "cmdline")
        .read_bytes()
        .rstrip(b"\0")
        .decode()
        .split("\0")
    )
    assert actual_argv == intent["client_argv"], "Client argv differs from frozen intent"
    assert sha256(root / "client/openttd.cfg") == intent["client_config_sha256"]
    assert (Path("/proc") / str(viewer.process.pid) / "exe").resolve() == native.BINARY.resolve()
    for name, digest in intent["client_assets"].items():
        assert sha256(root / "client/baseset" / name) == digest
    deadline = asyncio.get_running_loop().time() + 20
    window = None
    while asyncio.get_running_loop().time() < deadline:
        viewer.require_alive()
        backend.health()
        window = owned_window(viewer.process.pid)
        log = p.spec.stdout_path.read_text(errors="replace") + p.spec.stderr_path.read_text(
            errors="replace"
        )
        if window and "Python Demo Viewer has joined the game" in log:
            break
        if window:
            x, d, _ = window
            x.XCloseDisplay.argtypes = [c.c_void_p]
            x.XCloseDisplay(d)
            window = None
        await asyncio.sleep(0.25)
    if window is None:
        raise RuntimeError("GUI spectator join/window verification timed out; no retry")
    x, d, w = window
    try:
        console(backend, "clients")  # verified OpenTTD 15.3 read-only console command
        subprocess.run(
            ["/usr/bin/import", "-window", hex(w), str(review / "gui-joined.png")],
            check=True,
            timeout=10,
        )
        x.XRaiseWindow.argtypes = [c.c_void_p, c.c_ulong]
        x.XRaiseWindow(d, w)
        x.XSetInputFocus.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_ulong]
        x.XSetInputFocus(d, w, 1, 0)
        x.XKeysymToKeycode.argtypes = [c.c_void_p, c.c_ulong]
        x.XKeysymToKeycode.restype = c.c_uint
        key = x.XKeysymToKeycode(d, 0xFF53)
        xt = c.CDLL("libXtst.so.6")
        xt.XTestFakeKeyEvent.argtypes = [c.c_void_p, c.c_uint, c.c_int, c.c_ulong]
        xt.XTestFakeKeyEvent(d, key, 1, 0)
        xt.XTestFakeKeyEvent(d, key, 0, 200)
        x.XSync.argtypes = [c.c_void_p, c.c_int]
        x.XSync(d, 0)
        await asyncio.sleep(0.3)
        subprocess.run(
            ["/usr/bin/import", "-window", hex(w), str(review / "gui-inspected.png")],
            check=True,
            timeout=10,
        )
        (review / "gui-observation.json").write_text(
            json.dumps(
                dict(
                    pid=viewer.process.pid,
                    window=hex(w),
                    spectator_requested=255,
                    process_image_verified=True,
                    client_inputs_match=True,
                    join_log_observed=True,
                    read_only_navigation="arrow-right",
                    visible_gameplay="PENDING_VISUAL_INSPECTION",
                ),
                indent=2,
            )
        )
        print(
            "OBSERVED graphical spectator joined; owned window captured for visual verification.",
            flush=True,
        )
    finally:
        x.XCloseDisplay.argtypes = [c.c_void_p]
        x.XCloseDisplay(d)


async def delivered(backend, p):
    await viewer.delivered(backend, p)


with (review / "launch-authorization-consumed.json").open("x") as stream:
    stream.write(
        json.dumps(
            dict(
                one_shot=True,
                server_launches_allowed=1,
                client_launches_allowed=1,
                admin_connections_allowed=1,
                retries=0,
                reconnects=0,
                prelaunch_sha256=intent["prelaunch_sha256"],
                independent_preflight_sha256=sha256(review / "independent-preflight.json"),
                harness_sha256=sha256(Path(__file__)),
            )
        )
    )
result = asyncio.run(
    native.run(prepared, on_ready=ready, on_delivered=delivered, on_closing=viewer.close)
)
outcome = dict(
    native_result=result,
    server_manifest_verified=manifest(root) == (root / "artifact-manifest.sha256").read_text(),
    gui_evidence_present=(review / "gui-observation.json").exists(),
    p07_report=None,
)
if result["status"] == "NATIVE_MULTI_SERVICE_DELIVERY_VERIFIED":
    try:
        code = report(root, Path(intent["report_directory"]))
        outcome["p07_report"] = dict(exit_code=code, directory=intent["report_directory"])
    except Exception as error:
        outcome["p07_report"] = dict(error=type(error).__name__ + ": " + str(error))
if viewer.process is not None:
    outcome["client_cleanup"] = dict(
        pid=viewer.process.pid,
        reaped=viewer.process.poll() is not None,
        returncode=viewer.process.returncode,
    )
(review / "smoke-outcome.json").write_text(json.dumps(outcome, indent=2) + "\n")
print(json.dumps(outcome, indent=2), flush=True)
sys.exit(
    0
    if result["status"] == "NATIVE_MULTI_SERVICE_DELIVERY_VERIFIED"
    and outcome["p07_report"].get("exit_code") == 0  # ty: ignore[unresolved-attribute]
    else 1
)
