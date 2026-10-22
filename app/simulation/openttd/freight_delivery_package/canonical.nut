/* Qualification-only stopped-fleet acquisition and acknowledged dispatch. */
require("canonical-parent.nut");
require("canonical-collector.nut");
class CanonicalFreightProof extends ContinuousFreightProof {
    canonical_seen=null; canonical_started=false; canonical_armed=false; canonical_date=-1;
    function SelectionFleetReady() {
        if(!OthersStopped())return false;
        if(services!=null)foreach(n,c in services)if(n!=active&&
            (c==null||c.dstage!=10||c.dfailed))return false;
        return true;
    }
    function Save() {
        local data=ContinuousFreightProof.Save.call(this);
        if(canonical_started){data.fleet_status="unsupported";data.fleet=null;}
        return data;
    }
    function OthersStopped() {
        if(services!=null)foreach(n,c in services)if(n!=active&&c!=null&&c.dvehicle>=0)
            if(!GSVehicle.IsValidVehicle(c.dvehicle)||GSVehicle.GetOwner(c.dvehicle)!=0||
                !GSVehicle.IsStoppedInDepot(c.dvehicle)||GSVehicle.GetCargoLoad(c.dvehicle,c.choice.a[2])!=0)
                return false;
        return GSVehicleList().Count()==ExpectedVehicleCount();
    }
    ExecuteNetworkCommand=NetworkFreightProof.Execute;
    HandleContinuousRequest=ContinuousFreightProof.Handle;
    function Execute(i) {
        if(i==9)throw "CANONICAL_START_FORBIDDEN";
        return ExecuteNetworkCommand(i);
    }
    function CanonicalOriginals(require_stopped) {
        if(services==null||services.len()!=3)throw "CANONICAL_BINDINGS_MISSING";
        local out=[];local ids={};
        foreach(n,c in services) {
            local v=c.dvehicle;local a=c.choice.a;
            if(c.dstage!=10||c.dfailed||v in ids||!GSVehicle.IsValidVehicle(v)||
                GSVehicle.GetOwner(v)!=0||GSVehicle.GetEngineType(v)!=a[3]||
                GSVehicle.GetCapacity(v,a[2])<=0||GSVehicle.GetCargoLoad(v,a[2])!=0||
                !GSVehicle.IsInDepot(v)||GSVehicle.GetLocation(v)!=a[8]||
                GSVehicle.GetCurrentSpeed(v)!=0||GSOrder.GetOrderCount(v)!=2||
                GSOrder.GetOrderDestination(v,0)!=a[4]||GSOrder.GetOrderDestination(v,1)!=a[6]||
                GSOrder.GetOrderFlags(v,0)!=GSOrder.OF_FULL_LOAD||
                GSOrder.GetOrderFlags(v,1)!=GSOrder.OF_NO_LOAD||
                !GSOrder.IsGotoStationOrder(v,0)||!GSOrder.IsGotoStationOrder(v,1)||
                (require_stopped&&!GSVehicle.IsStoppedInDepot(v)))
                throw "CANONICAL_ORIGINAL_MISMATCH";
            ids[v]<-true;
            out.append([n,v,GSVehicle.GetLocation(v),GSVehicle.GetCargoLoad(v,a[2]),
                GSVehicle.GetCurrentSpeed(v),GSVehicle.GetState(v)]);
        }
        return out;
    }
    function CanonicalHandle(q) {
        if(q.len()!=4||q.protocol!=1||typeof q.request_id!="string"||
            q.request_id.len()<1||q.request_id.len()>32||typeof q.service!="integer")
            throw "CANONICAL_REQUEST_INVALID";
        if(canonical_seen==null)canonical_seen={};
        if(q.request_id in canonical_seen||canonical_seen.len()>=64)throw "CANONICAL_REQUEST_REPLAY";
        canonical_seen[q.request_id]<-true;
        Store();local mode=GSCompanyMode(0);GSRoad.SetCurrentRoadType(0);
        if(!GSCompanyMode.IsValid()||GSCompany.GetAutoRenewStatus(0))throw "CANONICAL_COMPANY_POLICY";
        local r={protocol=1,type=q.type+"-result",request_id=q.request_id,service=q.service,
            status="ok",tick=GetTick(),economy_date=GSDate.GetCurrentDate(),paused=GSGame.IsPaused(),
            command_pause_level=GSGameSettings.GetValue("construction.command_pause_level"),
            restored=restored_fleet,originals=[],extra=null,cash=GSCompany.GetBankBalance(0),loan=GSCompany.GetLoanAmount()};
        if(q.type=="canonical-dispatched") {
            if(q.service!=-1||!canonical_started)throw "CANONICAL_DISPATCH_NOT_STARTED";
            local deadline=GetTick()+64;
            while(GSGame.IsPaused()&&GetTick()<deadline)Sleep(1);
            if(GSGame.IsPaused())throw "CANONICAL_UNPAUSE_NOT_ACKNOWLEDGED";
            r.tick=GetTick();r.economy_date=GSDate.GetCurrentDate();r.paused=false;
            if(!GSAdmin.Send(r))throw "CANONICAL_SEND_FAILED";mode=null;return;
        }
        if(q.type=="canonical-seal") {
            if(canonical_armed||q.service!=active||dstage!=9||dfailed||!Route(choice.a)||
                !OthersStopped()||!GSVehicle.IsStoppedInDepot(dvehicle)||
                !GSVehicle.IsInDepot(dvehicle)||GSVehicle.GetLocation(dvehicle)!=choice.a[8]||
                GSVehicle.GetCargoLoad(dvehicle,choice.a[2])!=0||GSOrder.GetOrderCount(dvehicle)!=2||
                GSOrder.GetOrderDestination(dvehicle,0)!=choice.a[4]||
                GSOrder.GetOrderDestination(dvehicle,1)!=choice.a[6]||
                GSOrder.GetOrderFlags(dvehicle,0)!=GSOrder.OF_FULL_LOAD||
                GSOrder.GetOrderFlags(dvehicle,1)!=GSOrder.OF_NO_LOAD||
                !GSOrder.IsGotoStationOrder(dvehicle,0)||!GSOrder.IsGotoStationOrder(dvehicle,1))
                throw "CANONICAL_SEAL_INVALID";
            dstage=10;Store();
        } else {
            if(q.service!=-1||!r.paused||cbegun)throw "CANONICAL_PAUSE_REQUIRED";
            if(q.type=="canonical-ready")r.originals=CanonicalOriginals(true);
            else if(q.type=="canonical-arm") {
                if(canonical_armed||canonical_started||r.command_pause_level<2)
                    throw "CANONICAL_PAUSED_CONSTRUCTION_UNAVAILABLE";
                r.originals=CanonicalOriginals(true);canonical_date=r.economy_date;canonical_armed=true;
            } else if(q.type=="canonical-start") {
                if(!canonical_armed||canonical_started||r.economy_date!=canonical_date||
                    GSVehicleList().Count()!=(capacity_vehicle>=0?4:3))throw "CANONICAL_START_INVALID";
                CanonicalOriginals(true);canonical_started=true;
                foreach(c in services)if(!GSVehicle.StartStopVehicle(c.dvehicle))throw "CANONICAL_START_FAILED";
                r.originals=CanonicalOriginals(false);
                foreach(row in r.originals)if(GSVehicle.IsStoppedInDepot(row[1])||(row[5]!=GSVehicle.VS_RUNNING&&row[5]!=GSVehicle.VS_AT_STATION))
                    throw "CANONICAL_START_STATE";
            } else if(q.type=="canonical-dispatch-read") {
                if(!canonical_started||r.economy_date!=canonical_date)throw "CANONICAL_DISPATCH_INVALID";
                r.originals=CanonicalOriginals(false);
            } else throw "CANONICAL_OPERATION_INVALID";
        }
        if(q.type!="canonical-seal"&&(!GSGame.IsPaused()||GSDate.GetCurrentDate()!=r.economy_date))
            throw "CANONICAL_TIME_DRIFT";
        r.tick=GetTick();
        if(capacity_vehicle>=0) {
            local c=services[capacity_service];local v=capacity_vehicle;
            if(!GSVehicle.IsValidVehicle(v)||!GSVehicle.IsInDepot(v)||GSVehicle.IsStoppedInDepot(v)||
                GSVehicle.GetLocation(v)!=c.choice.a[8]||GSVehicle.GetCargoLoad(v,c.choice.a[2])!=0||
                GSVehicle.GetCurrentSpeed(v)!=0)throw "CANONICAL_EXTRA_MOVEMENT";
            r.extra=[capacity_service,v,GSVehicle.GetLocation(v),GSVehicle.GetCargoLoad(v,c.choice.a[2]),
                GSVehicle.GetCurrentSpeed(v),GSVehicle.GetState(v)];
        }
        if(!GSAdmin.Send(r))throw "CANONICAL_SEND_FAILED";mode=null;
    }
    function Handle(q) {
        if(typeof q=="table"&&"type" in q&&q.type=="canonical-page")return CanonicalCollect(this,q);
        if(typeof q=="table"&&"type" in q&&q.type.find("canonical-")==0)return CanonicalHandle(q);
        if(typeof q=="table"&&"type" in q&&q.type=="capacity-add") {
            if(!canonical_armed||canonical_started||q.service!=1||GSDate.GetCurrentDate()!=canonical_date||
                GSGameSettings.GetValue("construction.command_pause_level")<2)
                throw "CANONICAL_INTERVENTION_INVALID";
            CanonicalOriginals(true);return HandleContinuousRequest(q);
        }
        if(typeof q=="table"&&"type" in q&&q.type=="capacity-read")
            return HandleContinuousRequest(q);
        if(canonical_armed)throw "CANONICAL_MUTATIONS_SEALED";
        if(typeof q=="table"&&"op" in q&&q.op=="select") {
            if(services==null)services=[];
            Store();if(services.len()>=3||!OthersStopped())throw "CANONICAL_SELECTION_ORDER";
            foreach(c in services) {
                if(c==null||c.dstage!=10||c.dfailed)throw "CANONICAL_UNSEALED_SERVICE";
                if("plan" in q&&c.dplan==q.plan)throw "CANONICAL_DUPLICATE_SERVICE";
            }
            active=services.len();services.append(null);choice=null;planner_selected=null;dplan=null;
            dstage=0;dvehicle=-1;dfailed=false;dstations=null;monitors=false;monitor_pickup=0;
            monitor_delivery=0;period=null;closed=null;baseline=null;obs_stage=0;route_logged=false;
            this.PlannerHandle(q);Store();return;
        }
        return HandleContinuousRequest(q);
    }
}
