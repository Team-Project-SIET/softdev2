/* API peers supply state only. NativeCommand uses the real fork's suspension gate. */
::tree <- 467; ::world <- []; ::events <- []; ::fail_build <- -1;
class GSController { function GetTick(){return 1;} function Sleep(n){throw "STARTUP_COMPLETE";} }
class GSLog {static function Info(s){::events.append(s);}}
class GSDate {static function GetCurrentDate(){return 712223;}}
class GSGameSettings {static function GetValue(n){return 1;}}
class GSCompany {static COMPANY_INVALID=-1;}
class GSMap {static function IsValidTile(t){return t>=0&&t<4096;}}
class GSTile {
 static function GetSlope(t){return 0;}static function GetMinHeight(t){return 1;}
 static function IsWaterTile(t){return false;}static function GetOwner(t){return -1;}
 static TRANSPORT_ROAD=0;static TRANSPORT_RAIL=1;static TRANSPORT_WATER=2;static TRANSPORT_AIR=3;
 static function IsBuildable(t){return true;}
 static function IsCoastTile(t){return false;}static function HasTreeOnTile(t){return t==::tree;}
 static function IsFarmTile(t){return false;}static function IsRockTile(t){return false;}
 static function IsRoughTile(t){return false;}static function HasTransportType(t,k){return false;}
 static function DemolishTile(t){::events.append("before-demolish");NativeCommand();::events.append("after-demolish");::tree=-1;return true;}
}
class GSError {static function GetLastError(){return 17;}}
class CargoList {function Begin(){return 3;}function HasItem(c){return c==3;}}
class GSIndustryType {
 static function GetProducedCargo(t){return CargoList();}
 static function GetAcceptedCargo(t){return CargoList();}
 static function IsRawIndustry(t){return t==0;}
 static function BuildIndustry(t,tile){
  ::events.append("before-command");
  local result=NativeCommand();
  ::events.append("after-command");
  if(::world.len()==::fail_build)return false;
  ::world.append({type=t,tile=tile});return result;
 }
}
class GSIndustry {
 static function GetIndustryCount(){return ::world.len();}
 static function GetIndustryID(t){foreach(i,w in ::world)if(w.tile==t)return i;return -1;}
 static function IsValidIndustry(i){return i>=0&&i<::world.len();}
 static function GetIndustryType(i){return ::world[i].type;}
 static function GetLocation(i){return ::world[i].tile;}
}
class GSIndustryList {
 ids=null;p=0;
 constructor(){ids=[];foreach(i,w in ::world)ids.append(i);}
 function Begin(){p=0;return ids.len()?ids[0]:-1;}
 function IsEnd(){return p>=ids.len();}
 function Next(){p++;return IsEnd()?-1:ids[p];}
}
class GSIndustryList_CargoAccepting extends GSIndustryList {
 constructor(c){ids=[];foreach(i,w in ::world)if(w.type==1)ids.append(i);}
}
class GSEventController {static function IsEventWaiting(){return false;}}
