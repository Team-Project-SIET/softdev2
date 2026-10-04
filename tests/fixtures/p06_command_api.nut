// Controlled OpenTTD 13.4-shaped API. No process, terrain generation or pathfinder.
::logs <- []; ::calls <- []; ::facilities <- {}; ::tracks <- {}; ::roads <- {};
::vehicles <- {}; ::next_station <- 100; ::next_vehicle <- 200;
::command_counts <- {};
function command(name, args) {
    local s = name;
    foreach (a in args) s += "|" + a;
    calls.append(s);
    if (!(name in command_counts)) command_counts[name] <- 0;
    command_counts[name]++;
    return !(name == fail_command && command_counts[name] == fail_number);
}
class AIController { function Sleep(n) { throw "CONTROLLED_STOP"; } }
class AILog { static function Info(s) { logs.append("dbg: [script] [0] [I] " + s); } static function Error(s) { logs.append(s); } }
class AIMap {
    static function GetTileIndex(x,y) { return x + 64*y; }
    static function GetTileX(t) { return t % 64; }
    static function GetTileY(t) { return t / 64; }
    static function IsValidTile(t) { return t >= 0 && t < 4096; }
    static function GetMapSizeX() { return 64; } static function GetMapSizeY() { return 64; }
}
class AIGameSettings { static function IsValid(s) { return true; } static function GetValue(s) { return 17; } }
class AIIndustryList {
    i=0; function Sort(a,b) {} function Begin() { i=0; return 1; }
    function IsEnd() { return i>=2; } function Next() { i++; return i+1; }
}
class AIList { static SORT_BY_ITEM=0; static SORT_ASCENDING=0; }
class AIIndustry { static function IsValidIndustry(id) { return id==1 || id==2; } static function GetLocation(id) { return "world_location_override" in getroottable()?::world_location_override:(id==1 ? 260 : 276); } }
class AIStation {
    static STATION_NEW = -1;
    static function GetStationID(t) { return t in facilities ? facilities[t].id : -1; }
    static function IsValidStation(id) { foreach (t,f in facilities) if(f.id==id && f.kind=="station") return true; return false; }
    static function GetLocation(id) { foreach(t,f in facilities) if(f.id==id) return t; return -1; }
}
function station(tile, mode, width, height, front, axis) {
    local id=::next_station++;
    for(local y=0;y<height;y++) for(local x=0;x<width;x++) {
        local t=tile+x+64*y;
        facilities[t] <- {id=id,kind="station",mode=mode,front=front};
        if(mode=="rail") tracks[t] <- axis;
    }
}
class AIRoad {
    static ROADVEHTYPE_TRUCK=1; static ROADVEHTYPE_BUS=0;
    static function GetRoadVehicleTypeForCargo(c) { return ROADVEHTYPE_TRUCK; }
    static function SetCurrentRoadType(t) {} static function IsRoadTypeAvailable(t) { return t==0; }
    static function BuildRoadStation(t,f,k,s) { if(!command("road_station",[t,f,k,s])) return false; station(t,"road",1,1,f,0); return true; }
    static function BuildRoadDepot(t,f) { if(!command("road_depot",[t,f])) return false; facilities[t] <- {id=t,kind="depot",mode="road",front=f}; return true; }
    static function BuildRoad(a,b) { if(!command("road_segment",[a,b])) return false; roads[a+":"+b] <- true; roads[b+":"+a] <- true; return true; }
    static function AreRoadTilesConnected(a,b) { return (a+":"+b) in roads; }
    static function IsRoadStationTile(t) { return t in facilities && facilities[t].kind=="station" && facilities[t].mode=="road"; }
    static function IsRoadDepotTile(t) { return t in facilities && facilities[t].kind=="depot" && facilities[t].mode=="road"; }
    static function GetRoadStationFrontTile(t) { return facilities[t].front; }
    static function GetRoadDepotFrontTile(t) { return facilities[t].front; }
}
class AIRail {
    static RAILTRACK_NE_SW=1; static RAILTRACK_NW_SE=2;
    static function SetCurrentRailType(t) {} static function IsRailTypeAvailable(t) { return t==0; }
    static function GetName(t) { return "Rail"; }
    static function BuildRailStation(t,axis,n,len,s) { if(!command("rail_station",[t,axis,n,len,s])) return false; station(t,"rail",axis==1?len:n,axis==1?n:len,-1,axis); return true; }
    static function BuildRailDepot(t,f) { if(!command("rail_depot",[t,f])) return false; facilities[t] <- {id=t,kind="depot",mode="rail",front=f}; return true; }
    static function BuildRailTrack(t,axis) { if(!command("rail_segment",[t,axis])) return false; tracks[t] <- axis; return true; }
    static function IsRailStationTile(t) { return t in facilities && facilities[t].kind=="station" && facilities[t].mode=="rail"; }
    static function IsRailDepotTile(t) { return t in facilities && facilities[t].kind=="depot" && facilities[t].mode=="rail"; }
    static function IsRailTile(t) { return t in tracks; }
    static function GetRailTracks(t) { return t in tracks ? tracks[t] : 0; }
    static function GetRailType(t) { return 0; }
    static function GetRailDepotFrontTile(t) { return facilities[t].front; }
}
class AICargo { static function IsValidCargo(c) { return c==0; } static function GetCargoLabel(c) { return "COAL"; } }
class AIEngine {
    static function IsBuildable(e) { return e in engine_catalog; }
    static function GetName(e) { return engine_catalog[e].name; }
    static function GetVehicleType(e) { return engine_catalog[e].mode=="road"?1:0; }
    static function IsWagon(e) { return engine_catalog[e].wagon; }
    static function CanPullCargo(e,c) { return c==0; }
    static function CanRefitCargo(e,c) { return c==0; }
    static function CanRunOnRail(e,t) { return t==0; }
    static function HasPowerOnRail(e,t) { return t==0; }
    static function CanRunOnRoad(e,t) { return t==0; }
    static function IsArticulated(e) { return false; }
}
class AIVehicle {
    static VT_ROAD=1; static VT_RAIL=0;
    static function BuildVehicle(t,e) { return build(t,e,-1); }
    static function BuildVehicleWithRefit(t,e,c) { return build(t,e,c); }
    static function build(t,e,c) {
        if(!command("purchase",[t,e,c])) return -1;
        local id=::next_vehicle++;
        vehicles[id] <- {engines=[e],parts=[id],orders=[],stopped=true}; return id;
    }
    static function IsValidVehicle(v) { return v in vehicles; }
    static function GetGroupID(v) { calls.append("group_readback|"+v+"|"+vehicles[v].group); return vehicles[v].group; }
    static function GetEngineType(v) { return vehicles[v].engines[0]; }
    static function GetNumWagons(v) { return vehicles[v].engines.len(); }
    static function GetWagonEngineType(v,i) { return vehicles[v].engines[i]; }
    static function MoveWagon(v,i,t,j) { if(!command("attach",[v,i,t,j])) return false; vehicles[t].engines.append(vehicles[v].engines[0]); vehicles[t].parts.append(v); return true; }
    static function GetCapacity(v,c) { local n=0; foreach(e in vehicles[v].engines) n+=engine_catalog[e].capacity; return n; }
    static function GetLength(v) { local n=0; foreach(e in vehicles[v].engines) n+=engine_catalog[e].length*16; return n; }
    static function IsStoppedInDepot(v) { return vehicles[v].stopped; }
    static function StartStopVehicle(v) { if(!command("activate",[v])) return false; vehicles[v].stopped=false; return true; }
}
class AIOrder {
    static OF_NONE=0; static OF_NO_UNLOAD=16; static OF_UNLOAD=4; static OF_NO_LOAD=128;
    static function AppendOrder(v,t,f) { if(!command("order",[v,t,f])) return false; vehicles[v].orders.append({tile=t,flags=f}); return true; }
    static function GetOrderCount(v) { return vehicles[v].orders.len(); }
    static function GetOrderDestination(v,i) { return vehicles[v].orders[i].tile; }
    static function GetOrderFlags(v,i) { return vehicles[v].orders[i].flags; }
    static function IsGotoStationOrder(v,i) { return facilities[vehicles[v].orders[i].tile].kind=="station"; }
    static function IsGotoDepotOrder(v,i) { return facilities[vehicles[v].orders[i].tile].kind=="depot"; }
}
class AIError { static function GetLastError() { return 42; } }
function require(s) {} // Plan module is injected into this controlled VM.

::native_groups <- {}; ::next_group <- 300;
class AIGroup {
    static GROUP_INVALID=-1;
    static function CreateGroup(mode,parent) { if(!command("group_create",[mode,parent])) return -1; local id=::next_group++; native_groups[id] <- {mode=mode,protected=false}; return id; }
    static function IsValidGroup(id) { return id in native_groups; }
    static function EnableAutoReplaceProtection(id,enabled) { if(!command("group_protect",[id,enabled])) return false; native_groups[id].protected=enabled; return true; }
    static function GetVehicleType(id) { return native_groups[id].mode; }
    static function GetAutoReplaceProtection(id) { return native_groups[id].protected; }
    static function MoveVehicle(id,v) { if(!command("group_move",[id,v])) return false; vehicles[v].group <- id; return true; }
    static function GetNumVehicles(id,mode) { local n=0; foreach(v,row in vehicles) if("group" in row && row.group==id) n++; return n; }
}

class AITile {
    static SLOPE_FLAT=0;
    static function GetSlope(t) { return "slope_override" in getroottable()?::slope_override:0; }
    static function IsBuildable(t) { return true; }
}
