/* Query-only fake. Signatures pinned independently in p08_api_13_4.json. */
::logs <- [];
::query_count <- 0;
::company_contexts <- 0;
function require(path) { if (path != "request.nut") throw "unexpected package import"; }
class GSController { function Sleep(ticks) { throw "CONTROLLED_STOP"; } }
class GSLog { static function Info(line) { logs.append(line); } }
class GSGame {
    static LT_TEMPERATE = 0;
    static function IsPaused() { return true; }
    static function IsMultiplayer() { return false; }
    static function GetLandscape() { return 0; }
}
class GSCompany {
    static function ResolveCompanyID(id) { return id == 0 ? 0 : -1; }
}
class GSCompanyMode { constructor(company) { if (company != 0) throw "wrong company"; ::company_contexts++; } }
class GSDate {
    static function GetCurrentDate() { return 0; }
    static function GetYear(date) { return 1950; }
    static function GetMonth(date) { return 1; }
    static function GetDayOfMonth(date) { return 1; }
}
class QueryList {
    ids = null; pos = 0;
    constructor(values) { this.ids = values; }
    function Begin() { this.pos = 0; return this.ids.len() > 0 ? this.ids[0] : -1; }
    function IsEnd() { return this.pos >= this.ids.len(); }
    function Next() { this.pos++; return this.IsEnd() ? -1 : this.ids[this.pos]; }
}
class GSCargoList extends QueryList { constructor() { base.constructor([0]); } }
class GSIndustryList extends QueryList { constructor() { base.constructor([1, 2]); } }
class GSVehicle { static VT_ROAD = 1; }
class GSEngineList extends QueryList {
    constructor(mode) { if (mode != GSVehicle.VT_ROAD || company_contexts == 0) throw "engine context"; base.constructor([7]); }
}
class GSMap {
    static function GetMapSize() { return 96; }
    static function GetMapSizeX() { return 12; }
    static function GetMapSizeY() { return 8; }
    static function IsValidTile(tile) { return tile >= 0 && tile < 96; }
    static function GetTileX(tile) { return tile % 12; }
    static function GetTileY(tile) { return tile / 12; }
}
class GSCargo {
    static function GetCargoLabel(cargo) { ::query_count++; return "COAL"; }
    static function GetName(cargo) { return "Coal"; }
    static function IsFreight(cargo) { return true; }
}
class GSIndustry {
    static CAS_ACCEPTED = 1;
    static function IsValidIndustry(id) { return id == 1 || id == 2; }
    static function GetIndustryID(tile) { local id = WORLD.tiles[tile].industry_id; return id == null ? 65535 : id; }
    static function GetName(id) { return WORLD.industries[id-1].name; }
    static function GetLocation(id) { return WORLD.industries[id-1].anchor_tile; }
    static function GetLastMonthProduction(id, cargo) { return WORLD.industries[id-1].cargos[0].last_month_production; }
    static function IsCargoAccepted(id, cargo) { return WORLD.industries[id-1].cargos[0].accepts ? 1 : 0; }
}
class GSTile {
    static TRANSPORT_ROAD = 0;
    static TRANSPORT_RAIL = 1;
    static TRANSPORT_WATER = 2;
    static TRANSPORT_AIR = 3;
    static function HasTreeOnTile(tile) { return WORLD.tiles[tile].occupancy == "trees"; }
    static function IsFarmTile(tile) { return WORLD.tiles[tile].clearing_required; }
    static function IsRockTile(tile) { return false; }
    static function IsRoughTile(tile) { return false; }
    static function IsWaterTile(tile) { return WORLD.tiles[tile].land_class == "water"; }
    static function IsCoastTile(tile) { return WORLD.tiles[tile].land_class == "coast"; }
    static function HasTransportType(tile, type) { return WORLD.tiles[tile].transport_occupied; }
    static function IsBuildable(tile) { return WORLD.tiles[tile].build_eligible; }
    static function GetMinHeight(tile) { return WORLD.tiles[tile].height; }
    static function GetSlope(tile) { return WORLD.tiles[tile].slope; }
    static function GetCargoProduction(tile, cargo, width, height, radius) {
        if (width != 1 || height != 1 || radius != 3) throw "wrong station coverage";
        local facts = WORLD.tiles[tile].cargo_facts; return facts.len() ? facts[0].production : 0;
    }
    static function GetCargoAcceptance(tile, cargo, width, height, radius) {
        if (width != 1 || height != 1 || radius != 3) throw "wrong station coverage";
        local facts = WORLD.tiles[tile].cargo_facts; return facts.len() ? facts[0].acceptance_eighths : 0;
    }
}
class GSEngine {
    static function GetCargoType(engine) { return 0; }
    static function GetName(engine) { return "Coal truck"; }
    static function GetRoadType(engine) { return 0; }
    static function IsBuildable(engine) { if (company_contexts == 0) throw "missing company context"; return true; }
    static function IsArticulated(engine) { return false; }
    static function GetCapacity(engine) { return 20; }
    static function GetPrice(engine) { return 100; }
    static function GetRunningCost(engine) { return 365; }
    static function GetMaxSpeed(engine) { return 40; }
}
class GSRoad {
    static BT_ROAD = 0;
    static BT_TRUCK_STOP = 1;
    static BT_DEPOT = 2;
    static function GetBuildCost(road, type) { if (road != 0) throw "unsupported road"; return type == 0 ? 1 : type == 1 ? 10 : 15; }
}

class GSGameSettings { static function GetValue(setting) { if (setting != "station.modified_catchment") throw "unsupported setting"; return 1; } }
