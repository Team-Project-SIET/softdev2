require("plan.nut");

class P03Executor extends AIController {
    _terminal_emitted = false;

    function _stage(name, hash) {
        AILog.Info("P03_EXECUTOR_AI|P03_STAGE_V1|" + name + "|" + hash);
    }

    function _ids(items) {
        local value = "";
        foreach (item in items) {
            if (value != "") value += ",";
            value += item;
        }
        return value;
    }

    function _emit(status, code, plan) {
        if (this._terminal_emitted) return;
        local routes = status == "accepted" ? _ids(plan.route_ids) : "";
        local fleet = status == "accepted" ? _ids(plan.fleet_group_ids) : "";
        local actions = status == "accepted" ? _ids(plan.infrastructure_action_ids) : "";
        local record = "P03_EXECUTOR_AI|P03_SETUP_V1|1|1|" + status + "|" + code + "|" +
            plan.plan_hash + "|" + plan.world_fingerprint + "|" +
            plan.world_source_digest + "|" +
            plan.scenario_id + "|" + plan.scenario_version + "|" +
            routes + "|" + fleet + "|" + actions;
        AILog.Info(record);
        this._terminal_emitted = true;
    }

    function _world_failure(data, reason, site, actual) {
        local location_id = site == null ? "none" : site.location_id;
        local kind = site == null || site.world_kind == null ? "none" : site.world_kind;
        local expected_id = site == null || site.world_id == null ? "none" : site.world_id.tostring();
        local expected_x = site == null ? "none" : site.x.tostring();
        local expected_y = site == null ? "none" : site.y.tostring();
        AILog.Info("P03_EXECUTOR_AI|P03_WORLD_RESOLUTION_V1|" + data.plan_hash + "|" +
            reason + "|" + location_id + "|" + kind + "|" + expected_id + "|" +
            expected_x + "|" + expected_y + "|" + actual);
        _emit("failed", "WORLD_RESOLUTION_FAILURE", data);
    }

    function _industry_id_from_runtime(expected_id) {
        local industries = AIIndustryList();
        industries.Sort(AIList.SORT_BY_ITEM, AIList.SORT_ASCENDING);
        for (local industry_id = industries.Begin(); !industries.IsEnd();
                industry_id = industries.Next()) {
            if (industry_id == expected_id) return industry_id;
        }
        return -1;
    }

    function Start() {
        _stage("START_ENTERED", "none");
        local data = null;
        try {
            data = ::P03_TRANSPORT;
            _stage("PLAN_FOUND", data.plan_hash);
            _validate_and_acknowledge(data);
        } catch (error) {
            if (data != null) {
                _emit("failed", "EXECUTOR_SETUP_FAILURE", data);
            } else {
                AILog.Error("P03_EXECUTOR_AI|P03_FATAL_V1|EXECUTOR_SETUP_FAILURE|PLAN_NOT_FOUND");
            }
        }
    }

    function _validate_and_acknowledge(data) {
        if (data.transport_version != 1 || data.schema_version != 1) {
            _emit("failed", "EXECUTOR_SETUP_FAILURE", data);
            return;
        }
        if (data.plan_hash.len() != 64 || data.plan_hash != data.artifact.plan_hash ||
            data.artifact.plan.world_fingerprint != data.world_fingerprint ||
            data.artifact.plan.scenario_id != data.scenario_id ||
            data.artifact.plan.scenario_version != data.scenario_version) {
            _emit("failed", "EXECUTOR_SETUP_FAILURE", data);
            return;
        }
        _stage("PLAN_DECODED", data.plan_hash);
        _stage("WORLD_VALIDATION_STARTED", data.plan_hash);
        local observed_width = AIMap.GetMapSizeX();
        local observed_height = AIMap.GetMapSizeY();
        if (observed_width != data.world_width || observed_height != data.world_height) {
            _world_failure(data, "MAP_DIMENSIONS_MISMATCH", null,
                observed_width.tostring() + "," + observed_height.tostring());
            return;
        }
        if (!AIGameSettings.IsValid("game_creation.generation_seed")) {
            _world_failure(data, "SEED_SETTING_UNAVAILABLE", null,
                "game_creation.generation_seed");
            return;
        }
        local observed_seed = AIGameSettings.GetValue("game_creation.generation_seed");
        if (observed_seed != data.world_seed) {
            _world_failure(data, "SEED_MISMATCH", null, observed_seed.tostring());
            return;
        }
        local observed_objects = {};
        local runtime_objects = [];
        foreach (site in data.sites) {
            local tile = AIMap.GetTileIndex(site.x, site.y);
            if (!AIMap.IsValidTile(tile)) {
                _world_failure(data, "TILE_INVALID", site, tile.tostring());
                return;
            }
            // Unbuilt candidates assert a valid tile, not an existing facility.
            if (site.world_kind == null && site.world_id == null) {
                continue;
            }
            local observed_location = tile;
            local observed_id = -1;
            local observed_kind = "";
            if (site.world_kind == "industry") {
                if (!AIIndustry.IsValidIndustry(site.world_id)) {
                    _world_failure(data, "INDUSTRY_INVALID", site, "false");
                    return;
                }
                observed_id = _industry_id_from_runtime(site.world_id);
                if (observed_id < 0) {
                    _world_failure(data, "INDUSTRY_NOT_LISTED", site, observed_id.tostring());
                    return;
                }
                observed_location = AIIndustry.GetLocation(observed_id);
                observed_kind = "industry";
            } else if (site.world_kind == "station") {
                if (!AIStation.IsValidStation(site.world_id)) {
                    _world_failure(data, "STATION_INVALID", site, "false");
                    return;
                }
                observed_location = AIStation.GetLocation(site.world_id);
                observed_id = AIStation.GetStationID(observed_location);
                observed_kind = "station";
            } else {
                _world_failure(data, "WORLD_KIND_UNSUPPORTED", site, site.world_kind);
                return;
            }
            if (observed_location != tile) {
                _world_failure(data, observed_kind == "industry" ?
                    "INDUSTRY_LOCATION_MISMATCH" : "STATION_LOCATION_MISMATCH", site,
                    observed_location.tostring());
                return;
            }
            if (observed_id != site.world_id) {
                _world_failure(data, observed_kind == "industry" ?
                    "INDUSTRY_ID_MISMATCH" : "STATION_ID_MISMATCH", site,
                    observed_id.tostring());
                return;
            }
            // Validate every planner reference before suppressing duplicate objects.
            local object_key = observed_kind + ":" + observed_id.tostring();
            if (!(object_key in observed_objects)) {
                observed_objects[object_key] <- true;
                runtime_objects.append({
                    kind = observed_kind,
                    object_id = observed_id,
                    x = AIMap.GetTileX(observed_location),
                    y = AIMap.GetTileY(observed_location)
                });
            }
        }
        // Match Python's canonical (kind, object_id) order, including numeric IDs.
        runtime_objects.sort(function(a, b) {
            if (a.kind != b.kind) return a.kind < b.kind ? -1 : 1;
            if (a.object_id == b.object_id) return 0;
            return a.object_id < b.object_id ? -1 : 1;
        });
        local observed_sites = "";
        foreach (object in runtime_objects) {
            if (observed_sites != "") observed_sites += ",";
            observed_sites += object.kind + ":" + object.object_id.tostring() + ":" +
                object.x.tostring() + ":" + object.y.tostring();
        }
        AILog.Info("P03_EXECUTOR_AI|P03_RUNTIME_WORLD_V1|" + data.plan_hash + "|" +
            observed_width.tostring() + "|" + observed_height.tostring() + "|" +
            observed_seed.tostring() + "|" + observed_sites);
        _stage("WORLD_VALIDATION_SUCCEEDED", data.plan_hash);
        if (data.route_ids.len() != data.artifact.plan.routes.len() ||
            data.fleet_group_ids.len() != data.artifact.plan.fleet.groups.len() ||
            data.infrastructure_action_ids.len() != data.artifact.plan.infrastructure.actions.len()) {
            _emit("failed", "EXECUTOR_SETUP_FAILURE", data);
            return;
        }
        foreach (index, route in data.artifact.plan.routes) {
            if (route.route_id != data.route_ids[index] ||
                (route.mode != "road" && route.mode != "rail")) {
                _emit("failed", "EXECUTOR_SETUP_FAILURE", data);
                return;
            }
        }
        foreach (index, group in data.artifact.plan.fleet.groups) {
            if (group.fleet_group_id != data.fleet_group_ids[index]) {
                _emit("failed", "INVALID_FLEET", data);
                return;
            }
        }
        foreach (index, action in data.artifact.plan.infrastructure.actions) {
            if (action.construction_id != data.infrastructure_action_ids[index]) {
                _emit("failed", "EXECUTOR_SETUP_FAILURE", data);
                return;
            }
        }
        _emit("accepted", "NONE", data);
        while (true) Sleep(1000);
    }
}
