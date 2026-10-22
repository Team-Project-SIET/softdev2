require("demo-world.nut");
require("qualification.nut");

/* Only observations and admission differ; delivery uses the proven parent. */
class PlannerFreightProof extends FreightDemoProof {
    observer=null; planner_selected=null; planner_requests=0; planner_used=null; route_logged=false; planner_quoting=false; construction_commands=0;
    function Start() {
        PrepareDemo(); observer=NoMutationBridge();
        GSLog.Info("BRIDGE_STARTED protocol=1 api=15");
        GSLog.Info("FREIGHT_DELIVERY_READY");
        local pending=[];
        while(true){
            foreach(id in pending)GSLog.Info("BRIDGE_POST_RESPONSE_ALIVE request_id="+id);
            pending.clear();
            for(local n=0;n<32&&GSEventController.IsEventWaiting();n++){
                local e=GSEventController.GetNextEvent();
                if(e.GetEventType()==GSEvent.ET_ADMIN_PORT){
                    local q=GSEventAdminPort.Convert(e).GetObject();
                    if(Handle(q))pending.append(q.request_id);
                }
            }
            Sleep(1);
        }
    }
    function Covered(t,industry,radius) {
        for(local y=t/64-radius;y<=t/64+radius;y++)for(local x=t%64-radius;x<=t%64+radius;x++)
            if(x>=0&&y>=0&&x<64&&y<64&&GSIndustry.GetIndustryID(y*64+x)==industry)return true;
        return false;
    }
    function PlanningRead(q) {
        if(q.len()!=8||q.protocol!=1||!observer.ValidRequestID(q.request_id)||
            typeof q.arg!="integer"||q.arg<0||q.arg>4095||choice!=null||dstage!=0)return;
        if(planner_used==null)planner_used={};
        if(q.request_id in planner_used||planner_requests>=292)return;
        planner_used[q.request_id]<-true;planner_requests++;
        local mode=GSCompanyMode(0);GSRoad.SetCurrentRoadType(0);
        if(!GSCompanyMode.IsValid()||GSCompany.ResolveCompanyID(0)!=0||
            GSRoad.GetCurrentRoadType()!=0||!GSRoad.IsRoadTypeAvailable(0))throw "PLANNER_COMPANY_ROAD_INVALID";
        local before=GSDate.GetCurrentDate();local data=[];
        if(q.kind=="settings")data=[GSGameSettings.GetValue("station.modified_catchment"),
            GSGameSettings.GetValue("station.serve_neutral_industries"),
            GSGameSettings.GetValue("economy.timekeeping_units"),
            GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP),GSRoad.GetMaxSpeed(0),
            GSRoad.GetBuildCost(0,GSRoad.BT_ROAD),GSRoad.GetBuildCost(0,GSRoad.BT_TRUCK_STOP),
            GSRoad.GetBuildCost(0,GSRoad.BT_DEPOT)];
        else if(q.kind=="engines") {
            local all=GSEngineList(GSVehicle.VT_ROAD);if(all.Count()>32)throw "PLANNER_ENGINE_LIMIT";
            for(local e=all.Begin();!all.IsEnd();e=all.Next())if(Compatible(e))data.append(e);
        } else if(q.kind=="engine") {
            local e=q.arg;if(!Compatible(e))throw "PLANNER_ENGINE_INVALID";
            data=[e,GSEngine.GetCargoType(e),GSEngine.GetRoadType(e),GSEngine.GetCapacity(e),
                GSEngine.GetPrice(e),GSEngine.GetRunningCost(e),GSEngine.GetMaxSpeed(e)];
        } else if(q.kind=="tile") {
            local t=q.arg;local r=GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP);
            local industry=GSIndustry.GetIndustryID(t);
            data=[t,GSTile.GetMinHeight(t),GSTile.GetSlope(t),Vacant(t)?1:0,
                GSTile.IsWaterTile(t)?1:0,GSTile.IsCoastTile(t)?1:0,GSTile.HasTreeOnTile(t)?1:0,
                GSTile.IsFarmTile(t)?1:0,GSTile.IsRockTile(t)?1:0,GSTile.IsRoughTile(t)?1:0,
                GSRoad.IsRoadTile(t)?1:0,GSTile.HasTransportType(t,GSTile.TRANSPORT_RAIL)?1:0,
                GSTile.HasTransportType(t,GSTile.TRANSPORT_WATER)?1:0,
                GSTile.HasTransportType(t,GSTile.TRANSPORT_AIR)?1:0,
                GSIndustry.IsValidIndustry(industry)?industry:-1,
                GSTile.GetCargoProduction(t,q.cargo,1,1,r),GSTile.GetCargoAcceptance(t,q.cargo,1,1,r),
                Covered(t,q.src,r)?1:0,Covered(t,q.dst,r)?1:0];
        } else return;
        if(!GSAdmin.Send({protocol=1,type="planning_read_result",request_id=q.request_id,
            kind=q.kind,arg=q.arg,src=q.src,dst=q.dst,cargo=q.cargo,
            before=before,after=GSDate.GetCurrentDate(),data=data}))throw "PLANNER_READ_SEND_FAILED";
        mode=null;
    }
    function Tiles(a) {
        if(planner_selected==null)return this.DeliveryTiles(a);
        return planner_selected.path;
    }
    function Quote(i) {
        planner_quoting=true;
        if(i!=3&&i!=4){local q=this.DeliveryQuote(i);planner_quoting=false;return q;}
        local a=choice==null?planner_selected.a:choice.a;local stop=a[i==3?4:6];local front=a[i==3?5:7];
        local account=GSAccounting();local test=GSTestMode();
        local ok=GSRoad.BuildRoadStation(stop,front,GSRoad.ROADVEHTYPE_TRUCK,GSStation.STATION_NEW);
        local station_cost=account.GetCosts();test=null;account=null;
        account=GSAccounting();test=GSTestMode();local road=GSRoad.BuildRoad(front,stop);
        local road_cost=account.GetCosts();test=null;account=null;
        account=GSAccounting();test=GSTestMode();local clear=GSTile.DemolishTile(stop);
        local clear_cost=account.GetCosts();test=null;account=null;planner_quoting=false;
        // Test mode leaves the bay vacant; its clearing and temporary road bit are not repeated live.
        local bit_cost=GSRoad.GetBuildCost(0,GSRoad.BT_ROAD);
        return [ok&&road&&clear&&bit_cost>=0&&clear_cost>=0&&road_cost>=bit_cost+clear_cost,
            station_cost+road_cost-bit_cost-clear_cost];
    }
    function RecordConstruction(i,result,quoted,cost,funds) {
        GSLog.Info("FREIGHT_CONSTRUCTION_STAGE plan="+dplan+" stage="+i+" result="+((i==6?GSVehicle.IsValidVehicle(result):result)?1:0)+
            " quoted="+quoted+" cost="+cost+" spent="+(funds-GSCompany.GetBankBalance(0)));
    }
    function RoadState(a,b) {
        local step=a/64==b/64?(b>a?1:-1):(b>a?64:-64);local complete=true;
        for(local t=a;;t+=step){
            if(GSTile.GetOwner(t)!=0||!GSRoad.HasRoadType(t,0))complete=false;
            if(t!=b&&!Linked(t,t+step))complete=false;
            if(t==b)break;
        }
        return complete&&GSRoad.GetCurrentRoadType()==0;
    }
    function CheckedRoad(a,b,full) {
        if(planner_quoting)return full?GSRoad.BuildRoadFull(a,b):GSRoad.BuildRoad(a,b);
        local before=RoadState(a,b);local funds=GSCompany.GetBankBalance(0);local result=true;local error=0;
        if(!before){
            if(++construction_commands>64)throw "CONSTRUCTION_COMMAND_LIMIT";
            result=full?GSRoad.BuildRoadFull(a,b):GSRoad.BuildRoad(a,b);error=GSError.GetLastError();
        }
        local after=RoadState(a,b);local spent=funds-GSCompany.GetBankBalance(0);
        local step=a/64==b/64?(b>a?1:-1):(b>a?64:-64);
        for(local t=a;t!=b;t+=step)RouteEdge(t,t+step);
        local classification=before?"ALREADY_SATISFIED":(result&&after?"COMMAND_SUCCEEDED":
            (!result&&after?"FAILED_STATE_CHANGED":"PARTIAL_OR_INCONSISTENT"));
        GSLog.Info("FREIGHT_CONSTRUCTION_ROAD plan="+dplan+" stage="+dstage+" a="+a+" b="+b+" full="+(full?1:0)+
            " before="+(before?1:0)+" result="+(result?1:0)+" error="+error+
            " after="+(after?1:0)+" spent="+spent+" classification="+classification);
        // Fail closed even when a failed command changed state; no automatic reconciliation.
        return result&&after&&spent>=0&&(!before||spent==0);
    }
    function FacilityState(i) {
        local a=choice.a;local t=a[i==3?4:(i==4?6:8)];
        return GSTile.GetOwner(t)==0&&GSRoad.HasRoadType(t,0)&&
            (i==5?GSRoad.IsRoadDepotTile(t)&&GSRoad.GetRoadDepotFrontTile(t)==planner_selected.depot_front:
                GSRoad.IsRoadStationTile(t)&&GSRoad.GetRoadStationFrontTile(t)==a[i==3?5:7]);
    }
    function CheckedFacility(i) {
        if(planner_quoting)return i==5?GSRoad.BuildRoadDepot(choice.a[8],planner_selected.depot_front):this.DeliveryExecute(i);
        local before=FacilityState(i);local funds=GSCompany.GetBankBalance(0);local result=true;local error=0;
        if(!before){
            if(++construction_commands>64)throw "CONSTRUCTION_COMMAND_LIMIT";
            result=i==5?GSRoad.BuildRoadDepot(choice.a[8],planner_selected.depot_front):this.DeliveryExecute(i);
            error=GSError.GetLastError();
        }
        local after=FacilityState(i);local spent=funds-GSCompany.GetBankBalance(0);
        GSLog.Info("FREIGHT_CONSTRUCTION_FACILITY plan="+dplan+" stage="+i+" before="+(before?1:0)+
            " result="+(result?1:0)+" error="+error+" after="+(after?1:0)+" spent="+spent+
            " classification="+(before?"ALREADY_SATISFIED":(result&&after?"COMMAND_SUCCEEDED":
                (!result&&after?"FAILED_STATE_CHANGED":"PARTIAL_OR_INCONSISTENT"))));
        return result&&after&&spent>=0&&(!before||spent==0);
    }
    function Execute(i) {
        if(i==0||i==1) {
            local path=planner_selected.path;
            local n=1;
            while(n<path.len()) {
                local first=n-1;local step=path[n]-path[n-1];
                local horizontal=path[n]/64==path[n-1]/64;
                while(n+1<path.len()&&path[n+1]-path[n]==step)n++;
                if((i==0)==horizontal&&!CheckedRoad(path[first],path[n],true))return false;
                n++;
            }
            return true;
        }
        if(i==2)return CheckedRoad(planner_selected.depot_front,choice.a[8],false);
        if(i==3||i==4) {
            local a=choice.a;local stop=a[i==3?4:6];local front=a[i==3?5:7];
            if(!CheckedFacility(i))return false;
            // Bay stops orient their own tile; the adjacent road still needs its entrance bit.
            return CheckedRoad(front,stop,false);
        }
        if(i==5)return CheckedFacility(i);
        return this.DeliveryExecute(i);
    }
    function RouteEdge(a,b) {
        GSLog.Info("FREIGHT_ROUTE_EDGE a="+a+" b="+b+" roadtype="+GSRoad.GetCurrentRoadType()+
            " owner_a="+GSTile.GetOwner(a)+" owner_b="+GSTile.GetOwner(b)+
            " type_a="+(GSRoad.HasRoadType(a,0)?1:0)+" type_b="+(GSRoad.HasRoadType(b,0)?1:0)+
            " forward="+(GSRoad.AreRoadTilesConnected(a,b)?1:0)+
            " reverse="+(GSRoad.AreRoadTilesConnected(b,a)?1:0));
    }
    function Route(a) {
        local path=planner_selected.path;
        if(dstage>=6&&!route_logged) {
            route_logged=true;
            for(local n=1;n<path.len();n++)RouteEdge(path[n-1],path[n]);
            RouteEdge(a[4],a[5]);RouteEdge(a[6],a[7]);RouteEdge(a[8],planner_selected.depot_front);
            GSLog.Info("FREIGHT_ROUTE_FRONTS origin="+GSRoad.GetRoadStationFrontTile(a[4])+
                " destination="+GSRoad.GetRoadStationFrontTile(a[6])+" depot="+GSRoad.GetRoadDepotFrontTile(a[8]));
        }
        if(GSRoad.GetCurrentRoadType()!=0)return false;
        foreach(t in path)if(GSTile.GetOwner(t)!=0||!GSRoad.IsRoadTile(t)||!GSRoad.HasRoadType(t,0))return false;
        for(local n=1;n<path.len();n++)if(!Linked(path[n-1],path[n]))return false;
        foreach(t in [a[4],a[6],a[8]])if(GSTile.GetOwner(t)!=0||!GSRoad.HasRoadType(t,0))return false;
        return GSRoad.IsRoadStationTile(a[4])&&GSRoad.IsRoadStationTile(a[6])&&
            GSRoad.GetRoadStationFrontTile(a[4])==a[5]&&GSRoad.GetRoadStationFrontTile(a[6])==a[7]&&
            GSRoad.IsRoadDepotTile(a[8])&&GSRoad.GetRoadDepotFrontTile(a[8])==planner_selected.depot_front&&
            Linked(a[4],a[5])&&Linked(a[6],a[7])&&Linked(a[8],planner_selected.depot_front)&&
            GSStation.GetStationID(a[4])!=GSStation.GetStationID(a[6]);
    }
    function SelectionFleetReady() {return GSVehicleList().Count()==0;}
    function Select() {
        if(planner_selected==null)return "PLANNER_SELECTION_REQUIRED";
        // The planner_selected geometry must be within the proven executor's exact footprint.
        local a=planner_selected.a;local tiles=Tiles(a);
        if(typeof tiles!="array"||tiles.len()<2||tiles.len()>47||tiles[0]!=a[5]||tiles.top()!=a[7])return "PLANNER_TOPOLOGY_REJECTED";
        local all_path=[a[4]];foreach(t in tiles)all_path.append(t);all_path.append(a[6]);
        for(local n=1;n<all_path.len();n++)if(!GSMap.IsValidTile(all_path[n-1])||!GSMap.IsValidTile(all_path[n])||
            GSMap.DistanceManhattan(all_path[n-1],all_path[n])!=1)return "PLANNER_TOPOLOGY_REJECTED";
        if(!GSMap.IsValidTile(a[8])||!GSMap.IsValidTile(planner_selected.depot_front)||
            GSMap.DistanceManhattan(a[8],planner_selected.depot_front)!=1)return "PLANNER_DEPOT_REJECTED";
        local front=false;foreach(t in tiles)if(t==planner_selected.depot_front)front=true;
        if(!front)return "PLANNER_DEPOT_REJECTED";
        if(!SelectionFleetReady()||GSGame.IsPaused()||tiles==null||
            !GSIndustry.IsValidIndustry(a[0])||!GSIndustry.IsValidIndustry(a[1])||a[0]==a[1]||
            !Compatible(a[3])||GSEngine.GetCargoType(a[3])!=a[2])return "PLANNER_IDENTITY_REJECTED";
        local all=clone tiles;all.append(a[4]);all.append(a[6]);all.append(a[8]);
        local seen={};local height=-1;
        foreach(t in all){if(!GSMap.IsValidTile(t)||t<65||t>4030||t in seen||!Vacant(t))return "PLANNER_FOOTPRINT_REJECTED";
            seen[t]<-true;local h=GSTile.GetMinHeight(t);if(height==-1)height=h;if(h!=height)return "PLANNER_HEIGHT_REJECTED";}
        local radius=GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP);
        if(radius<1||radius>4||CargoAt(a[4],a[2])!=a[0]||
            GSTile.GetCargoProduction(a[4],a[2],1,1,radius)!=1||
            GSTile.GetCargoAcceptance(a[6],a[2],1,1,radius)<8||!Covered(a[6],a[1],radius)||
            GSIndustry.GetLastMonthProduction(a[0],a[2])<=0||
            GSIndustry.IsCargoAccepted(a[1],a[2])!=GSIndustry.CAS_ACCEPTED)return "PLANNER_CARGO_REJECTED";
        choice={a=a,f=[GSIndustry.GetIndustryType(a[0]),GSIndustry.GetIndustryType(a[1]),
            GSIndustry.GetLocation(a[0]),GSIndustry.GetLocation(a[1]),GSIndustry.GetLastMonthProduction(a[0],a[2]),
            GSEngine.GetCapacity(a[3]),GSEngine.GetPrice(a[3]),radius],ceiling=0};
        local total=choice.f[6];local ok=total>0;
        for(local i=0;i<6;i++){local quote=Quote(i);if(!quote[0]||quote[1]<0||(i>=2&&quote[1]==0))ok=false;total+=quote[1];}
        if(!ok||total>100000||total>GSCompany.GetBankBalance(0)){choice=null;return "PLANNER_QUOTE_REJECTED";}
        choice.ceiling=total;return "READY";
    }
    function Handle(q) {
        if(typeof q=="table"&&"type" in q) {
            if(q.type=="planning_read")PlanningRead(q);
            else if(choice==null&&dstage==0)return observer.Handle(q);
            return;
        }
        if(typeof q=="table"&&"op" in q&&q.op=="select") {
            if(planner_selected!=null||choice!=null||q.len()!=9||typeof q.a!="array"||q.a.len()!=10)return;
            foreach(v in q.a)if(typeof v!="integer"||v<0||v>65534)return;
            planner_selected={a=q.a,path=q.path,depot_front=q.depot_front};
            q.rawdelete("a");q.rawdelete("path");q.rawdelete("depot_front");q.op="inspect";
        }
        this.DeliveryHandle(q);
    }
}
