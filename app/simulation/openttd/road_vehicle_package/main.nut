require("infrastructure.nut");
class RoadVehicleProof extends RoadFreightProof {
    vstage = 0;
    vhalted = false;
    vused = null;
    vrequests = 0;
    selected = null;
    vehicle_id = -1;
    vehicle_plan = null;
    checked = false;

    function Site(q) {
        if(q.depot!=q.stop+3 || q.stop/64!=q.depot/64 ||
            !GSMap.IsValidTile(q.stop) || !GSMap.IsValidTile(q.depot)) return false;
        for(local t=q.stop;t<=q.depot;t++) if(GSTile.GetOwner(t)!=q.company) return false;
        return GSRoad.IsRoadDepotTile(q.depot) && GSRoad.GetRoadDepotFrontTile(q.depot)==q.depot-1 &&
            GSRoad.IsRoadStationTile(q.stop) && !GSRoad.IsDriveThroughRoadStationTile(q.stop) &&
            GSRoad.GetRoadStationFrontTile(q.stop)==q.stop+1 &&
            GSRoad.IsRoadTile(q.stop+1) && GSRoad.IsRoadTile(q.stop+2) &&
            GSStation.IsValidStation(GSStation.GetStationID(q.stop)) &&
            GSStation.HasStationType(GSStation.GetStationID(q.stop),GSStation.STATION_TRUCK_STOP) &&
            !GSStation.HasStationType(GSStation.GetStationID(q.stop),GSStation.STATION_BUS_STOP) &&
            Linked(q.stop,q.stop+1) && Linked(q.stop+1,q.stop+2) && Linked(q.stop+2,q.depot);
    }
    function Compatible(e) {
        return GSEngine.IsBuildable(e) && GSEngine.IsValidEngine(e) &&
            GSEngine.GetVehicleType(e)==GSVehicle.VT_ROAD && !GSEngine.IsArticulated(e) &&
            GSEngine.CanRunOnRoad(e,0) && GSEngine.HasPowerOnRoad(e,0) &&
            GSCargo.IsValidCargo(GSEngine.GetCargoType(e)) &&
            GSRoad.GetRoadVehicleTypeForCargo(GSEngine.GetCargoType(e))==GSRoad.ROADVEHTYPE_TRUCK &&
            GSEngine.CanRefitCargo(e,GSEngine.GetCargoType(e)) && GSEngine.GetCapacity(e)>0;
    }
    function VState(q,r) {
        r.funds=GSCompany.GetBankBalance(q.company);
        if(selected!=null) {
            r.engine=selected.engine; r.cargo=selected.cargo;
            r.capacity=selected.capacity; r.price=selected.price;
            r.available=GSEngine.IsBuildable(r.engine); r.compatible=Compatible(r.engine);
        }
        r.vehicle=vehicle_id;
        if(vehicle_id>=0 && GSVehicle.IsValidVehicle(vehicle_id) && GSVehicle.IsPrimaryVehicle(vehicle_id)) {
            r.engine=GSVehicle.GetEngineType(vehicle_id);
            r.owner=GSVehicle.GetOwner(vehicle_id); r.location=GSVehicle.GetLocation(vehicle_id);
            r.capacity=GSVehicle.GetCapacity(vehicle_id,r.cargo);
            r.indepot=GSVehicle.IsInDepot(vehicle_id); r.speed=GSVehicle.GetCurrentSpeed(vehicle_id);
            local s=GSVehicle.GetState(vehicle_id);
            r.state=s==GSVehicle.VS_IN_DEPOT ? "IN_DEPOT" : (s==GSVehicle.VS_RUNNING ? "RUNNING" :
                (s==GSVehicle.VS_AT_STATION ? "AT_STATION" : (s==GSVehicle.VS_STOPPED ? "STOPPED" :
                (s==GSVehicle.VS_BROKEN ? "BROKEN" : (s==GSVehicle.VS_CRASHED ? "CRASHED" : "INVALID")))));
            local n=GSOrder.GetOrderCount(vehicle_id);
            r.order=[n,n>0 ? GSOrder.GetOrderDestination(vehicle_id,0) : -1,
                n>0 ? GSOrder.GetOrderFlags(vehicle_id,0) : 0,
                n>0 && GSOrder.IsGotoStationOrder(vehicle_id,0)];
        }
    }
    function VCommand(q,op) {
        if(op=="purchase") return GSVehicle.BuildVehicle(q.depot,q.engine);
        if(op=="order") return GSOrder.AppendOrder(vehicle_id,q.stop,GSOrder.OF_NONE);
        return GSVehicle.StartStopVehicle(vehicle_id);
    }
    function VTest(q,op) {
        local a=GSAccounting(); local t=GSTestMode();
        local value=VCommand(q,op); local cost=a.GetCosts();
        t=null; a=null;
        return [op=="purchase" ? value==0 : value,cost];
    }
    function Identity(q) {
        return selected!=null && q.engine==selected.engine && q.cargo==selected.cargo &&
            q.depot==selected.depot && q.stop==selected.stop && q.company==selected.company &&
            q.max_cost==selected.max_cost && q.expected_cost==selected.price &&
            (vehicle_plan==null || q.plan==vehicle_plan);
    }
    function Stopped(r,n) {
        return r.owner==0 && r.state=="IN_DEPOT" && r.indepot && r.location==selected.depot &&
            r.capacity==selected.capacity && r.order[0]==n &&
            (n==0 || (r.order[1]==selected.stop && r.order[2]==0 && r.order[3]));
    }
    function Motion(q,r) {
        local first=GetTick(); local previous=first; local polls=0; local paused=false;
        for(local i=0;i<=256;i++) {
            local tick=GetTick(); polls++;
            VState(q,r); paused=GSGame.IsPaused();
            if(paused) {r.status="PAUSED";break;}
            if(tick<first || (i>0 && tick<=previous)) {r.status="CLOCK_STALLED";break;}
            if(tick-first>256) {r.status="WINDOW_EXHAUSTED";break;}
            if(!Site(q) || r.order[0]!=1 || r.order[1]!=q.stop || r.order[2]!=0 || !r.order[3])
                {r.status="INVALID_ROUTE";break;}
            if(r.owner!=q.company || r.engine!=q.engine || r.capacity!=selected.capacity ||
                (r.state!="RUNNING" && r.state!="AT_STATION"))
                {r.status="READBACK_MISMATCH";break;}
            if(r.location!=q.depot && !r.indepot && r.location>=q.stop && r.location<q.depot)
                {r.status="MOVED";break;}
            if(tick-first>=256 || i==256) {r.status="WINDOW_EXHAUSTED";break;}
            previous=tick; Sleep(1);
        }
        local v=[];
        foreach(k in ["engine","cargo","vehicle","available","compatible","capacity","price","cost",
                      "funds","owner","location","state","indepot","speed","order"]) {
            v.append(r[k]); delete r[k];
        }
        r.v <- v; r.clock <- [first,GetTick(),polls,paused];
    }
    function Handle(q) {
        // The loaded infrastructure package remains read-only in this profile.
        if(typeof q=="table" && q.len()==8) {
            if("op" in q && q.op=="read") RoadFreightProof.Handle.call(this,q);
            return;
        }
        if(typeof q!="table" || q.len()!=12) return;
        foreach(k in ["protocol","op","request_id","plan","company","depot","stop",
                     "engine","cargo","vehicle","max_cost","expected_cost"]) if(!(k in q)) return;
        if(q.protocol!=1 || typeof q.op!="string" || typeof q.plan!="string" || q.plan.len()!=64 ||
            typeof q.request_id!="string" || q.request_id.len()<1 || q.request_id.len()>32) return;
        if(q.op!="engine" && q.op!="purchase" && q.op!="vread" && q.op!="order-check" &&
            q.op!="order" && q.op!="start-check" && q.op!="start" && q.op!="motion") return;
        foreach(k in ["company","depot","stop","engine","cargo","vehicle","max_cost","expected_cost"])
            if(typeof q[k]!="integer") return;
        if(q.company!=0 || q.depot<0 || q.depot>4095 || q.stop<0 || q.stop>4095 ||
            q.max_cost<0 || q.max_cost>2147483647 || q.expected_cost<0 || q.expected_cost>2147483647) return;
        foreach(k in ["engine","cargo","vehicle"]) if(q[k] < -1 || q[k]>65535) return;
        for(local i=0;i<q.plan.len();i++) {
            local c=q.plan[i]; if(!((c>=48 && c<=57) || (c>=97 && c<=102))) return;
        }
        for(local i=0;i<q.request_id.len();i++) {
            local c=q.request_id[i]; if(!(c==45 || (c>=48 && c<=57) || (c>=97 && c<=122))) return;
        }
        if(vused==null) vused={};
        if(q.request_id in vused || vrequests>=10) return;
        vused[q.request_id] <- true; vrequests++;
        local r={protocol=1,op=q.op,request_id=q.request_id,plan=q.plan,company=q.company,
            depot=q.depot,stop=q.stop,status="REJECTED",engine=q.engine,cargo=q.cargo,vehicle=q.vehicle,
            available=false,compatible=false,capacity=0,price=0,cost=0,funds=0,
            owner=-1,location=-1,state="INVALID",indepot=false,speed=0,order=[0,-1,0,false]};
        if(GSCompany.ResolveCompanyID(q.company)!=q.company) r.status="INVALID_COMPANY";
        else {
            local company=GSCompanyMode(q.company);
            if(!GSCompanyMode.IsValid()) r.status="INVALID_COMPANY";
            else {
                GSRoad.SetCurrentRoadType(GSRoad.ROADTYPE_ROAD);
                if(GSRoad.GetCurrentRoadType()!=0 || !GSRoad.IsRoadTypeAvailable(0) || !Site(q))
                    r.status=q.op=="motion" ? "INVALID_ROUTE" : "INVALID_SITE";
                else if(q.op=="engine" && vstage==0 && !vhalted && GSVehicleList().Count()!=0)
                    r.status="REJECTED";
                else if(q.op=="engine" && vstage==0 && !vhalted && selected==null) {
                    local list=GSEngineList(GSVehicle.VT_ROAD); local count=0; local best=-1;
                    for(local e=list.Begin();!list.IsEnd();e=list.Next()) {
                        count++; if(count>32) break;
                        if(Compatible(e) && (best==-1 || e<best)) best=e;
                    }
                    if(count>32) r.status="ENGINE_LIMIT";
                    else if(best==-1) r.status="NO_ENGINE";
                    else {
                        selected={engine=best,cargo=GSEngine.GetCargoType(best),capacity=GSEngine.GetCapacity(best),
                            price=GSEngine.GetPrice(best),depot=q.depot,stop=q.stop,
                            company=q.company,max_cost=q.max_cost};
                        VState(q,r);
                        local testq={depot=q.depot,engine=best}; local t=VTest(testq,"purchase"); r.cost=t[1];
                        if(!t[0]) r.status="REJECTED";
                        else if(r.cost<=0 || r.cost!=r.price) r.status="COST_CHANGED";
                        else if(r.cost>q.max_cost) r.status="COST_LIMIT";
                        else if(r.funds<r.cost) r.status="INSUFFICIENT_FUNDS";
                        else r.status="READY";
                    }
                } else if(!Identity(q) || (vehicle_id>=0 && q.vehicle!=vehicle_id) || vhalted)
                    r.status="OUT_OF_ORDER";
                else {
                    VState(q,r);
                    if(q.op=="vread") r.status="READ";
                    else if(q.op=="motion" && vstage==3) {
                        Motion(q,r);
                    } else {
                        local op=q.op=="order-check" ? "order" : (q.op=="start-check" ? "start" : q.op);
                        local stage=op=="purchase" ? 0 : (op=="order" ? 1 : 2);
                        local checking=q.op=="order-check" || q.op=="start-check";
                        if(stage!=vstage || (stage==0 && (q.vehicle!=-1 || !Compatible(q.engine))))
                            r.status=stage==0 ? "UNAVAILABLE_ENGINE" : "OUT_OF_ORDER";
                        else if(stage>0 && (!Stopped(r,stage-1) ||
                            !GSOrder.AreOrderFlagsValid(q.stop,GSOrder.OF_NONE))) r.status="READBACK_MISMATCH";
                        else {
                            local t=VTest(q,op); local expected=stage==0 ? q.expected_cost : 0;
                            if(!t[0]) r.status="REJECTED";
                            else if(t[1]!=expected) r.status="COST_CHANGED";
                            else if(r.funds<expected) r.status="INSUFFICIENT_FUNDS";
                            else if(checking) {checked=true;r.status="READY";}
                            else if(stage>0 && !checked) r.status="OUT_OF_ORDER";
                            else {
                                local funds=r.funds; vhalted=true; checked=false; vehicle_plan=q.plan;
                                local a=GSAccounting(); local result=VCommand(q,op); r.cost=a.GetCosts();a=null;
                                if(stage==0 && GSVehicle.IsValidVehicle(result)) vehicle_id=result;
                                VState(q,r);
                                if((stage==0 && vehicle_id==-1) || (stage>0 && !result)) r.status="REJECTED";
                                else if(r.cost!=expected || (stage<2 && funds-r.funds!=r.cost) ||
                                    (stage==0 && !Stopped(r,0)) || (stage==1 && !Stopped(r,1)) ||
                                    (stage==2 && r.state!="RUNNING" && r.state!="AT_STATION"))
                                    r.status="READBACK_MISMATCH";
                                else {vstage++;vhalted=false;r.status=stage==0 ? "PURCHASED" :
                                    (stage==1 ? "ORDERED" : "STARTED");}
                            }
                        }
                    }
                }
            }
            company=null;
        }
        if(r.status!="READY" && r.status!="READ" && r.status!="PURCHASED" &&
            r.status!="ORDERED" && r.status!="STARTED" && r.status!="MOVED") vhalted=true;
        if("v" in r) {
            foreach(i in [5,6,7,8,13]) if(r.v[i] < -2147483648 || r.v[i]>2147483647)
                throw "VEHICLE_RESPONSE_OUT_OF_BOUNDS";
            foreach(i in [0,1]) if(r.clock[i]<0 || r.clock[i]>2147483647)
                throw "VEHICLE_CLOCK_OUT_OF_BOUNDS";
        } else foreach(k in ["funds","price","cost","capacity","speed"]) if(r[k] < -2147483648 ||
                r[k]>2147483647) throw "VEHICLE_RESPONSE_OUT_OF_BOUNDS";
        if(!GSAdmin.Send(r)) throw "VEHICLE_RESPONSE_SEND_FAILED";
        GSLog.Info("VEHICLE_RESPONSE "+q.request_id+" "+r.status);
    }
    function Start() {
        GSLog.Info("ROAD_VEHICLE_READY");
        while(true) {
            while(GSEventController.IsEventWaiting()) {
                local e=GSEventController.GetNextEvent();
                if(e.GetEventType()==GSEvent.ET_ADMIN_PORT) Handle(GSEventAdminPort.Convert(e).GetObject());
            }
            Sleep(1);
        }
    }
}
