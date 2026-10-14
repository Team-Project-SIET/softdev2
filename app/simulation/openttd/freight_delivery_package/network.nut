require("network-parent.nut");
class NetworkFreightProof extends PlannerFreightProof {
    services=null; active=-1; parked=0;
    function Store() {
        if(active<0)return;
        services[active]={choice=choice,planner_selected=planner_selected,dplan=dplan,dstage=dstage,
            dvehicle=dvehicle,dfailed=dfailed,dstations=dstations,monitors=monitors,
            monitor_pickup=monitor_pickup,monitor_delivery=monitor_delivery,period=period,
            closed=closed,baseline=baseline,obs_stage=obs_stage,route_logged=route_logged};
    }
    function Load(n) {
        Store();active=n;local c=services[n];
        choice=c.choice;planner_selected=c.planner_selected;dplan=c.dplan;dstage=c.dstage;
        dvehicle=c.dvehicle;dfailed=c.dfailed;dstations=c.dstations;monitors=c.monitors;
        monitor_pickup=c.monitor_pickup;monitor_delivery=c.monitor_delivery;
        period=c.period;closed=c.closed;baseline=c.baseline;obs_stage=c.obs_stage;route_logged=c.route_logged;
    }
    function ExpectedVehicleCount() {
        local count=dvehicle>=0?1:0;
        if(services!=null)foreach(n,c in services)if(n!=active&&c!=null&&c.dvehicle>=0)count++;
        return count;
    }
    function OthersStopped() {
        if(services!=null)foreach(n,c in services)if(n!=active&&c!=null&&c.dvehicle>=0)
            if(!GSVehicle.IsValidVehicle(c.dvehicle)||GSVehicle.GetOwner(c.dvehicle)!=0||
                GSVehicle.GetState(c.dvehicle)!=GSVehicle.VS_STOPPED||
                GSVehicle.GetCargoLoad(c.dvehicle,c.choice.a[2])!=0)return false;
        return GSVehicleList().Count()==ExpectedVehicleCount();
    }
    function RecordConstruction(i,result,quoted,cost,funds) {
        base.RecordConstruction(i,result,quoted,cost,funds);
        if(i==6&&GSVehicle.IsValidVehicle(result))GSLog.Info("FREIGHT_GAME_TIME_CONSTRUCTION plan="+dplan+
            " date="+GSDate.GetCurrentDate()+" tick="+GetTick());
    }
    function PrepareDemo() {
        GSLog.Info("FREIGHT_GAME_TIME_START date="+GSDate.GetCurrentDate()+" tick="+GetTick());
        if(GSIndustry.GetIndustryCount()!=0)throw "NETWORK_REQUIRES_EMPTY_WORLD";
        if(GSGameSettings.GetValue("economy.multiple_industry_per_town")!=1)
            throw "NETWORK_REQUIRES_MULTIPLE_INDUSTRY_PER_TOWN";
        local cargo=GSIndustryType.GetProducedCargo(0).Begin();
        if(!GSIndustryType.IsRawIndustry(0)||!GSIndustryType.GetAcceptedCargo(1).HasItem(cargo))
            throw "NETWORK_CONTENT_MISMATCH";
        foreach(y in [20,44]) {
            foreach(site in [[0,20+y*64],[1,36+(y+8)*64]]) {
                local type=site[0];local tile=site[1];local before=GSIndustry.GetIndustryCount();
                if(!GSMap.IsValidTile(tile)||GSTile.GetSlope(tile)!=0||GSTile.GetMinHeight(tile)!=1||
                    GSTile.IsWaterTile(tile)||GSIndustry.IsValidIndustry(GSIndustry.GetIndustryID(tile)))
                    throw "NETWORK_INDUSTRY_SITE_CONFLICT type="+type+" tile="+tile;
                if(!GSIndustryType.BuildIndustry(type,tile)) {
                    local error=GSError.GetLastError();
                    throw "NETWORK_INDUSTRY_BUILD_FAILED type="+type+" tile="+tile+
                        " built="+before+" error="+error;
                }
                // Some native power-station layouts leave their anchor tile empty.
                local industry=-1;local matches=0;local built=GSIndustryList();
                for(local i=built.Begin();!built.IsEnd();i=built.Next())
                    if(GSIndustry.GetIndustryType(i)==type&&GSIndustry.GetLocation(i)==tile) {
                        industry=i;matches++;
                    }
                if(GSIndustry.GetIndustryCount()!=before+1||matches!=1)
                    throw "NETWORK_INDUSTRY_BUILD_READBACK_FAILED type="+type+" tile="+tile;
                GSLog.Info("FREIGHT_NETWORK_INDUSTRY_BUILT type="+type+" tile="+tile+" industry="+industry);
            }
        }
        if(GSIndustry.GetIndustryCount()!=4)throw "NETWORK_INDUSTRY_COUNT_MISMATCH";
        // Bounded preparation is separate from company construction spending.
        local industries=GSIndustryList();local count=0;
        for(local src=industries.Begin();!industries.IsEnd();src=industries.Next()) {
            if(GSIndustry.GetIndustryType(src)!=0)continue;
            local s=GSIndustry.GetLocation(src);local target=-1;
            local dsts=GSIndustryList_CargoAccepting(cargo);
            for(local d=dsts.Begin();!dsts.IsEnd();d=dsts.Next())
                if(GSIndustry.GetLocation(d)/64==s/64+8)target=d;
            if(target<0)throw "NETWORK_INDUSTRY_LOCATION_MISMATCH";
            local d=GSIndustry.GetLocation(target);local ss=s-65;local ds=d-65;
            local a=[src,target,cargo,-1,ss,ss+1,ds,ds-64,ss+1-64,(ss/64)*64+(ds-64)%64];
            local tiles=this.DeliveryTiles(a);if(tiles==null)throw "NETWORK_CLEAR_BOUND";
            tiles.append(ss);tiles.append(ds);tiles.append(a[8]);
            foreach(t in tiles) {
                if(++count>104||!GSMap.IsValidTile(t)||GSTile.GetSlope(t)!=0||GSTile.GetMinHeight(t)!=1||
                    GSIndustry.IsValidIndustry(GSIndustry.GetIndustryID(t))||GSTile.IsWaterTile(t)||
                    GSTile.GetOwner(t)!=GSCompany.COMPANY_INVALID)throw "NETWORK_UNSAFE_CLEARING";
                if(!Vacant(t)&&!GSTile.DemolishTile(t))throw "NETWORK_CLEAR_FAILED";
                if(!Vacant(t))throw "NETWORK_CLEAR_READBACK_FAILED";
            }
        }
        GSLog.Info("FREIGHT_NETWORK_WORLD_READY cleared_bound="+count);
    }
    function Quote(i) {
        if(i==0||i==1) {
            local path=planner_selected.path;local complete=true;local n=1;
            while(n<path.len()) {
                local first=n-1;local step=path[n]-path[n-1];local horizontal=path[n]/64==path[n-1]/64;
                while(n+1<path.len()&&path[n+1]-path[n]==step)n++;
                if((i==0)==horizontal&&!RoadState(path[first],path[n]))complete=false;
                n++;
            }
            if(complete)return [true,0];
        }
        if(i==2&&RoadState(planner_selected.depot_front,choice.a[8]))return [true,0];
        if((i==3||i==4)&&FacilityState(i)&&RoadState(choice.a[i==3?5:7],choice.a[i==3?4:6]))return [true,0];
        if(i==5&&FacilityState(i))return [true,0];
        return this.PlannerQuote(i);
    }
    function Handle(q) {
        if(typeof q!="table")return;
        if("type" in q)return this.PlannerHandle(q);
        if(!("op" in q)||!("request_id" in q)||!("arg" in q)||!("plan" in q))return;
        if(q.op=="select") {
            if(services==null)services=[];
            if(services.len()>=2||ExpectedVehicleCount()!=0)throw "NETWORK_SELECTION_ORDER";
            Store();active=services.len();services.append(null);
            choice=null;planner_selected=null;dplan=null;dstage=0;dvehicle=-1;dfailed=false;
            dstations=null;monitors=false;monitor_pickup=0;monitor_delivery=0;period=null;closed=null;
            baseline=null;obs_stage=0;route_logged=false;
            this.PlannerHandle(q);Store();return;
        }
        if(q.op=="read"&&q.request_id.find("activate-")==0) {
            if(services==null||services.len()<1||services.len()>2||q.arg<0||q.arg>=services.len())throw "NETWORK_ACTIVATION_ORDER";
            Load(q.arg);
        }
        if(!OthersStopped())throw "NETWORK_OTHER_VEHICLE_ACTIVE_OR_FOREIGN";
        if(q.op=="finish"&&q.arg==1) {
            if(q.protocol!=1||q.max_cost!=100000||q.len()!=6||q.plan!=dplan||q.request_id in dused||
                drequests>=58||dstage!=10||obs_stage!=4||monitors||dfailed||
                GSVehicle.GetCargoLoad(dvehicle,choice.a[2])!=0)throw "NETWORK_PARK_ORDER";
            dused[q.request_id]<-true;drequests++;dfailed=true;
            local mode=GSCompanyMode(0);GSRoad.SetCurrentRoadType(0);
            local funds=GSCompany.GetBankBalance(0);
            if(!GSVehicle.StartStopVehicle(dvehicle)||GSVehicle.GetState(dvehicle)!=GSVehicle.VS_STOPPED||
                GSCompany.GetBankBalance(0)!=funds)throw "NETWORK_PARK_FAILED";
            dfailed=false;parked++;dcost=0;local s=Snapshot();
            if(!GSAdmin.Send({protocol=1,op=q.op,request_id=q.request_id,plan=q.plan,arg=q.arg,
                max_cost=q.max_cost,status="PARKED",a=choice.a,f=choice.f,s=s,e=Period(s)}))throw "NETWORK_SEND_FAILED";
            GSLog.Info("FREIGHT_NETWORK_PARKED vehicle="+dvehicle+" service="+active);mode=null;Store();return;
        }
        this.PlannerHandle(q);Store();
    }
}
