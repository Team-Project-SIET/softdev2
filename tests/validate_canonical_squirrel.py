"""Run packaged startup in unmodified OpenTTD 15.3 Squirrel; no game process/network.

Usage: PYTHONPATH=. .venv/bin/python tests/validate_canonical_squirrel.py \
  --source /tmp/canonical-squirrel-15.3 --report /tmp/canonical-squirrel-report.json
Source: git clone --depth 1 --branch 15.3 --filter=blob:none --sparse
https://github.com/OpenTTD/OpenTTD.git; sparse-checkout set src/3rdparty/squirrel
src/core src/3rdparty/fmt src/script. Compile inputs must match the pinned commit.
Game API peers are controlled; this qualifies VM suspension, not native construction.
"""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from app.simulation.openttd.proof.freight_delivery import staged_package

COMMIT = "14ec60f248547d4d062a1160f0fc26d742319888"
SUPPORT = Path(__file__).parent / "support"


def run(source: Path, report: Path):
    source = source.resolve()
    root = source / "src"
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != COMMIT:
        raise ValueError("expected exact OpenTTD 15.3 source commit")
    subprocess.run(
        ["git", "-C", str(source), "diff", "--exit-code", "HEAD", "--", "src"], check=True
    )
    sources = [
        SUPPORT / "openttd_squirrel_suspend.cpp",
        *sorted((root / "3rdparty/squirrel/squirrel").glob("*.cpp")),
        root / "core/string_consumer.cpp",
        root / "core/utf8.cpp",
    ]
    with tempfile.TemporaryDirectory(prefix="canonical-squirrel-") as tmp:
        tmp = Path(tmp)
        binary = tmp / "squirrel-host"
        subprocess.run(
            [
                "g++",
                "-std=c++20",
                "-O0",
                "-ffunction-sections",
                "-fdata-sections",
                "-Wl,--gc-sections",
                "-DFMT_HEADER_ONLY",
                "-I" + str(root / "3rdparty/squirrel/include"),
                "-I" + str(root / "3rdparty/squirrel/squirrel"),
                "-include",
                str(root / "stdafx.h"),
                *map(str, sources),
                "-o",
                str(binary),
            ],
            check=True,
            timeout=180,
        )
        package = staged_package(True, True, True, "high-budget-500k", 3, 5, canonical=True)
        seen = set()

        def expand(name):
            if name in seen:
                return ""
            seen.add(name)
            return re.sub(r'require\("([^"]+)"\);', lambda m: expand(m[1]), package[name].decode())

        code = (SUPPORT / "canonical_startup_vm.nut").read_text() + expand("main.nut")
        finish = """
::b <- CanonicalFreightProof();
try {b.Start();throw "START_DID_NOT_FINISH";}catch(e){if(e!="STARTUP_COMPLETE")throw e;}
if(world.len()!=6||b.observer==null||tree!=-1)throw "INITIALIZATION_ORDER";
if(events[0].find("FREIGHT_GAME_TIME_START")!=0)throw "START_ORDER";
local before=0;local after=0;local ready=-1;
foreach(i,e in events){
 if(e=="before-command")before++;
 if(e=="after-command")after++;
 if(e.find("FREIGHT_DELIVERY_READY")==0)ready=i;
 if(before<after||before>after+1)throw "RESUMPTION_ORDER";
}
if(before!=6||after!=6||ready!=events.len()-1)throw "READY_BEFORE_COMMAND_COMPLETE";
// Instance slot lookup must preserve receiver identity, including restored no-op.
local c=CanonicalFreightProof();c.restored_fleet=true;c.PrepareDemo();
if(world.len()!=6||c.observer!=null)throw "RESTORED_REBUILT";
"""
        results = []

        def case(name, text, expected, commands=None):
            path = tmp / (name + ".nut")
            path.write_text(text)
            result = subprocess.run(
                [str(binary), str(path)], capture_output=True, text=True, timeout=10
            )
            output = result.stdout + result.stderr
            if (expected is None and result.returncode != 0) or (
                expected is not None and (result.returncode == 0 or expected not in output)
            ):
                raise AssertionError(f"{name}: {result.returncode}: {output}")
            if commands is not None and f"commands={commands}" not in output:
                raise AssertionError(f"{name}: {output}")
            results.append(
                {
                    "case": name,
                    "returncode": result.returncode,
                    "output": output.strip(),
                    "script_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            )
            print(name + ": " + output.strip(), flush=True)

        case("packaged-startup", code + finish, None, 7)
        case(
            "q1-boundary-regression",
            code.replace(
                "return PrepareNetworkDemo();",
                "return NetworkFreightProof.PrepareDemo.call(this);",
                1,
            )
            + finish,
            "COMMAND_NOT_SUSPENDABLE",
        )
        case("command-false", code + "::fail_build=0;" + finish, "NETWORK_INDUSTRY_BUILD_FAILED")
        case(
            "command-error",
            code.replace("local result=NativeCommand();", 'local result=NativeCommand("error");', 1)
            + finish,
            "NATIVE_COMMAND_ERROR",
        )
        # Exercise each command-bearing delegate's receiver and native frame depth.
        delegates = code.replace(
            "ExecuteNetworkCommand=NetworkFreightProof.Execute;",
            'function ExecuteNetworkCommand(i){if(this!=::b||i!=6)throw "BAD_RECEIVER";'
            "return NativeCommand();}",
        ).replace(
            "HandleContinuousRequest=ContinuousFreightProof.Handle;",
            'function HandleContinuousRequest(q){if(this!=::b||q.type!="delegate-probe")'
            'throw "BAD_RECEIVER";return NativeCommand();}',
        )
        invocation = (
            '::b<-CanonicalFreightProof();\nif(!b.Execute(6)){throw "EXECUTE_RESULT";}\n'
            'if(!b.Handle({type="delegate-probe"})){throw "HANDLE_RESULT";}\n'
        )
        case("command-delegates", delegates + invocation, None, 2)
        case(
            "execute-old-boundary",
            delegates.replace(
                "return ExecuteNetworkCommand(i);", "return ExecuteNetworkCommand.call(this,i);"
            )
            + invocation,
            "COMMAND_NOT_SUSPENDABLE",
        )
        case(
            "handle-old-boundary",
            delegates.replace(
                "return HandleContinuousRequest(q);", "return HandleContinuousRequest.call(this,q);"
            )
            + invocation,
            "COMMAND_NOT_SUSPENDABLE",
        )
        protocol = code + (SUPPORT / "canonical_protocol_vm.nut").read_text()
        complete = "for(local n=0;n<3;n++){SelectService(n);BuildService(n);SealService(n);}"
        case(
            "canonical-three-service-protocol",
            protocol + complete + "b.CanonicalOriginals(true);",
            None,
            33,
        )
        case(
            "canonical-old-order",
            protocol + "SelectService(0);SelectService(1);",
            "CANONICAL_UNSEALED_SERVICE",
        )
        case(
            "canonical-missing-seal",
            protocol + "SelectService(0);BuildService(0);SelectService(1);",
            "CANONICAL_UNSEALED_SERVICE",
        )
        case(
            "canonical-early-seal",
            protocol + "SelectService(0);SealService(0);",
            "CANONICAL_SEAL_INVALID",
        )
        case(
            "canonical-duplicate-seal",
            protocol + "SelectService(0);BuildService(0);SealService(0);SealService(0);",
            "CANONICAL_REQUEST_REPLAY",
        )
        case(
            "canonical-duplicate-selection",
            protocol + "SelectService(0);BuildService(0);SealService(0);b.Handle(Selection(0));",
            "CANONICAL_DUPLICATE_SERVICE",
        )
        case(
            "canonical-construction-order",
            protocol + 'SelectService(0);b.Handle(Request("build",0,1,"wrong-stage"));'
            'if(responses.top().status!="REJECTED"||!b.dfailed)throw "ORDER_ACCEPTED";',
            None,
        )
        case(
            "canonical-partial-command",
            protocol + "SelectService(0);::failed_command=true;"
            'b.Handle(Request("build",0,0,"failed-build"));'
            'if(responses.top().status!="CONSTRUCTION_FAILED"||!b.dfailed)'
            'throw "ERROR_NOT_RETAINED";\nSelectService(1);',
            "CANONICAL_UNSEALED_SERVICE",
        )
        case(
            "canonical-wrong-service-seal",
            protocol + "SelectService(0);BuildService(0);SealService(1);",
            "CANONICAL_SEAL_INVALID",
        )
        case(
            "canonical-duplicate-seal-new-id",
            protocol
            + 'SelectService(0);BuildService(0);SealService(0);SealService(0,"seal-again");',
            "CANONICAL_SEAL_INVALID",
        )
        case(
            "canonical-partial-mutation",
            protocol + "SelectService(0);::partial_command=true;"
            'b.Handle(Request("build",0,0,"partial-build"));'
            'if(roads.len()==0||responses.top().status!="CONSTRUCTION_FAILED"||!b.dfailed)'
            'throw "PARTIAL_NOT_RETAINED";\nSelectService(1);',
            "CANONICAL_UNSEALED_SERVICE",
        )
        case(
            "canonical-old-zero-fleet-policy",
            protocol.replace(
                "if(!SelectionFleetReady()||GSGame.IsPaused()",
                "if(GSVehicleList().Count()!=0||GSGame.IsPaused()",
            )
            + "SelectService(0);BuildService(0);SealService(0);SelectService(1);",
            "SELECT_NOT_READY",
        )
        collector = protocol + complete + "::paused=true;"
        case(
            "collector-same-world-context",
            collector + "InitializeCollector();CollectorDepots();",
            None,
            33,
        )
        restored = collector + "RestoreForCollector();"
        case(
            "collector-uninitialized-reload",
            restored + "CollectorDepots();",
            "ROAD_CONTEXT_DEPOT_MISMATCH",
        )
        case(
            "collector-wrong-road-type",
            restored + "::road_type=1;CollectorDepots();",
            "ROAD_CONTEXT_DEPOT_MISMATCH",
        )
        case(
            "collector-fresh-reload-context",
            restored + "InitializeCollector();CollectorDepots();",
            None,
            33,
        )
        case(
            "collector-wrong-type-corrected",
            restored + "::road_type=1;InitializeCollector();CollectorDepots();",
            None,
            33,
        )
        case(
            "collector-unavailable-road-type",
            restored + "::road_available=false;InitializeCollector();",
            "CONTEXT_READ_REJECTED",
        )
        with report.open("x") as output:
            output.write(
                json.dumps(
                    {
                        "source_commit": revision,
                        "compiler": subprocess.check_output(["g++", "--version"], text=True),
                        "host_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                        "compiled_source_sha256": {
                            str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sources
                        },
                        "scope": (
                            "packaged startup and canonical protocol VM execution; "
                            "controlled game API peers; zero OpenTTD launches"
                        ),
                        "package_sha256": {
                            k: hashlib.sha256(v).hexdigest() for k, v in sorted(package.items())
                        },
                        "helper_sha256": {
                            str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in [
                                Path(__file__),
                                *sorted(SUPPORT.glob("*suspend.cpp")),
                                SUPPORT / "canonical_startup_vm.nut",
                                SUPPORT / "canonical_protocol_vm.nut",
                            ]
                        },
                        "results": results,
                    },
                    indent=2,
                )
                + "\n"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.report)
