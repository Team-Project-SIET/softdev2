/* Pinned OpenTTD 13.4 GameScript queries only. No gameplay commands. */
require("request.nut");

class P08Preparation extends GSController {
    sequence = 0;
    sum_a = 1;
    sum_b = 0;
    emitted_bytes = 0;
    completed = false;

    function Json(value) {
        local kind = typeof value;
        if (value == null) return "null";
        if (kind == "bool") return value ? "true" : "false";
        if (kind == "integer") return value.tostring();
        if (kind == "string") {
            local result = "\"";
            for (local i = 0; i < value.len(); i++) {
                local ch = value[i];
                if (ch == 34) result += "\\\"";
                else if (ch == 92) result += "\\\\";
                else if (ch < 32) result += format("\\u%04x", ch);
                else result += value.slice(i, i + 1);
            }
            return result + "\"";
        }
        if (kind == "array") {
            local result = "[";
            foreach (i, item in value) result += (i == 0 ? "" : ",") + this.Json(item);
            return result + "]";
        }
        if (kind == "table") {
            local keys = [];
            foreach (key, item in value) keys.append(key);
            keys.sort();
            local result = "{";
            foreach (i, key in keys) result += (i == 0 ? "" : ",") + this.Json(key) + ":" + this.Json(value[key]);
            return result + "}";
        }
        throw "unsupported extraction JSON type";
    }

    function Emit(kind, body) {
        if (this.completed) throw "extraction already complete";
        local line = "P08|" + this.sequence + "|" + kind + "|" + this.Json(body);
        if (line.len() > 8192 || this.emitted_bytes + line.len() + 1 > (kind == "failure" ? 67108864 : 67100672)) this.Reject("CANDIDATE_LIMIT_EXCEEDED", "extraction evidence/count exceeds profile bound");
        this.emitted_bytes += line.len() + 1;
        if (kind != "done" && kind != "failure") {
            local bytes = line + "\n";
            for (local i = 0; i < bytes.len(); i++) {
                this.sum_a = (this.sum_a + bytes[i]) % 65521;
                this.sum_b = (this.sum_b + this.sum_a) % 65521;
            }
        }
        GSLog.Info(line);
        this.sequence++;
        if (kind == "done" || kind == "failure") this.completed = true;
    }

    function ListIds(list) {
        local result = [];
        for (local id = list.Begin(); !list.IsEnd(); id = list.Next()) result.append(id);
        result.sort();
        return result;
    }

    function Extract() {
        if (this.completed) return;
        if (!GSGame.IsPaused() || GSGame.GetLandscape() != GSGame.LT_TEMPERATE || GSGame.IsMultiplayer()) this.Reject("UNSUPPORTED_WORLD", "unpaused, multiplayer or non-temperate preparation world");
        if (GSGameSettings.GetValue("station.modified_catchment") != 1) this.Reject("UNSUPPORTED_WORLD", "modified truck-stop catchment is required");
        local company = P08_REQUEST.company_id;
        if (GSCompany.ResolveCompanyID(company) != company) this.Reject("UNSUPPORTED_WORLD", "query company unavailable");
        for (local i = 0; i < 15; i++) {
            if (i != company && GSCompany.ResolveCompanyID(i) == i) this.Reject("UNSUPPORTED_WORLD", "competing active company");
        }
        local date = GSDate.GetCurrentDate();
        local cargos = this.ListIds(GSCargoList());
        local industries = this.ListIds(GSIndustryList());
        local engines;
        {
            local context = GSCompanyMode(company);
            engines = this.ListIds(GSEngineList(GSVehicle.VT_ROAD));
        }
        local size = GSMap.GetMapSize();
        if (size > P08_REQUEST.limits.map_tiles || industries.len() > P08_REQUEST.limits.industries || cargos.len() > 32 || engines.len() > 256) this.Reject("CANDIDATE_LIMIT_EXCEEDED", "extraction evidence/count exceeds profile bound");
        local counts = {tile = size, industry = industries.len(), cargo = cargos.len(), engine = engines.len(), cost = 1};
        local meta = {
            schema_version = 1, profile = P08_REQUEST.profile,
            width_tiles = GSMap.GetMapSizeX(), height_tiles = GSMap.GetMapSizeY(),
            seed = P08_REQUEST.seed, preparation_date = format("%04d-%02d-%02d", GSDate.GetYear(date), GSDate.GetMonth(date), GSDate.GetDayOfMonth(date)),
            company_id = company, source_save_digest = P08_REQUEST.source_save_digest,
            policy_version = "p08-v1", counts = counts
        };
        this.Emit("meta", meta);
        foreach (cargo in cargos) this.Emit("cargo", {
            cargo_id = cargo, label = GSCargo.GetCargoLabel(cargo), name = GSCargo.GetName(cargo), freight = GSCargo.IsFreight(cargo)
        });
        local footprints = {};
        foreach (industry in industries) footprints[industry] <- [];
        local neighborhood = {};
        // Footprints are extracted independently of native anchor assumptions.
        for (local tile = 0; tile < size; tile++) {
            if (!GSMap.IsValidTile(tile)) continue;
            local industry = GSIndustry.GetIndustryID(tile);
            if (GSIndustry.IsValidIndustry(industry)) {
                if (!(industry in footprints)) this.Reject("CATALOG_IDENTITY_MISMATCH", "industry catalog changed");
                footprints[industry].append(tile);
                local x = GSMap.GetTileX(tile), y = GSMap.GetTileY(tile);
                for (local dy = -3; dy <= 3; dy++) for (local dx = -3; dx <= 3; dx++) {
                    local nx = x + dx, ny = y + dy;
                    if (nx >= 0 && ny >= 0 && nx < meta.width_tiles && ny < meta.height_tiles) neighborhood[ny * meta.width_tiles + nx] <- true;
                }
            }
        }
        foreach (industry in industries) {
            local facts = [];
            foreach (cargo in cargos) facts.append({cargo_id = cargo,
                last_month_production = GSIndustry.GetLastMonthProduction(industry, cargo),
                accepts = GSIndustry.IsCargoAccepted(industry, cargo) == GSIndustry.CAS_ACCEPTED});
            this.Emit("industry", {industry_id = industry, name = GSIndustry.GetName(industry),
                anchor_tile = GSIndustry.GetLocation(industry), footprint = footprints[industry], cargos = facts});
        }
        for (local tile = 0; tile < size; tile++) {
            local facts = [];
            local valid = GSMap.IsValidTile(tile);
            local industry = valid ? GSIndustry.GetIndustryID(tile) : -1;
            local native_industry = GSIndustry.IsValidIndustry(industry);
            local tree = valid && GSTile.HasTreeOnTile(tile);
            local clearing = valid && (tree || GSTile.IsFarmTile(tile) || GSTile.IsRockTile(tile) || GSTile.IsRoughTile(tile));
            local water = valid && GSTile.IsWaterTile(tile);
            local coast = valid && GSTile.IsCoastTile(tile);
            local transport = false;
            if (valid) foreach (type in [GSTile.TRANSPORT_ROAD, GSTile.TRANSPORT_RAIL, GSTile.TRANSPORT_WATER, GSTile.TRANSPORT_AIR]) {
                if (GSTile.HasTransportType(tile, type)) transport = true;
            }
            local buildable = valid && GSTile.IsBuildable(tile);
            if (valid && tile in neighborhood) foreach (cargo in cargos) facts.append({cargo_id = cargo,
                production = GSTile.GetCargoProduction(tile, cargo, 1, 1, 3),
                acceptance_eighths = GSTile.GetCargoAcceptance(tile, cargo, 1, 1, 3)});
            this.Emit("tile", {tile_index = tile, x = tile % meta.width_tiles, y = tile / meta.width_tiles,
                height = valid ? GSTile.GetMinHeight(tile) : 0, slope = valid ? GSTile.GetSlope(tile) : 65535,
                land_class = water ? "water" : coast ? "coast" : "land",
                occupancy = native_industry ? "industry" : tree ? "trees" : buildable ? "vacant" : "other",
                transport_occupied = transport, industry_id = native_industry ? industry : null,
                build_eligible = buildable, clearing_required = clearing, cargo_facts = facts});
        }
        {
            // Only company-relative engine availability/catalog queries need this context.
            local context = GSCompanyMode(company);
            foreach (engine in engines) {
                local cargo = GSEngine.GetCargoType(engine);
                this.Emit("engine", {engine_id = engine, name = GSEngine.GetName(engine),
                    default_cargo_id = cargo, freight = GSCargo.IsFreight(cargo),
                    road_type = GSEngine.GetRoadType(engine), depot_class = "road",
                    immediately_buildable = GSEngine.IsBuildable(engine), articulated = GSEngine.IsArticulated(engine),
                    refit_required = false, default_capacity = GSEngine.GetCapacity(engine),
                    purchase_cost_gbp = GSEngine.GetPrice(engine).tostring(),
                    running_cost_gbp_per_year = GSEngine.GetRunningCost(engine).tostring(),
                    native_speed_units = GSEngine.GetMaxSpeed(engine)});
            }
        }
        this.Emit("cost", {road_build_cost_gbp = (2 * GSRoad.GetBuildCost(0, GSRoad.BT_ROAD)).tostring(),
            station_build_cost_gbp = GSRoad.GetBuildCost(0, GSRoad.BT_TRUCK_STOP).tostring(),
            depot_build_cost_gbp = GSRoad.GetBuildCost(0, GSRoad.BT_DEPOT).tostring()});
        if (!GSGame.IsPaused() || GSDate.GetCurrentDate() != date) this.Reject("WORLD_CHANGED_DURING_PREPARATION", "pause/date changed during extraction");
        this.Emit("done", {counts = counts, adler32 = format("%04x%04x", this.sum_b, this.sum_a)});
    }

    function Reject(code, message) { throw {code = code, message = message}; }

    function Save() { return {completed = this.completed}; }
    function Load(version, data) {
        if (typeof data == "table" && "completed" in data && data.completed) this.completed = true;
    }

    function Start() {
        try { this.Extract(); }
        catch (error) {
            local code = "EXTRACTION_INCOMPLETE", message = "native read-only query failed";
            if (typeof error == "table" && "code" in error && "message" in error) {
                code = error.code; message = error.message;
            }
            this.Emit("failure", {code = code, message = message, adler32 = format("%04x%04x", this.sum_b, this.sum_a)});
        }
        while (true) this.Sleep(1000); // Inert after terminal marker.
    }
}
