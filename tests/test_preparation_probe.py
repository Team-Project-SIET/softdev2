"""P08 framed extraction boundary: no native OpenTTD process."""

import json
import zlib

import pytest

from app.planning.preparation.failures import PreparationError
from app.planning.preparation.probe import parse_extraction
from tests.test_planning_preparation import request, synthetic_world


def frames(world=None):
    world = world or synthetic_world()
    data = world.model_dump(mode="json")
    rows = []
    counts = {
        "tile": len(world.tiles),
        "industry": len(world.industries),
        "cargo": len(world.cargos),
        "engine": len(world.engines),
        "cost": 1,
    }
    meta = {
        k: v
        for k, v in data.items()
        if k
        not in {
            "tiles",
            "industries",
            "cargos",
            "engines",
            "prepared_save_digest",
            "complete",
            "road_build_cost_gbp",
            "station_build_cost_gbp",
            "depot_build_cost_gbp",
        }
    }
    meta["counts"] = counts
    rows.append(("meta", meta))
    for kind, field in (
        ("tile", "tiles"),
        ("industry", "industries"),
        ("cargo", "cargos"),
        ("engine", "engines"),
    ):
        rows.extend((kind, body) for body in data[field])
    rows.append(
        (
            "cost",
            {
                k: data[k]
                for k in ("road_build_cost_gbp", "station_build_cost_gbp", "depot_build_cost_gbp")
            },
        )
    )
    lines, checksum = [], 1
    for seq, (kind, body) in enumerate(rows):
        line = f"P08|{seq}|{kind}|" + json.dumps(body, separators=(",", ":"), sort_keys=True)
        lines.append(line)
        checksum = zlib.adler32((line + "\n").encode(), checksum)
    lines.append(
        f"P08|{len(rows)}|done|" + json.dumps({"counts": counts, "adler32": f"{checksum:08x}"})
    )
    return lines


def test_complete_sequenced_snapshot_round_trip():
    world = parse_extraction(frames(), request(), "a" * 64)
    assert world == synthetic_world()
    assert parse_extraction(["[script] " + line for line in frames()], request(), "a" * 64) == world


@pytest.mark.parametrize(
    "mutation", ["missing", "count", "digest", "duplicate", "after", "no-done"]
)
def test_partial_or_forged_stream_never_publishes_snapshot(mutation):
    lines = frames()
    if mutation == "missing":
        del lines[3]
    elif mutation == "duplicate":
        lines.insert(4, lines[3])
    elif mutation == "after":
        lines.append(lines[2])
    elif mutation == "count":
        terminal = json.loads(lines[-1].split("|", 3)[3])
        terminal["counts"]["tile"] += 1
        lines[-1] = (
            lines[-1].split("|", 3)[0]
            + "|"
            + lines[-1].split("|", 3)[1]
            + "|done|"
            + json.dumps(terminal)
        )
    elif mutation == "digest":
        lines[3] = lines[3].replace('"height":1', '"height":2')
    else:
        lines.pop()
    with pytest.raises(PreparationError, match="EXTRACTION_INCOMPLETE"):
        parse_extraction(lines, request(), "a" * 64)


def test_actual_gamescript_runs_on_query_only_13_4_fake_and_becomes_inert():
    from pathlib import Path

    from squirrel import SQVM

    from app.planning.preparation.probe import PROBE_DIRECTORY
    from app.planning.transport import _literal

    world = synthetic_world()
    vm = SQVM()
    vm.execute("::WORLD <- " + _literal(world.model_dump(mode="json")) + ";")
    config = {
        "company_id": 0,
        "seed": 42,
        "source_save_digest": "a" * 64,
        "profile": world.profile.model_dump(mode="json"),
        "limits": request().limits.model_dump(mode="json"),
    }
    vm.execute("::P08_REQUEST <- " + _literal(config) + ";")
    vm.execute((Path(__file__).with_name("fixtures") / "p08_query_api.nut").read_text())
    vm.execute((PROBE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        "::probe <- P08Preparation(); try { probe.Start(); } "
        'catch(e) { if (e != "CONTROLLED_STOP") throw e; }'
    )
    root = vm.get_roottable()
    lines = [str(line) for line in root["logs"]]
    snapshot = parse_extraction(lines, request(), "a" * 64)
    assert snapshot.width_tiles == 12
    assert snapshot.industries == world.industries
    assert snapshot.engines == world.engines
    assert root["company_contexts"] == 2
    assert root["probe"]["completed"]
    vm.execute("probe.Extract();")
    assert [str(line) for line in root["logs"]] == lines
    assert root["query_count"] == 1


def test_probe_query_names_and_fake_arities_match_pinned_native_headers():
    import re
    from pathlib import Path

    from app.planning.preparation.probe import PROBE_DIRECTORY

    source = (PROBE_DIRECTORY / "main.nut").read_text()
    fake = (Path(__file__).with_name("fixtures") / "p08_query_api.nut").read_text()
    native = json.loads((Path(__file__).with_name("fixtures") / "p08_api_13_4.json").read_text())
    methods = {(row["class"], row["method"]): row["arity"] for row in native}
    assert set(re.findall(r"(GS\w+)\.(\w+)\(", source)) == set(methods)
    for (cls, method), arity in methods.items():
        class_match = re.search(r"class " + cls + r"\s*\{(.*?)(?=\nclass |\Z)", fake, re.S)
        assert class_match is not None
        method_match = re.search(r"function " + method + r"\((.*?)\)", class_match.group(1))
        assert method_match is not None
        parameters = method_match.group(1)
        assert (0 if not parameters else len(parameters.split(","))) == arity
    assert not re.search(
        r"\.(Build|Remove|Demolish|Terraform|Plant|Set|Pause|Unpause)\w*\(", source
    )
    assert "Sleep(1000)" in source


@pytest.mark.parametrize(
    "code",
    [
        "UNSUPPORTED_WORLD",
        "CANDIDATE_LIMIT_EXCEEDED",
        "WORLD_CHANGED_DURING_PREPARATION",
        "CATALOG_IDENTITY_MISMATCH",
    ],
)
def test_sequenced_failure_frame_preserves_typed_native_rejection(code):
    row = "P08|0|failure|" + json.dumps(
        {"code": code, "message": "controlled rejection", "adler32": "00000001"}
    )
    with pytest.raises(PreparationError, match=code):
        parse_extraction([row], request(), "a" * 64)


def test_probe_save_load_retains_inert_completion():
    from pathlib import Path

    from squirrel import SQVM

    from app.planning.preparation.probe import PROBE_DIRECTORY

    vm = SQVM()
    vm.execute((Path(__file__).with_name("fixtures") / "p08_query_api.nut").read_text())
    vm.execute((PROBE_DIRECTORY / "main.nut").read_text())
    vm.execute("::probe <- P08Preparation(); probe.Load(1, {completed=true}); probe.Extract();")
    assert list(vm.get_roottable()["logs"]) == []


@pytest.mark.parametrize(
    "condition,expected",
    [
        ("climate", "UNSUPPORTED_WORLD"),
        ("companies", "UNSUPPORTED_WORLD"),
        ("bound", "CANDIDATE_LIMIT_EXCEEDED"),
    ],
)
def test_actual_probe_emits_typed_native_failure_and_becomes_inert(condition, expected):
    from pathlib import Path

    from squirrel import SQVM

    from app.planning.preparation.probe import PROBE_DIRECTORY
    from app.planning.transport import _literal

    world = synthetic_world()
    vm = SQVM()
    vm.execute("::WORLD <- " + _literal(world.model_dump(mode="json")) + ";")
    limits = request().limits.model_dump(mode="json")
    if condition == "bound":
        limits["map_tiles"] = 1
    config = {
        "company_id": 0,
        "seed": 42,
        "source_save_digest": "a" * 64,
        "profile": world.profile.model_dump(mode="json"),
        "limits": limits,
    }
    vm.execute("::P08_REQUEST <- " + _literal(config) + ";")
    fake = (Path(__file__).with_name("fixtures") / "p08_query_api.nut").read_text()
    if condition == "climate":
        fake = fake.replace("GetLandscape() { return 0; }", "GetLandscape() { return 1; }")
    if condition == "companies":
        fake = fake.replace("return id == 0 ? 0 : -1;", "return id == 0 || id == 1 ? id : -1;")
    vm.execute(fake)
    vm.execute((PROBE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        "::probe <- P08Preparation(); try { probe.Start(); } "
        'catch(e) { if(e != "CONTROLLED_STOP") throw e; }'
    )
    root = vm.get_roottable()
    rows = [str(row) for row in root["logs"]]
    with pytest.raises(PreparationError, match=expected):
        parse_extraction(rows, request(), "a" * 64)
    vm.execute("probe.Extract();")
    assert [str(row) for row in root["logs"]] == rows
