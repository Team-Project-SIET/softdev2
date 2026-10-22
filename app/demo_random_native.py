"""Opt-in 256x256 native package composition; fixed package bytes stay unchanged."""

import json

from app.demo_random import DemoBudgets, RandomWorldSettings


def random_budgets(value: dict, service_limit: int, base: dict) -> dict:
    budget = DemoBudgets.from_sealed(value)
    if service_limit != min(budget.max_services, budget.max_vehicles):
        raise ValueError("random service capacity differs from sealed budgets")
    return base | dict(
        requests=29 * service_limit,
        mutations=11 * service_limit,
        supplemental_requests=budget.supplemental_request_limit,
        total_seconds=300 + 300 * service_limit,
        world_preparation_mutations=0,
        construction_commands=64 * service_limit,
        selected_services=service_limit,
    )


def _method(source: bytes, name: bytes, replacement: bytes) -> bytes:
    start = source.index(b"    function " + name + b"(")
    opening = source.index(b"{", start)
    depth, end = 1, opening + 1
    while depth:
        if source[end : end + 1] == b"{":
            depth += 1
        elif source[end : end + 1] == b"}":
            depth -= 1
        end += 1
    return source[:start] + replacement + source[end:]


# Every staged seam is an exact byte pattern; an anchorless drift in the staged
# package ("364*" style collisions) must fail preparation, never reach the game.
_SEAM_COUNTS = {
    ("delivery.nut", b"/64"): 9,
    ("delivery.nut", b"%64"): 7,
    ("delivery.nut", b"*64"): 3,
    ("delivery.nut", b"64*"): 1,
    ("delivery.nut", b"x<64"): 1,
    ("delivery.nut", b"y<64"): 1,
    ("delivery.nut", b"x>=64"): 1,
    ("delivery.nut", b"y>=64"): 1,
    ("delivery.nut", b"?64:-64"): 0,
    ("delivery.nut", b"? 64 : -64"): 1,
    ("delivery.nut", b"q.arg>4095"): 0,
    ("delivery.nut", b"t<65||t>4030"): 1,
    ("delivery.nut", b"drequests>=87"): 1,
    ("delivery.nut", b"planner_requests>=1168"): 0,
    ("delivery.nut", b"services.len()>=3"): 0,
    ("delivery.nut", b"services.len()>3"): 0,
    ("network-parent.nut", b"/64"): 8,
    ("network-parent.nut", b"%64"): 2,
    ("network-parent.nut", b"*64"): 1,
    ("network-parent.nut", b"64*"): 0,
    ("network-parent.nut", b"x<64"): 1,
    ("network-parent.nut", b"y<64"): 1,
    ("network-parent.nut", b"x>=64"): 0,
    ("network-parent.nut", b"y>=64"): 0,
    ("network-parent.nut", b"?64:-64"): 2,
    ("network-parent.nut", b"? 64 : -64"): 0,
    ("network-parent.nut", b"q.arg>4095"): 1,
    ("network-parent.nut", b"t<65||t>4030"): 1,
    ("network-parent.nut", b"drequests>=87"): 0,
    ("network-parent.nut", b"planner_requests>=1168"): 1,
    ("network-parent.nut", b"services.len()>=3"): 0,
    ("network-parent.nut", b"services.len()>3"): 0,
    ("main.nut", b"/64"): 5,
    ("main.nut", b"%64"): 1,
    ("main.nut", b"*64"): 3,
    ("main.nut", b"64*"): 0,
    ("main.nut", b"x<64"): 0,
    ("main.nut", b"y<64"): 0,
    ("main.nut", b"x>=64"): 0,
    ("main.nut", b"y>=64"): 0,
    ("main.nut", b"?64:-64"): 0,
    ("main.nut", b"? 64 : -64"): 0,
    ("main.nut", b"q.arg>4095"): 0,
    ("main.nut", b"t<65||t>4030"): 0,
    ("main.nut", b"drequests>=87"): 1,
    ("main.nut", b"planner_requests>=1168"): 0,
    ("main.nut", b"services.len()>=3"): 1,
    ("main.nut", b"services.len()>3"): 1,
    ("vehicle.nut", b"/64"): 2,
    ("vehicle.nut", b"%64"): 0,
    ("vehicle.nut", b"*64"): 0,
    ("vehicle.nut", b"64*"): 0,
    ("vehicle.nut", b"x<64"): 0,
    ("vehicle.nut", b"y<64"): 0,
    ("vehicle.nut", b"x>=64"): 0,
    ("vehicle.nut", b"y>=64"): 0,
    ("vehicle.nut", b"?64:-64"): 0,
    ("vehicle.nut", b"? 64 : -64"): 0,
    ("vehicle.nut", b"q.arg>4095"): 0,
    ("vehicle.nut", b"t<65||t>4030"): 0,
    ("vehicle.nut", b"drequests>=87"): 0,
    ("vehicle.nut", b"planner_requests>=1168"): 0,
    ("vehicle.nut", b"services.len()>=3"): 0,
    ("vehicle.nut", b"services.len()>3"): 0,
    ("infrastructure.nut", b"/64"): 0,
    ("infrastructure.nut", b"%64"): 2,
    ("infrastructure.nut", b"*64"): 0,
    ("infrastructure.nut", b"64*"): 0,
    ("infrastructure.nut", b"x<64"): 0,
    ("infrastructure.nut", b"y<64"): 0,
    ("infrastructure.nut", b"x>=64"): 0,
    ("infrastructure.nut", b"y>=64"): 0,
    ("infrastructure.nut", b"?64:-64"): 0,
    ("infrastructure.nut", b"? 64 : -64"): 0,
    ("infrastructure.nut", b"q.arg>4095"): 0,
    ("infrastructure.nut", b"t<65||t>4030"): 0,
    ("infrastructure.nut", b"drequests>=87"): 0,
    ("infrastructure.nut", b"planner_requests>=1168"): 0,
    ("infrastructure.nut", b"services.len()>=3"): 0,
    ("infrastructure.nut", b"services.len()>3"): 0,
}


def _assert_seam_counts(name, value):
    for (file, pattern), expected in _SEAM_COUNTS.items():
        if file != name:
            continue
        actual = value.count(pattern)
        if actual != expected:
            raise ValueError(
                f"STAGING_SEAM_DRIFT: {name} seam "
                + pattern.decode()
                + f" matched {actual} times, expected {expected}"
            )


def stage_random(out: dict[str, bytes], budgets: dict) -> dict[str, bytes]:
    """Compose from the proven serial executor, changing only explicit profile seams."""
    budget = DemoBudgets.from_sealed(budgets)
    limit = min(budget.max_services, budget.max_vehicles)
    for seam_name in (
        "delivery.nut",
        "network-parent.nut",
        "main.nut",
        "vehicle.nut",
        "infrastructure.nut",
    ):
        _assert_seam_counts(seam_name, out[seam_name])
    main = _method(
        out["main.nut"],
        b"PrepareDemo",
        b"""    function PrepareDemo() {
        if(GSMap.GetMapSizeX()!=256||GSMap.GetMapSizeY()!=256)
            throw "RANDOM_MAP_DIMENSION_MISMATCH";
        GSLog.Info("FREIGHT_GAME_TIME_START date="+GSDate.GetCurrentDate()+" tick="+GetTick());
        GSLog.Info("FREIGHT_RANDOM_WORLD_READY industries="+GSIndustry.GetIndustryCount());
    }""",
    )
    main = main.replace(b"services.len()>=3", f"services.len()>={limit}".encode())
    main = main.replace(b"services.len()>3", f"services.len()>{limit}".encode())
    main = main.replace(b"drequests>=87", f"drequests>={29 * limit}".encode())
    out = dict(out, **{"main.nut": main})
    for name in (
        "delivery.nut",
        "network-parent.nut",
        "main.nut",
        "vehicle.nut",
        "infrastructure.nut",
    ):
        value = out[name]
        for a, b in (
            (b"/64", b"/256"),
            (b"%64", b"%256"),
            (b"*64", b"*256"),
            (b"64*", b"256*"),
            (b"x<64", b"x<256"),
            (b"y<64", b"y<256"),
            (b"x>=64", b"x>=256"),
            (b"y>=64", b"y>=256"),
            (b"?64:-64", b"?256:-256"),
            (b"? 64 : -64", b"? 256 : -256"),
            (b"q.arg>4095", b"q.arg>65535"),
        ):
            value = value.replace(a, b)
        value = value.replace(
            b"t<65||t>4030",
            b"GSMap.GetTileX(t)<1||GSMap.GetTileY(t)<1||"
            b"GSMap.GetTileX(t)>254||GSMap.GetTileY(t)>254",
        )
        value = value.replace(b"drequests>=87", f"drequests>={29 * limit}".encode())
        value = value.replace(
            b"planner_requests>=1168",
            f"planner_requests>={budget.supplemental_request_limit}".encode(),
        )
        out[name] = value
    out["network-parent.nut"] = out["network-parent.nut"].replace(
        b'else if(q.kind=="engines")',
        b"""else if(q.kind=="generation") {
            foreach(name in ["difficulty.terrain_type","difficulty.number_towns",
                             "difficulty.industry_density"])
                if(!GSGameSettings.IsValid(name))throw "RANDOM_GENERATION_SETTING_UNAVAILABLE";
            data=[GSGame.GetLandscape(),
                GSGameSettings.GetValue("difficulty.terrain_type"),
                GSGameSettings.GetValue("difficulty.number_towns"),
                GSGameSettings.GetValue("difficulty.industry_density"),
                GSMap.GetMapSizeX(),GSMap.GetMapSizeY()];
        } else if(q.kind=="engines")""",
    )
    return out


def expected_world(metadata: dict) -> tuple:
    world = metadata.get("world", dict(seed=42, width=64, height=64))
    return "15.3", world["seed"], world["width"], world["height"]


def validate_generation_config(metadata: dict, text: str):
    import configparser

    settings = RandomWorldSettings.model_validate_json(json.dumps(metadata["random_world"]))
    if metadata.get("random_profile_version") != 1 or metadata["source"] != dict(
        kind="NATIVE_RANDOM_WORLD", settings=settings.model_dump()
    ):
        raise ValueError("random generation profile/source mismatch")
    expected = configparser.ConfigParser(interpolation=None)
    expected.read_string(settings.config())
    actual = configparser.ConfigParser(interpolation=None)
    actual.read_string(text)
    for section in expected.sections():
        for name, value in expected[section].items():
            if actual.get(section, name, fallback=None) != value:
                raise ValueError(f"random generation setting mismatch: {section}.{name}")
    if expected_world(metadata) != ("15.3", settings.seed, 256, 256):
        raise ValueError("random requested world identity mismatch")


def generation_argv(argv: tuple, seed: int) -> tuple:
    index = argv.index("-g")
    return argv[:index] + ("-G", str(seed), "-g") + argv[index + 2 :]


def generation_observation(metadata: dict, runtime: dict, readback) -> dict:
    settings = RandomWorldSettings.model_validate_json(json.dumps(metadata["random_world"]))
    expected = (
        dict(temperate=0, arctic=1, tropic=2, toyland=3)[settings.climate],
        settings.terrain,
        settings.towns,
        settings.industries,
        256,
        256,
    )
    if readback.data != expected or expected_world(metadata) != (
        runtime["welcome"]["revision"],
        runtime["welcome"]["seed"],
        runtime["welcome"]["width"],
        runtime["welcome"]["height"],
    ):
        raise ValueError("actual random generation settings/world identity mismatch")
    return dict(
        schema="random-generation-observation-v1",
        classification="OBSERVED",
        actual_settings=dict(settings.model_dump()),
        actual_world_identity=runtime["welcome"],
        readback_digest=__import__("hashlib")
        .sha256(readback.model_dump_json().encode())
        .hexdigest(),
    )
