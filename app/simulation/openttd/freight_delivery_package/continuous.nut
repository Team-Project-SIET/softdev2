/* Opt-in bounded capacity observation; only constructed fleet bindings can reload. */
require("continuous-parent.nut");
class ContinuousFreightProof extends NetworkFreightProof {
    cbegun=false; cstart=-1; ctargets=null; cseen=null; cpolls=0; cunique=null; cdelivered=null;
    tpolls=0; tseen=null;
    capacity_vehicle=-1; capacity_service=-1; capacity_attempted=false; capacity_receipt=null; capacity_reads=0; capacity_originals=null; capacity_limit=0;
    restored_fleet=false;
    /* Native save serializer accepts only value trees. Never retain live aliases. */
    function PersistenceCopy(value) {
        local kind=typeof value;
        if(kind=="array") {local out=[];foreach(v in value)out.append(PersistenceCopy(v));return out;}
        if(kind=="table") {local out={};foreach(k,v in value)out[k]<-PersistenceCopy(v);return out;}
        if(kind=="null"||kind=="integer"||kind=="string"||kind=="bool")return value;
        throw "CANONICAL_SAVE_VALUE_INVALID";
    }
    function PersistenceFields() {
        return ["active","parked","dused","drequests","planner_requests","planner_used",
            "construction_commands","capital_planning_started"];
    }
    function ValidFleet(data) {
        if(typeof data!="table"||data.len()!=3||!("services" in data)||
            !("state" in data)||!("schema" in data)||data.schema!=1||
            typeof data.services!="array"||data.services.len()!=3||typeof data.state!="table")return false;
        foreach(k in PersistenceFields())if(!(k in data.state))return false;
        if(data.state.len()!=PersistenceFields().len()||typeof data.state.active!="integer"||
            data.state.active<0||data.state.active>2||typeof data.state.capital_planning_started!="bool")return false;
        foreach(k in ["parked","drequests","planner_requests","construction_commands"])
            if(typeof data.state[k]!="integer"||data.state[k]<0)return false;
        foreach(k in ["dused","planner_used"]) {
            if(data.state[k]==null)continue;
            if(typeof data.state[k]!="table")return false;
            foreach(id,used in data.state[k])if(typeof id!="string"||used!=true)return false;
        }
        local vehicles={};local plans={};
        foreach(c in data.services) {
            if(typeof c!="table")return false;
            foreach(k in ["choice","planner_selected","dplan","dstage","dvehicle","dfailed",
                "dstations","monitors","monitor_pickup","monitor_delivery","period","closed",
                "baseline","obs_stage","route_logged"])if(!(k in c))return false;
            if(c.dstage!=10||c.dfailed!=false||typeof c.dvehicle!="integer"||c.dvehicle<0||
                typeof c.dplan!="string"||c.dplan.len()==0||c.dvehicle in vehicles||c.dplan in plans||
                typeof c.choice!="table"||!("a" in c.choice)||typeof c.choice.a!="array"||
                c.choice.a.len()!=10)return false;
            foreach(v in c.choice.a)if(typeof v!="integer")return false;
            vehicles[c.dvehicle]<-true;plans[c.dplan]<-true;
        }
        return true;
    }
    function Save() {
        Store();
        local data={scenario_capital=null,fleet_schema=1,fleet=null,
            fleet_status="unsupported"};
        if(!("SaveScenarioCapital" in this))return data;
        data.scenario_capital=SaveScenarioCapital();
        /* Keep failure/monitoring saves diagnostic, never silently resumable. */
        if(services==null&&active==-1&&!capital_planning_started)data.fleet_status="preconstruction";
        else if(!cbegun&&!capacity_attempted&&capacity_vehicle<0) {
            local state={};foreach(k in PersistenceFields())state[k]<-this[k];
            local fleet={schema=1,services=services,state=state};
            if(ValidFleet(fleet)){data.fleet=PersistenceCopy(fleet);data.fleet_status="constructed";}
        }
        return data;
    }
    function Load(version,data) {
        if(!("LoadScenarioCapital" in this)||typeof data!="table"||!("fleet_schema" in data)||data.fleet_schema!=1||
            !("fleet_status" in data)||!("fleet" in data)||!("scenario_capital" in data)||
            (data.fleet_status!="preconstruction"&&data.fleet_status!="constructed"))
            throw "CANONICAL_SAVE_UNSUPPORTED";
        if(data.fleet_status=="constructed"&&!ValidFleet(data.fleet))throw "CANONICAL_SAVE_INVALID";
        if(data.fleet_status=="preconstruction"&&data.fleet!=null)throw "CANONICAL_SAVE_INVALID";
        LoadScenarioCapital(data.scenario_capital);
        if(data.fleet_status=="preconstruction")return;
        if(capital_funding==null||!capital_funding.completed)throw "CANONICAL_SAVE_FUNDING_INVALID";
        local fleet=PersistenceCopy(data.fleet);services=fleet.services;
        foreach(k in PersistenceFields())if(k!="active")this[k]=fleet.state[k];
        active=-1;LoadService(fleet.state.active);restored_fleet=true;
    }
    /* Instance slot avoids closure.call's non-suspendable native frame. */
    PrepareNetworkDemo=NetworkFreightProof.PrepareDemo;
    function PrepareDemo() {
        if(restored_fleet)return;
        return PrepareNetworkDemo();
    }
    function ExpectedVehicleCount() {
        return NetworkFreightProof.ExpectedVehicleCount.call(this)+(capacity_vehicle>=0?1:0);
    }
    function OthersStopped() { return GSVehicleList().Count()==ExpectedVehicleCount(); }
    function Clock() {
        local d=GSDate.GetCurrentDate();
        return {economy_date=d,economy_year=GSDate.GetYear(d),economy_month=GSDate.GetMonth(d),
            economy_day=GSDate.GetDayOfMonth(d),calendar_date=null,
            timekeeping_units=GSGameSettings.GetValue("economy.timekeeping_units"),script_tick=GetTick(),paused=GSGame.IsPaused()};
    }
    function CapacityOriginals() {
        local out=[];
        foreach(c in services) {
            local v=c.dvehicle;local a=c.choice.a;
            out.append([v,GSVehicle.GetOwner(v),GSVehicle.GetEngineType(v),
                GSVehicle.GetCapacity(v,a[2]),GSVehicle.GetState(v),
                GSVehicle.GetLocation(v),GSOrder.GetOrderCount(v),
                GSOrder.GetOrderDestination(v,0),GSOrder.GetOrderFlags(v,0),
                GSOrder.GetOrderDestination(v,1),GSOrder.GetOrderFlags(v,1)]);
        }
        return out;
    }
    function CapacityOriginalsMatch(before) {
        local after=CapacityOriginals();
        foreach(i,row in before)foreach(j,value in row)if(after[i][j]!=value)return false;
        return true;
    }
    function CapacityReadback(r,c) {
        local v=capacity_vehicle;local a=c.choice.a;
        r.vehicle=v;r.tick=GetTick();r.economy_date=GSDate.GetCurrentDate();
        r.cash_after=GSCompany.GetBankBalance(0);
        r.owner=-1;r.engine=-1;r.capacity=0;r.state=-1;r.orders=[];
        if(v<0||!GSVehicle.IsValidVehicle(v))return;
        r.owner=GSVehicle.GetOwner(v);r.engine=GSVehicle.GetEngineType(v);
        r.capacity=GSVehicle.GetCapacity(v,a[2]);r.state=GSVehicle.GetState(v);
        r.orders=[];
        local n=GSOrder.GetOrderCount(v);
        if(n>2)throw "CAPACITY_ORDER_COUNT";
        for(local i=0;i<n;i++)r.orders.append([GSOrder.GetOrderDestination(v,i),
            GSOrder.GetOrderFlags(v,i),GSOrder.IsGotoStationOrder(v,i)]);
    }
    function CapacityCommand(stage,a) {
        if(stage==0)return GSVehicle.BuildVehicle(a[8],a[3]);
        if(stage<3)return GSOrder.AppendOrder(capacity_vehicle,a[stage==1?4:6],
            stage==1?GSOrder.OF_FULL_LOAD:GSOrder.OF_NO_LOAD);
        return GSVehicle.StartStopVehicle(capacity_vehicle);
    }
    /* One intervention only. A failed or partial mutation cannot be retried. */
    function CapacityRead(q) {
        if(q.len()!=5||q.protocol!=1||typeof q.request_id!="string"||
            q.request_id.len()<1||q.request_id.len()>32||capacity_receipt==null||
            typeof q.service!="integer"||q.service!=capacity_service||
            typeof q.max_cost!="integer"||q.max_cost!=capacity_limit||++capacity_reads>1||
            q.request_id==capacity_receipt.request_id)throw "CAPACITY_READ_INVALID";
        local mode=GSCompanyMode(0);local r=clone capacity_receipt;
        r.request_id=q.request_id;r.type="capacity-read-result";
        CapacityReadback(r,services[q.service]);
        if(!GSGame.IsPaused()||!CapacityOriginalsMatch(capacity_originals)||
            GSVehicleList().Count()!=4) {r.status="partial";r.error="CAPACITY_READ_WORLD_MISMATCH";}
        if(!GSAdmin.Send(r))throw "CAPACITY_READ_SEND_FAILED";mode=null;
    }
    function CapacityHandle(q) {
        if(q.len()!=5||!("protocol" in q)||q.protocol!=1||!("request_id" in q)||
            typeof q.request_id!="string"||q.request_id.len()<1||q.request_id.len()>32||
            !("service" in q)||typeof q.service!="integer"||q.service<0||q.service>2||
            !("max_cost" in q)||typeof q.max_cost!="integer"||q.max_cost<1||
            q.max_cost>2147483647)throw "CAPACITY_REQUEST_INVALID";
        if(cbegun||capacity_attempted||services==null||services.len()!=3||
            !GSGame.IsPaused())throw "CAPACITY_BOUNDARY_INVALID";
        Store();local mode=GSCompanyMode(0);GSRoad.SetCurrentRoadType(0);
        if(!GSCompanyMode.IsValid()||GSCompany.GetAutoRenewStatus(0)||
            GSVehicleList().Count()!=3)throw "CAPACITY_WORLD_INVALID";
        foreach(c in services)if(c.dstage!=10||c.dfailed||!GSVehicle.IsValidVehicle(c.dvehicle)||
            GSVehicle.GetOwner(c.dvehicle)!=0)throw "CAPACITY_ORIGINAL_INVALID";
        local c=services[q.service];local a=c.choice.a;local originals=CapacityOriginals();
        if(GSVehicle.GetEngineType(c.dvehicle)!=a[3]||
            GSOrder.GetOrderCount(c.dvehicle)!=2||
            GSOrder.GetOrderDestination(c.dvehicle,0)!=a[4]||
            GSOrder.GetOrderDestination(c.dvehicle,1)!=a[6]||
            GSOrder.GetOrderFlags(c.dvehicle,0)!=GSOrder.OF_FULL_LOAD||
            GSOrder.GetOrderFlags(c.dvehicle,1)!=GSOrder.OF_NO_LOAD||
            !GSOrder.IsGotoStationOrder(c.dvehicle,0)||
            !GSOrder.IsGotoStationOrder(c.dvehicle,1))throw "CAPACITY_ORIGINAL_ORDERS";
        capacity_attempted=true;capacity_service=q.service;
        capacity_originals=originals;capacity_limit=q.max_cost;
        local r={protocol=1,type="capacity-add-result",request_id=q.request_id,
            status="partial",service=q.service,vehicle=-1,original_vehicle=c.dvehicle,
            plan=c.dplan,engine=a[3],cargo=a[2],capacity=0,owner=-1,state=-1,
            orders=[],commands=[],purchase_capex=0,cash_before=GSCompany.GetBankBalance(0),
            cash_after=0,tick=GetTick(),economy_date=GSDate.GetCurrentDate(),error=null};
        try {
            for(local stage=0;stage<4;stage++) {
                local account=GSAccounting();local test=GSTestMode();
                local quoted=CapacityCommand(stage,a);local quote=account.GetCosts();test=null;account=null;
                if((stage==0?quoted!=0:!quoted)||quote<0||
                    (stage==0?(quote<1||quote>q.max_cost):quote!=0))throw "CAPACITY_QUOTE_REJECTED";
                local funds=GSCompany.GetBankBalance(0);
                if(funds<quote)throw "CAPACITY_FUNDS";
                account=GSAccounting();local result=CapacityCommand(stage,a);
                local cost=account.GetCosts();account=null;
                if(stage==0&&GSVehicle.IsValidVehicle(result))capacity_vehicle=result;
                if(stage==0)r.purchase_capex=cost;
                CapacityReadback(r,c);
                r.commands.append([stage,stage==0?capacity_vehicle>=0:result,quote,cost,
                    funds,r.cash_after]);
                if((stage==0?capacity_vehicle<0:!result)||cost!=quote||
                    funds-r.cash_after!=cost||r.owner!=0||r.engine!=a[3]||
                    !CapacityOriginalsMatch(originals)||GSVehicleList().Count()!=4||
                    r.capacity!=GSVehicle.GetCapacity(c.dvehicle,a[2])||
                    r.orders.len()!=(stage<3?stage:2))throw "CAPACITY_READBACK_MISMATCH";
                if(stage==0&&(!GSVehicle.IsInDepot(capacity_vehicle)||
                    GSVehicle.GetLocation(capacity_vehicle)!=a[8]))throw "CAPACITY_DEPOT_MISMATCH";
                if(stage>=1&&(r.orders[0][0]!=a[4]||r.orders[0][1]!=GSOrder.OF_FULL_LOAD||
                    !r.orders[0][2]))throw "CAPACITY_SOURCE_ORDER";
                if(stage>=2&&(r.orders[1][0]!=a[6]||r.orders[1][1]!=GSOrder.OF_NO_LOAD||
                    !r.orders[1][2]))throw "CAPACITY_DESTINATION_ORDER";
                if(stage==3&&r.state!=GSVehicle.VS_RUNNING&&r.state!=GSVehicle.VS_AT_STATION)
                    throw "CAPACITY_START_MISMATCH";
            }
            r.status="ok";
        }catch(error){r.error=error.tostring();CapacityReadback(r,c);}
        capacity_receipt=clone r;
        if(!GSAdmin.Send(r))throw "CAPACITY_RECEIPT_SEND_FAILED";
        mode=null;return r.status=="ok";
    }
    function Handle(q) {
        if(typeof q=="table"&&"type" in q&&q.type=="capacity-read")return CapacityRead(q);
        if(typeof q=="table"&&"type" in q&&q.type=="capacity-add")return CapacityHandle(q);
        if(typeof q!="table"||!("type" in q)||q.type.find("continuous-")!=0)
            {if(cbegun)throw "CONTINUOUS_OPERATION_SEALED";return this.NetworkHandle(q);}
        try { if(q.type=="continuous-telemetry")return TelemetryHandle(q); return ContinuousHandle(q); }
        catch(error) {
            if(!("request_id" in q)||typeof q.request_id!="string"||
                q.request_id.len()<1||q.request_id.len()>32)throw error;
            local reason=error.tostring();
            if(reason.len()>160)reason=reason.slice(0,160);
            if(!GSAdmin.Send({protocol=1,type=q.type+"-result",request_id=q.request_id,
                status="rejected",error=reason}))throw "CONTINUOUS_REJECTION_SEND_FAILED";
            GSLog.Info("CONTINUOUS_REJECTED "+q.request_id+" "+reason);
            return false;
        }
    }
    /* Opt-in point samples, not an exact event stream. Separate finite budget. */
    function TelemetryHandle(q) {
        if(!cbegun||q.len()!=5||!("protocol" in q)||q.protocol!=1||
            !("request_id" in q)||typeof q.request_id!="string"||
            q.request_id.len()<1||q.request_id.len()>32||!("service" in q)||
            typeof q.service!="integer"||q.service<0||q.service>=3||
            !("vehicle" in q)||typeof q.vehicle!="integer")throw "TELEMETRY_REQUEST_INVALID";
        if(tseen==null)tseen={};
        if(q.request_id in tseen||++tpolls>20000)throw "TELEMETRY_REQUEST_BUDGET";
        tseen[q.request_id]<-true;
        local mode=GSCompanyMode(0);local c=services[q.service];local a=c.choice.a;local v=q.vehicle;
        if((v!=c.dvehicle&&(v!=capacity_vehicle||q.service!=capacity_service))||
            !GSCompanyMode.IsValid()||!GSVehicle.IsValidVehicle(v)||GSVehicle.GetOwner(v)!=0||
            GSVehicle.GetEngineType(v)!=GSVehicle.GetEngineType(c.dvehicle)||
            GSVehicle.GetCapacity(v,a[2])<=0||
            GSOrder.GetOrderCount(v)!=2||GSOrder.GetOrderDestination(v,0)!=a[4]||
            GSOrder.GetOrderDestination(v,1)!=a[6]||!GSOrder.IsGotoStationOrder(v,0)||
            !GSOrder.IsGotoStationOrder(v,1)||GSOrder.GetOrderFlags(v,0)!=GSOrder.OF_FULL_LOAD||
            GSOrder.GetOrderFlags(v,1)!=GSOrder.OF_NO_LOAD)throw "TELEMETRY_VEHICLE_IDENTITY";
        local r={protocol=1,type="continuous-telemetry-result",request_id=q.request_id,status="ok",
            service=q.service,vehicle=v,tick=GetTick(),economy_date=GSDate.GetCurrentDate(),
            tile=GSVehicle.GetLocation(v),state=GSVehicle.GetState(v),speed=GSVehicle.GetCurrentSpeed(v),
            load=GSVehicle.GetCargoLoad(v,a[2]),capacity=GSVehicle.GetCapacity(v,a[2]),
            queue=GSStation.GetCargoWaiting(GSStation.GetStationID(a[4]),a[2]),
            stopped_in_depot=GSVehicle.IsInDepot(v),at_station=GSVehicle.GetState(v)==GSVehicle.VS_AT_STATION,
            source_tile=a[4],destination_tile=a[6],
            profit_this_year=GSVehicle.GetProfitThisYear(v),profit_last_year=GSVehicle.GetProfitLastYear(v),
            running_cost_rate_per_year=GSVehicle.GetRunningCost(v)};
        if(!GSAdmin.Send(r))throw "TELEMETRY_SEND_FAILED";mode=null;
    }
    function ContinuousHandle(q) {
        if(q.len()!=4||!("protocol" in q)||q.protocol!=1||!("request_id" in q)||
            typeof q.request_id!="string"||q.request_id.len()<1||q.request_id.len()>32||
            !("service" in q)||typeof q.service!="integer")throw "CONTINUOUS_REQUEST_INVALID";
        if(cseen==null)cseen={};
        if(q.request_id in cseen||++cpolls>14401)throw "CONTINUOUS_REQUEST_BUDGET";
        cseen[q.request_id]<-true;
        Store();local mode=GSCompanyMode(0);GSRoad.SetCurrentRoadType(0);
        if(!GSCompanyMode.IsValid()||services==null||services.len()!=3)
            throw "CONTINUOUS_NETWORK_INVALID";
        if(GSCompany.GetAutoRenewStatus(0))throw "CONTINUOUS_AUTORENEW_ENABLED";
        local r={protocol=1,type=q.type+"-result",request_id=q.request_id,status="ok",clock=Clock()};
        if(q.type=="continuous-begin") {
            if(cbegun||q.service!=-1)throw "CONTINUOUS_BEGIN_INVALID";
            foreach(i,c in services) {
                if(c.dstage!=10||c.dfailed||!GSVehicle.IsValidVehicle(c.dvehicle)||
                    GSVehicle.GetOwner(c.dvehicle)!=0||GSVehicle.GetState(c.dvehicle)==GSVehicle.VS_STOPPED)
                    throw "CONTINUOUS_SERVICE_NOT_READY";
            }
            cstart=r.clock.economy_date;ctargets=[];
            for(local n=1;n<=5;n++) {
                local y=r.clock.economy_year+n;local day=r.clock.economy_day;
                local target=GSDate.GetDate(y,r.clock.economy_month,day);
                if(target<=cstart)throw "CONTINUOUS_DATE_INVALID";ctargets.append(target);
            }
            cunique=[];cdelivered=[];
            foreach(i,c in services) {
                local unique=true;
                foreach(j,other in services)if(i!=j&&other.choice.a[1]==c.choice.a[1]&&
                    other.choice.a[2]==c.choice.a[2])unique=false;
                cunique.append(unique);cdelivered.append(0);
                if(unique)GSCargoMonitor.GetIndustryDeliveryAmount(0,c.choice.a[2],c.choice.a[1],true);
            }
            r.baseline_snapshots<-[];r.baseline_delivered<-[];
            for(local i=0;i<3;i++) {
                LoadService(i);local s=Snapshot();
                if(s[5]!=0||s[12]!=2||s[28]!=1||s[29]!=1)throw "CONTINUOUS_BASELINE_INVALID";
                r.baseline_snapshots.append(s);r.baseline_delivered.append(cunique[i]?0:null);Store();
            }
            cbegun=true;r.annual_targets<-ctargets;r.start_economy_date<-cstart;
        } else if(!cbegun)throw "CONTINUOUS_NOT_BEGUN";
        else if(q.type=="continuous-company") {
            if(q.service!=-1)throw "CONTINUOUS_COMPANY_INVALID";
        } else if(q.type=="continuous-service") {
            if(q.service<0||q.service>=3)throw "CONTINUOUS_SERVICE_INVALID";
            local c=services[q.service];local v=c.dvehicle;local a=c.choice.a;
            if(!GSVehicle.IsValidVehicle(v))throw "CONTINUOUS_VEHICLE_DESTROYED";
            LoadService(q.service);local s=Snapshot();
            if(s[5]!=0||s[12]!=2||s[13]!=a[4]||s[14]!=a[6]||s[28]!=1||s[29]!=1||
                s[9]==GSVehicle.VS_STOPPED||s[9]==GSVehicle.VS_CRASHED)
                throw "CONTINUOUS_ROUTE_OR_ORDER_INVALID";
            r.service<-q.service;r.plan<-c.dplan;r.vehicle<-v;r.snapshot<-s;
            r.profit_this_year<-GSVehicle.GetProfitThisYear(v);
            r.profit_last_year<-GSVehicle.GetProfitLastYear(v);
            r.running_cost_rate_per_year<-GSVehicle.GetRunningCost(v);
            if(cunique[q.service])cdelivered[q.service]+=GSCargoMonitor.GetIndustryDeliveryAmount(0,a[2],a[1],true);
            r.delivered<-cunique[q.service]?cdelivered[q.service]:null;
            r.revenue<-null;r.operating_costs<-null;r.completed_delivery_cycles<-null;
            r.station_waiting_cargo<-GSStation.GetCargoWaiting(s[16],a[2]);
            r.cargo_load<-s[11];r.capacity<-s[7];Store();
        } else throw "CONTINUOUS_OPERATION_INVALID";
        if(q.type=="continuous-begin"||q.type=="continuous-company") {
            r.cash<-GSCompany.GetBankBalance(0);r.loan_balance<-GSCompany.GetLoanAmount();
            r.quarter_income<-GSCompany.GetQuarterlyIncome(0,0);
            r.quarter_expenses<-GSCompany.GetQuarterlyExpenses(0,0);
            r.quarter_delivered<-GSCompany.GetQuarterlyCargoDelivered(0,0);
            r.previous_quarter_income<-GSCompany.GetQuarterlyIncome(0,1);
            r.previous_quarter_expenses<-GSCompany.GetQuarterlyExpenses(0,1);
            r.previous_quarter_delivered<-GSCompany.GetQuarterlyCargoDelivered(0,1);
            r.loan_interest<-null;r.expense_categories<-null;r.vehicle_operating_expenses<-null;
        }
        if(!GSAdmin.Send(r))throw "CONTINUOUS_SEND_FAILED";mode=null;
    }
}
