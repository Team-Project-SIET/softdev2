/* Controlled game API peers; production selection/build/sealing methods stay intact. */
::roads <- {};
::edges <- {};
::stations <- {};
::depots <- {};
::vehicles <- [];
::responses <- []; ::funds <- 500000; ::cost <- 0; ::testing <- false;
::road_type <- 0;
::road_available <- true;
::paused <- false; ::failed_command <- false; ::partial_command <- false;
function Spend(n) {::cost+=n;if(!::testing)::funds-=n;}
function Complete() {if(!::testing){NativeCommand();if(::failed_command)return false;}
return true;}
::GSAccounting <- class {constructor(){::cost=0;::testing=false;}function GetCosts(){return ::cost;}};
::GSTestMode <- class {constructor(){::testing=true;}};
::GSCompanyMode <- class {constructor(c){}static function IsValid(){return true;}};
::GSCompany <- class {
 static COMPANY_INVALID=-1;static CURRENT_QUARTER=0;
 static function ResolveCompanyID(c){return c;}
 static function GetAutoRenewStatus(c){return false;}
 static function GetBankBalance(c){return ::funds;}static function GetLoanAmount(){return 100000;}
 static function GetQuarterlyCargoDelivered(c,q){return 0;}
 static function GetQuarterlyIncome(c,q){return 0;}
};
::GSAdmin <- class {static function Send(r){::responses.append(r);return true;}};
::GSGame <- class {static function IsPaused(){return ::paused;}};
::GSMap <- class {
 static function IsValidTile(t){return t>=0&&t<4096;}
 static function GetMapSize(){return 4096;}
 static function GetMapSizeX(){return 64;}
 static function GetMapSizeY(){return 64;}
 static function DistanceManhattan(a,b){local x=a%64-b%64;local y=a/64-b/64;return (x<0?-x:x)+(y<0?-y:y);}
};
::GSDate <- class {
 static function GetCurrentDate(){return 712223;}static function GetYear(d){return 1950;}
 static function GetMonth(d){return 1;}
};
::GSTile <- class {
 static TRANSPORT_ROAD=0;static TRANSPORT_RAIL=1;static TRANSPORT_WATER=2;static TRANSPORT_AIR=3;
 static function GetSlope(t){return 0;}static function GetMinHeight(t){return 1;}
 static function IsWaterTile(t){return false;}static function IsCoastTile(t){return false;}
 static function HasTreeOnTile(t){return false;}static function IsFarmTile(t){return false;}
 static function IsRockTile(t){return false;}static function IsRoughTile(t){return false;}
 static function GetOwner(t){return t in ::roads||t in ::stations||t in ::depots?0:-1;}
 static function IsBuildable(t){return GSTile.GetOwner(t)==-1;}
 static function HasTransportType(t,k){return k==0&&GSTile.GetOwner(t)==0;}
 static function GetCargoProduction(t,c,w,h,r){return 1;}
 static function GetCargoAcceptance(t,c,w,h,r){return 8;}
 static function DemolishTile(t){return true;}
};
::GSIndustry <- class {
 static CAS_ACCEPTED=1;
 static function IsValidIndustry(i){return i>=0&&i<6;}
 static function GetIndustryType(i){return i%2;}
 static function GetLocation(i){return i%2==0?20+(8+i/2*18)*64:36+(16+i/2*18)*64;}
 static function GetIndustryID(t){for(local i=0;i<6;i++)if(GSIndustry.GetLocation(i)==t)return i;return -1;}
 static function GetLastMonthProduction(i,c){return i%2==0?100:0;}
 static function IsCargoAccepted(i,c){return GSIndustry.CAS_ACCEPTED;}
 static function GetCargoLastAcceptedDate(i,c){return -1;}
};
::GSCargo <- class {static function IsValidCargo(c){return c==1;}};
::GSEngine <- class {
 static function IsBuildable(e){return e==123;}static function IsValidEngine(e){return e==123;}
 static function GetVehicleType(e){return 0;}static function IsArticulated(e){return false;}
 static function CanRunOnRoad(e,r){return true;}static function HasPowerOnRoad(e,r){return true;}
 static function GetCargoType(e){return 1;}static function CanRefitCargo(e,c){return true;}
 static function GetCapacity(e){return 20;}static function GetPrice(e){return 5;}
};
::GSRoad <- class {
 static ROADTYPE_ROAD=0;static ROADVEHTYPE_TRUCK=0;static BT_ROAD=0;
 static function SetCurrentRoadType(t){if(GSRoad.IsRoadTypeAvailable(t))::road_type=t;}
 static function GetCurrentRoadType(){return ::road_type;}
 static function IsRoadTypeAvailable(t){return ::road_available&&t==0;}static function GetRoadVehicleTypeForCargo(c){return 0;}
 static function GetBuildCost(t,k){return 0;}
 static function HasRoadType(t,k){return t in ::roads||t in ::stations||t in ::depots;}
 static function IsRoadTile(t){return t in ::roads;}
 static function AreRoadTilesConnected(a,b){return GSRoad.IsRoadTypeAvailable(GSRoad.GetCurrentRoadType())&&(a+":"+b) in ::edges;}
 static function IsRoadStationTile(t){return t in ::stations;}
 static function IsRoadDepotTile(t){return GSRoad.IsRoadTypeAvailable(GSRoad.GetCurrentRoadType())&&t in ::depots;}
 static function GetRoadStationFrontTile(t){return ::stations[t];}
 static function GetRoadDepotFrontTile(t){return ::depots[t];}
 static function BuildRoadFull(a,b){
  Spend(1);if(!Complete())return false;
  if(!::testing){local step=a/64==b/64?(b>a?1:-1):(b>a?64:-64);for(local t=a;;t+=step){::roads[t]<-true;if(t==b)break;::edges[t+":"+(t+step)]<-true;::edges[(t+step)+":"+t]<-true;}}
return ::testing||!::partial_command;
 }
 static function BuildRoad(a,b){return GSRoad.BuildRoadFull(a,b);}
 static function BuildRoadStation(t,f,k,s){Spend(1);if(!Complete())return false;if(!::testing)::stations[t]<-f;return true;}
 static function BuildRoadDepot(t,f){Spend(1);if(!Complete())return false;if(!::testing)::depots[t]<-f;return true;}
};
::GSStation <- class {
 static STATION_TRUCK_STOP=0;static STATION_NEW=-1;
 static function GetCoverageRadius(k){return 4;}
 static function GetStationID(t){return t in ::stations?t:65535;}
 static function GetCargoWaiting(s,c){return 0;}
};
::GSVehicleList <- class {function Count(){return ::vehicles.len();}};
::GSVehicle <- class {
 static VT_ROAD=0;static VS_STOPPED=2;static VS_RUNNING=0;static VS_AT_STATION=3;
 static function IsValidVehicle(v){return v>=0&&v<::vehicles.len();}
 static function GetOwner(v){return 0;}static function GetEngineType(v){return 123;}
 static function GetCapacity(v,c){return 20;}static function GetCargoLoad(v,c){return 0;}
 static function IsStoppedInDepot(v){return true;}static function IsInDepot(v){return true;}
 static function GetLocation(v){return ::vehicles[v].tile;}static function GetCurrentSpeed(v){return 0;}
 static function GetState(v){return GSVehicle.VS_STOPPED;}static function GetProfitThisYear(v){return 0;}
 static function BuildVehicle(t,e){Spend(5);if(!Complete())return -1;if(::testing)return 0;::vehicles.append({tile=t,orders=[]});return ::vehicles.len()-1;}
 static function StartStopVehicle(v){throw "UNEXPECTED_DISPATCH";}
};
::GSOrder <- class {
 static OF_FULL_LOAD=64;static OF_NO_LOAD=128;
 static function GetOrderCount(v){return ::vehicles[v].orders.len();}
 static function GetOrderDestination(v,n){return ::vehicles[v].orders[n].tile;}
 static function GetOrderFlags(v,n){return ::vehicles[v].orders[n].flags;}
 static function IsGotoStationOrder(v,n){return true;}
 static function AppendOrder(v,t,f){if(!Complete())return false;if(!::testing)::vehicles[v].orders.append({tile=t,flags=f});return true;}
};
function Selection(n) {
 local i=4-n*2;local s=GSIndustry.GetLocation(i);local d=GSIndustry.GetLocation(i+1);
 local ss=s-65;local ds=d-65;local a=[i,i+1,1,123,ss,ss+1,ds,ds-64,ss+1-64,(ss/64)*64+(ds-64)%64];
 local path=[];for(local t=a[5];t<=a[9];t++)path.append(t);
 for(local t=a[9]+64;t<=a[7];t+=64)path.append(t);
 local digest="";for(local j=0;j<64;j++)digest+=(n==0?"a":(n==1?"b":"c"));
 return {protocol=1,op="select",request_id="select-"+n,plan=digest,arg=0,max_cost=100000,a=a,path=path,depot_front=a[5]};
}
function Request(op,n,stage,id) {
 local q=Selection(n);return {protocol=1,op=op,request_id=id,plan=q.plan,arg=stage,max_cost=100000};
}
function SelectService(n) {
 b.Handle(Selection(n));
 if(responses.top().status!="READY"||b.active!=n||b.services[n].choice==null)throw "SELECT_NOT_READY";
 b.Handle(Request("read",n,n,"activate-"+n));
 if(responses.top().status!="READ"||b.active!=n||responses.top().s[22]!=0||b.dvehicle!=-1)throw "ACTIVATE_NOT_READY";
}
function BuildService(n) {
 for(local stage=0;stage<9;stage++) {
  b.Handle(Request("build",n,stage,"s"+n+"-build-"+stage));
  if(responses.top().status!="BUILT")throw "BUILD_"+stage+"_"+responses.top().status;
  b.Handle(Request("read",n,stage,"s"+n+"-read-"+stage));
  if(responses.top().status!="READ"||responses.top().s[22]!=stage+1||b.active!=n||b.dfailed)throw "STATE_CONTINUITY";
 }
}
function SealService(n, id=null) {
 b.Handle({protocol=1,type="canonical-seal",request_id=id==null?"seal-"+n:id,service=n});
 if(b.services[n].dstage!=10||responses.top().status!="ok")throw "SEAL_NOT_COMMITTED";
}
::b <- CanonicalFreightProof();
b.capital_funding=ScenarioCapitalFunding();b.capital_funding.completed=true;

function CollectorDepots() {
 local out=[];
 foreach(c in b.services) {
  local tile=c.choice.a[8];
  b.Handle({protocol=1,type="canonical-page",request_id="depot-"+tile,section="map",offset=tile});
  local row=responses.top().records[0];
  if(row.tile!=GSVehicle.GetLocation(c.dvehicle)||!GSVehicle.IsStoppedInDepot(c.dvehicle)||
   !row.depot||row.owner!=0||row.edges.len()==0)throw "ROAD_CONTEXT_DEPOT_MISMATCH";
  out.append(row);
 }
 return out;
}
function RestoreForCollector() {
 b.capital_funding.autorenew_set=true;
 local saved=b.Save();
 if(saved.fleet_status!="constructed")throw "FLEET_NOT_SAVED";
 b=CanonicalFreightProof();::road_type=-1;
 b.Load(1,saved);b.PrepareDemo();
 if(!b.restored_fleet||b.services.len()!=3||GSRoad.GetCurrentRoadType()!=-1)throw "RESTORE_CONTEXT";
}
function InitializeCollector() {
 b.Handle(Request("read",0,0,"activate-reload-context"));
 local r=responses.top();
 if(r.status!="READ"||r.s[2]!=1||r.s[22]!=10||r.s[28]!=1||r.s[29]!=1||
  GSRoad.GetCurrentRoadType()!=0||!GSRoad.IsRoadTypeAvailable(0))throw "CONTEXT_READ_REJECTED";
 b.CanonicalOriginals(true);
}
