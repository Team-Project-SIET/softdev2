"""Controlled preparation command replay; never native construction proof."""

import json
import zipfile

import pytest
from test_native_freight_network import network_vm

from app.simulation.openttd.proof import freight_delivery as proof

HISTORICAL = proof.PROJECT / "artifacts/runtime/openttd-15.3-first-freight-delivery-attempt10"


def world_vm(*, multiple=True, fail_at=-1):
    vm = network_vm()
    vm.execute(
        """
        ::world_industries <- [];
        ::prep_logs <- [];
        ::GSLog = class {static function Info(s){::prep_logs.append(s);}};
        ::build_attempts <- [];
        ::multiple <- MULTIPLE;
        ::fail_at <- FAIL_AT;
        ::GSGameSettings <- class {
            static function GetValue(name){return ::multiple?1:0;}
        };
        ::GSError <- class {static function GetLastError(){return 17;}};
        ::GSMap = class extends GSMap {
            static function GetMapSizeX(){return 64;}
            static function GetMapSizeY(){return 64;}
        };
        ::DemoCargoList <- class {
            function Count(){return 1;}function Begin(){return 3;}
            function HasItem(c){return c==3;}
        };
        ::GSIndustryType <- class {
            static function GetProducedCargo(t){return DemoCargoList();}
            static function GetAcceptedCargo(t){return DemoCargoList();}
            static function IsRawIndustry(t){return t==0;}
            static function BuildIndustry(t,tile){
                ::build_attempts.append([t,tile]);
                if(::build_attempts.len()==::fail_at)return false;
                // OpenTTD 15.3 FindTownForIndustry: this retained map has one town.
                if(!::multiple)foreach(i in ::world_industries)if(i.type==t)return false;
                ::world_industries.append({type=t,tile=tile});return true;
            }
        };
        ::GSIndustry = class extends GSIndustry {
            static function GetIndustryCount(){return ::world_industries.len();}
            static function GetIndustryType(i){return ::world_industries[i].type;}
            static function GetLocation(i){return ::world_industries[i].tile;}
            static function IsValidIndustry(i){return i>=0&&i<::world_industries.len();}
            static function GetIndustryID(t){
                foreach(i,c in ::world_industries)if(c.tile==t)return i;return -1;
            }
        };
        ::WorldIndustries <- class {
            ids=null;pos=0;
            constructor(t=-1){ids=[];foreach(i,c in ::world_industries)
                if(t<0||c.type==t)ids.append(i);}
            function Count(){return ids.len();}
            function Begin(){pos=0;return ids.len()?ids[0]:-1;}
            function Next(){pos++;return pos<ids.len()?ids[pos]:-1;}
            function IsEnd(){return pos>=ids.len();}
        };
        ::GSIndustryList <- class extends WorldIndustries {constructor(){base.constructor();}};
        ::GSIndustryList_CargoAccepting = class extends WorldIndustries {
            constructor(c){base.constructor(1);}
        };
        ::GSTile = class extends GSTile {
            static function IsBuildable(t){return GSIndustry.GetIndustryID(t)<0;}
        };
    """.replace("MULTIPLE", "true" if multiple else "false").replace("FAIL_AT", str(fail_at))
    )
    return vm


def attempts(vm):
    values = vm.get_roottable()["build_attempts"]
    return [(int(values[i][0]), int(values[i][1])) for i in range(len(values))]


def test_attempt10_exact_same_town_failure_replay():
    vm = world_vm(multiple=False)
    with zipfile.ZipFile(HISTORICAL / "frozen-source.zip") as archive:
        code = archive.read("staged/main.nut").decode()
    vm.execute(code.replace('require("network-parent.nut");', ""))
    with pytest.raises(Exception, match="NETWORK_INDUSTRY_BUILD_FAILED"):
        vm.execute("::bridge=NetworkFreightProof();bridge.PrepareDemo();")
    assert attempts(vm) == [(0, 1300), (1, 1828), (0, 2836)]
    assert len(vm.get_roottable()["world_industries"]) == 2


def test_multi_industry_preparation_is_deterministic():
    expected = [(0, 1300), (1, 1828), (0, 2836), (1, 3364)]
    for _ in range(2):
        vm = world_vm()
        vm.execute("bridge.PrepareDemo();")
        assert attempts(vm) == expected
        assert len(vm.get_roottable()["world_industries"]) == 4
        logs = vm.get_roottable()["prep_logs"]
        assert str(logs[len(logs) - 1]).startswith("FREIGHT_NETWORK_WORLD_READY cleared_bound=")
        assert int(str(logs[len(logs) - 1]).split("=")[-1]) <= 104


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_failed_industry_construction_stops_without_retry(fail_at):
    vm = world_vm(fail_at=fail_at)
    with pytest.raises(Exception, match="NETWORK_INDUSTRY_BUILD_FAILED"):
        vm.execute("bridge.PrepareDemo();")
    assert len(attempts(vm)) == fail_at
    assert len(vm.get_roottable()["world_industries"]) == fail_at - 1
    if fail_at > 1:
        with pytest.raises(Exception, match="NETWORK_REQUIRES_EMPTY"):
            vm.execute("bridge.PrepareDemo();")
        assert len(attempts(vm)) == fail_at


def test_current_layout_rejects_same_town_conflict():
    vm = world_vm(multiple=False)
    with pytest.raises(Exception, match="NETWORK_REQUIRES_MULTIPLE_INDUSTRY_PER_TOWN"):
        vm.execute("bridge.PrepareDemo();")
    assert attempts(vm) == []
    assert len(vm.get_roottable()["world_industries"]) == 0


def test_network_preparation_seals_safe_setting_and_pristine_source(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline preparation launched or connected")

    monkeypatch.setattr(proof.DemoBackend, "launch", forbidden)
    monkeypatch.setattr(proof.DeliverySession, "connect_secure", forbidden)
    prepared = proof.prepare(
        tmp_path / "openttd-15.3-first-freight-delivery-attempt1",
        demo=True,
        planner=True,
        network=True,
    )
    try:
        proof.preflight(prepared)
        config_text = prepared.spec.workspace.config.read_text()
        economy = first_native_ini_group(config_text, "economy")
        assert economy["multiple_industry_per_town"] == "true"
        assert economy["timekeeping_units"] == "0"
        assert config_text.count("[economy]") == 1
        vm = world_vm(multiple=economy.get("multiple_industry_per_town") == "true")
        vm.execute("bridge.PrepareDemo();")
        assert len(vm.get_roottable()["world_industries"]) == 4
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_bytes())
        assert metadata["source"]["kind"] == "NATIVE_FLAT_HEIGHTMAP"
        with zipfile.ZipFile(prepared.directory / "frozen-source.zip") as archive:
            assert archive.read("staged/openttd.cfg") == prepared.spec.workspace.config.read_bytes()
            assert (
                archive.read("staged/main.nut")
                == proof.staged_package(True, True, True)["main.nut"]
            )
        assert not (prepared.directory / "CLAIM.json").exists()
        (prepared.spec.workspace.root / "failure.sav").write_bytes(b"mutated disposable world")
        with pytest.raises(ValueError, match="save|pristine|disposable"):
            proof.preflight(prepared)
    finally:
        prepared.spec.workspace.close()


def test_native_powerstation_anchor_hole_is_not_a_missing_industry():
    vm = world_vm()
    vm.execute("""
        GSIndustry.GetIndustryID <- function(t) {
            foreach(i,c in ::world_industries)if(c.tile==t&&c.type==0)return i;
            return -1;
        };
    """)
    vm.execute("bridge.PrepareDemo();")
    assert len(attempts(vm)) == 4
    assert len(vm.get_roottable()["world_industries"]) == 4


@pytest.mark.parametrize("bad_readback", ["count", "type", "location"])
def test_success_return_requires_independent_industry_readback(bad_readback):
    vm = world_vm()
    overrides = {
        "count": "GSIndustry.GetIndustryCount <- function(){return 0;};",
        "type": "GSIndustry.GetIndustryType <- function(i){return 1;};",
        "location": "GSIndustry.GetLocation <- function(i){return 1301;};",
    }
    vm.execute(overrides[bad_readback])
    with pytest.raises(Exception, match="NETWORK_INDUSTRY_BUILD_READBACK_FAILED"):
        vm.execute("bridge.PrepareDemo();")
    assert attempts(vm) == [(0, 1300)]
    assert len(vm.get_roottable()["world_industries"]) == 1


@pytest.mark.parametrize("terrain", ["slope", "height", "water", "occupied"])
def test_site_conflicts_abort_before_first_build(terrain):
    vm = world_vm()
    overrides = {
        "slope": "GSTile.GetSlope <- function(t){return 1;};",
        "height": "GSTile.GetMinHeight <- function(t){return 2;};",
        "water": "GSTile.IsWaterTile <- function(t){return true;};",
        "occupied": (
            "GSIndustry.GetIndustryID <- function(t){return 0;};"
            "GSIndustry.IsValidIndustry <- function(i){return true;};"
        ),
    }
    vm.execute(overrides[terrain])
    with pytest.raises(Exception, match="NETWORK_INDUSTRY_SITE_CONFLICT"):
        vm.execute("bridge.PrepareDemo();")
    assert attempts(vm) == []


@pytest.mark.parametrize(
    "contamination",
    ["nested_save", "runtime_heightmap", "retained_heightmap", "symlink", "wrong_kind"],
)
def test_network_input_guard_rejects_mutated_source(tmp_path, contamination):
    from types import SimpleNamespace

    root = tmp_path / "world"
    root.mkdir()
    directory = tmp_path / "evidence"
    directory.mkdir()
    png = proof.flat_heightmap()
    (root / "heightmap.png").write_bytes(png)
    (directory / "heightmap.png").write_bytes(png)
    config = root / "openttd.cfg"
    config.write_text("[economy]\ntimekeeping_units = 0\nmultiple_industry_per_town = true\n")
    prepared = SimpleNamespace(
        directory=directory,
        spec=SimpleNamespace(workspace=SimpleNamespace(root=root, config=config)),
    )
    metadata = {
        "source": {
            "kind": "NATIVE_FLAT_HEIGHTMAP",
            "input_sha256": proof.sha256(directory / "heightmap.png"),
        }
    }
    proof.validate_network_world_inputs(prepared, metadata)
    if contamination == "nested_save":
        (root / "save").mkdir()
        (root / "save" / "FAILURE.SAV").write_bytes(b"partial")
    elif contamination == "symlink":
        (root / "heightmap.png").unlink()
        (root / "heightmap.png").symlink_to(directory / "heightmap.png")
    elif contamination == "wrong_kind":
        metadata["source"]["kind"] = "COPIED_NATIVE_PROVEN_COMPANY_WORLD"
    else:
        target = root if contamination == "runtime_heightmap" else directory
        (target / "heightmap.png").write_bytes(b"changed")
    with pytest.raises(ValueError):
        proof.validate_network_world_inputs(prepared, metadata)


def test_failed_command_that_mutates_world_cannot_continue_or_reenter():
    vm = world_vm()
    vm.execute("""
        GSIndustryType.BuildIndustry <- function(t,tile) {
            ::build_attempts.append([t,tile]);
            ::world_industries.append({type=t,tile=tile});
            return ::build_attempts.len()!=3;
        };
    """)
    with pytest.raises(Exception, match="NETWORK_INDUSTRY_BUILD_FAILED"):
        vm.execute("bridge.PrepareDemo();")
    assert attempts(vm) == [(0, 1300), (1, 1828), (0, 2836)]
    assert len(vm.get_roottable()["world_industries"]) == 3
    with pytest.raises(Exception, match="NETWORK_REQUIRES_EMPTY_WORLD"):
        vm.execute("bridge.PrepareDemo();")
    assert len(attempts(vm)) == 3


def test_incompatible_native_cargo_relationship_aborts_before_builds():
    vm = world_vm()
    vm.execute("DemoCargoList.HasItem <- function(c){return false;};")
    with pytest.raises(Exception, match="NETWORK_CONTENT_MISMATCH"):
        vm.execute("bridge.PrepareDemo();")
    assert attempts(vm) == []
    assert len(vm.get_roottable()["world_industries"]) == 0


def first_native_ini_group(config, group_name):
    """15.3 IniFile::GetGroup selects the first matching group, without merging."""
    items = {}
    active = False
    for line in config.splitlines():
        line = line.strip()
        if line.startswith("["):
            if active:
                break
            active = line == f"[{group_name}]"
        elif active and "=" in line:
            key, value = line.split("=", 1)
            items[key.strip()] = value.strip()
    return items


def test_attempt11_frozen_config_replays_zero_mutation_guard_failure():
    historical = HISTORICAL.with_name("openttd-15.3-first-freight-delivery-attempt11")
    with zipfile.ZipFile(historical / "frozen-source.zip") as archive:
        config = archive.read("staged/openttd.cfg").decode()
        code = archive.read("staged/main.nut").decode()
    assert config.count("[economy]") == 2
    economy = first_native_ini_group(config, "economy")
    assert economy == {"timekeeping_units": "0"}
    vm = world_vm(multiple=economy.get("multiple_industry_per_town") == "true")
    vm.execute(code.replace('require("network-parent.nut");', ""))
    with pytest.raises(Exception, match="NETWORK_REQUIRES_MULTIPLE_INDUSTRY_PER_TOWN"):
        vm.execute("::bridge=NetworkFreightProof();bridge.PrepareDemo();")
    assert attempts(vm) == []
    assert len(vm.get_roottable()["world_industries"]) == 0


@pytest.mark.parametrize(
    "config_text,admitted",
    [
        ("[economy]\ntimekeeping_units = 0\nmultiple_industry_per_town = true\n", True),
        ("[economy]\nmultiple_industry_per_town = false\n", False),
        ("[economy]\ntimekeeping_units = 0\n", False),
        (
            "[economy]\nmultiple_industry_per_town = false\n"
            "[economy]\nmultiple_industry_per_town = true\n",
            False,
        ),
    ],
)
def test_native_effective_setting_is_validated_offline(tmp_path, config_text, admitted):
    from types import SimpleNamespace

    root = tmp_path / "world"
    root.mkdir()
    directory = tmp_path / "evidence"
    directory.mkdir()
    png = proof.flat_heightmap()
    (root / "heightmap.png").write_bytes(png)
    (directory / "heightmap.png").write_bytes(png)
    config = root / "openttd.cfg"
    config.write_text(config_text)
    prepared = SimpleNamespace(
        directory=directory,
        spec=SimpleNamespace(workspace=SimpleNamespace(root=root, config=config)),
    )
    metadata = {
        "source": {
            "kind": "NATIVE_FLAT_HEIGHTMAP",
            "input_sha256": proof.sha256(directory / "heightmap.png"),
        }
    }
    if admitted:
        proof.validate_network_world_inputs(prepared, metadata)
    else:
        with pytest.raises(ValueError):
            proof.validate_network_world_inputs(prepared, metadata)
