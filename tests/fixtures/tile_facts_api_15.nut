/* Controlled values for audited getters only, not native evidence. */
::width <- 4096; ::height <- 4096; ::date <- 2147483647;
::void_tile <- -1; ::road <- false; ::airport <- false;
::house <- false; ::station <- false; ::buildable <- true;
::owner <- -1; ::industry <- null; ::slope <- 0; ::elevation <- 0;
/* Native ScriptStorage starts at internal INVALID_ROADTYPE=63, not API -1. */
::current <- 63; ::available <- true; ::calls <- 0;
::selector_sets <- 0; ::selector_events <- []; ::setter_refuses <- false;
::tram <- false; ::custom_road <- false; ::getter_failure <- false;
class GSMap {
    static function GetMapSizeX(){::calls++; return ::width;}
    static function GetMapSizeY(){::calls++; return ::height;}
    static function GetTileIndex(x,y){::calls++; return y*::width+x;}
    static function IsValidTile(t){::calls++; return t>=0 && t<::width*::height && t!=::void_tile;}
    static function GetTileX(t){::calls++; return t%::width;}
    static function GetTileY(t){::calls++; return t/::width;}
}
class GSTile {
    static TRANSPORT_ROAD=1; static TRANSPORT_RAIL=2; static TRANSPORT_WATER=3;
    static function GetMinHeight(t){::calls++; if(::getter_failure)throw "controlled native getter failure"; return ::elevation;}
    static function GetSlope(t){::calls++; return ::slope;}
    static function IsBuildable(t){::calls++; return ::buildable && !::tram && !::custom_road;}
    static function IsWaterTile(t){::calls++; return false;}
    static function IsCoastTile(t){::calls++; return false;}
    static function HasTreeOnTile(t){::calls++; return false;}
    static function IsFarmTile(t){::calls++; return false;}
    static function IsRockTile(t){::calls++; return false;}
    static function IsRoughTile(t){::calls++; return false;}
    static function HasTransportType(t,kind){::calls++; if(kind==1)return ::road || ::tram || ::custom_road; if(kind!=2 && kind!=3)throw "AIR forbidden"; return false;}
    static function IsHouseTile(t){::calls++; return ::house;}
    static function IsStationTile(t){::calls++; return ::station;}
    static function GetOwner(t){::calls++; return ::owner;}
}
class GSRoad {
    static ROADTYPE_ROAD=0; static ROADTYPE_TRAM=1; static ROADTYPE_INVALID=-1;
    static function GetCurrentRoadType(){::calls++; ::selector_events.append("get"); return ::current;}
    static function IsRoadTypeAvailable(t){::calls++; ::selector_events.append("available"); return ::available;}
    static function SetCurrentRoadType(t){::selector_sets++; ::selector_events.append("set"); if(::available && !::setter_refuses)::current=t;}
    static function IsRoadTile(t){::calls++; return ::road || ::tram || ::custom_road;}
    static function HasRoadType(t,kind){::calls++; return ::road;}
    /* Asymmetric one-way relationship, never diagonal. */
    static function AreRoadTilesConnected(a,b){::calls++; return a<b;}
}
class GSAirport {static function IsAirportTile(t){::calls++; return ::airport;}}
class GSIndustry {
    static function GetIndustryID(t){::calls++; return ::industry == null ? 65535 : ::industry;}
    static function IsValidIndustry(id){::calls++; return id>=0 && id<64000;}
}
class GSDate {static function GetCurrentDate(){::calls++; return ::date;}}
