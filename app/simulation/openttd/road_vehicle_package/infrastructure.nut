class RoadFreightProof extends GSController {
    requests = 0;
    used = null;
    ready = null;
    bound = null;
    stage = 0;
    halted = false;

    function Vacant(t) {
        return GSTile.IsBuildable(t) && GSTile.GetSlope(t) == 0 &&
            GSTile.GetOwner(t) == GSCompany.COMPANY_INVALID &&
            !GSTile.IsWaterTile(t) && !GSTile.IsCoastTile(t) &&
            !GSTile.HasTreeOnTile(t) && !GSTile.IsFarmTile(t) &&
            !GSTile.IsRockTile(t) && !GSTile.IsRoughTile(t) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_ROAD) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_RAIL) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_WATER) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_AIR);
    }
    function Linked(a,b) {
        return GSRoad.AreRoadTilesConnected(a,b) && GSRoad.AreRoadTilesConnected(b,a);
    }
    function State(q,r) {
        local s = q.start-1; local d = q.end+1;
        r.owners = [GSTile.GetOwner(s), GSTile.GetOwner(q.start),
                    GSTile.GetOwner(q.end), GSTile.GetOwner(d)];
        r.road = [GSRoad.IsRoadTile(q.start), GSRoad.IsRoadTile(q.end)];
        r.stop = GSRoad.IsRoadStationTile(s);
        r.depot = GSRoad.IsRoadDepotTile(d);
        r.fronts = [r.stop ? GSRoad.GetRoadStationFrontTile(s) : -1,
                    r.depot ? GSRoad.GetRoadDepotFrontTile(d) : -1];
        r.sid = r.stop ? GSStation.GetStationID(s) : -1;
        r.truck = r.stop && !GSRoad.IsDriveThroughRoadStationTile(s) &&
            GSStation.IsValidStation(r.sid) &&
            GSStation.HasStationType(r.sid, GSStation.STATION_TRUCK_STOP) &&
            !GSStation.HasStationType(r.sid, GSStation.STATION_BUS_STOP);
        r.links = [Linked(s,q.start), Linked(q.start,q.end), Linked(q.end,d)];
        r.eligible = Vacant(s) && Vacant(q.start) && Vacant(q.end) && Vacant(d) &&
            GSTile.GetMinHeight(s) == GSTile.GetMinHeight(q.start) &&
            GSTile.GetMinHeight(s) == GSTile.GetMinHeight(q.end) &&
            GSTile.GetMinHeight(s) == GSTile.GetMinHeight(d);
        r.funds = GSCompany.GetBankBalance(q.company);
    }
    function Command(q,i) {
        if(i == 0) return GSRoad.BuildRoadFull(q.start,q.end);
        if(i == 1) return GSRoad.BuildRoadStation(q.start-1,q.start,
            GSRoad.ROADVEHTYPE_TRUCK, GSStation.STATION_NEW);
        return GSRoad.BuildRoadDepot(q.end+1,q.end);
    }
    function Test(q,i) {
        local accounting = GSAccounting(); local testing = GSTestMode();
        local ok = Command(q,i); local cost = accounting.GetCosts();
        testing = null; accounting = null;
        return [ok,cost];
    }
    function Matches(q) {
        return ready != null && ready.company == q.company && ready.start == q.start &&
            ready.end == q.end && ready.max_cost == q.max_cost;
    }
    function Correct(q,r,i) {
        local s = i >= 1; local d = i >= 2;
        return r.owners[0] == (s ? q.company : GSCompany.COMPANY_INVALID) &&
            r.owners[1] == q.company && r.owners[2] == q.company &&
            r.owners[3] == (d ? q.company : GSCompany.COMPANY_INVALID) &&
            r.road[0] && r.road[1] && r.stop == s && r.truck == s && r.depot == d &&
            r.fronts[0] == (s ? q.start : -1) && r.fronts[1] == (d ? q.end : -1) &&
            r.links[0] == s && r.links[1] && r.links[2] == d;
    }
    function Handle(q) {
        if(typeof q != "table" || q.len() != 8) return;
        foreach(k in ["protocol","op","request_id","plan","company","start","end","max_cost"])
            if(!(k in q)) return;
        if(q.protocol != 1 || typeof q.op != "string" ||
            (q.op != "inspect" && q.op != "road" && q.op != "stop" &&
             q.op != "depot" && q.op != "read") || typeof q.request_id != "string" ||
            q.request_id.len() < 1 || q.request_id.len() > 32 ||
            typeof q.plan != "string" || q.plan.len() != 64) return;
        for(local i=0;i<q.request_id.len();i++) {
            local c=q.request_id[i];
            if(!(c==45 || (c>=48 && c<=57) || (c>=97 && c<=122))) return;
        }
        for(local i=0;i<q.plan.len();i++) {
            local c=q.plan[i]; if(!((c>=48 && c<=57) || (c>=97 && c<=102))) return;
        }
        foreach(k in ["company","start","end","max_cost"]) if(typeof q[k] != "integer") return;
        if(q.company<0 || q.company>14 || q.start<0 || q.end>4095 ||
            q.max_cost<0 || q.max_cost>2147483647) return;
        if(used == null) used = {};
        if(q.request_id in used || requests >= 38) return;
        used[q.request_id] <- true; requests++;
        local r = {protocol=1,op=q.op,request_id=q.request_id,plan=q.plan,company=q.company,
            start=q.start,end=q.end,status="REJECTED",owners=[-1,-1,-1,-1],road=[false,false],
            stop=false,truck=false,depot=false,fronts=[-1,-1],links=[false,false,false],
            eligible=false,funds=0,costs=[0,0,0],cost=0,sid=-1};
        if(GSCompany.ResolveCompanyID(q.company) != q.company) r.status="INVALID_COMPANY";
        else if(q.end != q.start+1 || q.start%64<1 || q.start%64>60 ||
                !GSMap.IsValidTile(q.start-1) || !GSMap.IsValidTile(q.end+1))
            r.status="INVALID_LOCATION";
        else {
            local company = GSCompanyMode(q.company);
            if(!GSCompanyMode.IsValid()) r.status="INVALID_COMPANY";
            else {
                GSRoad.SetCurrentRoadType(GSRoad.ROADTYPE_ROAD);
                if(GSRoad.GetCurrentRoadType()!=0 || !GSRoad.IsRoadTypeAvailable(0))
                    r.status="UNSUPPORTED_ROAD_TYPE";
                else {
                    State(q,r);
                    if(ready != null) r.costs=ready.costs;
                    if(q.op=="read") r.status="READ";
                    else if(q.op=="inspect" && stage==0 && !halted) {
                        ready=null; r.costs=[0,0,0];
                        if(!r.eligible) r.status="NOT_BUILDABLE";
                        else {
                            local ok=true;
                            for(local i=0;i<3;i++) {
                                local t=Test(q,i); if(!t[0] || t[1]<=0) ok=false;
                                r.costs[i]=t[1];
                            }
                            local total=r.costs[0]+r.costs[1]+r.costs[2];
                            if(!ok) r.status="REJECTED";
                            else if(total>q.max_cost) r.status="COST_LIMIT";
                            else if(total>r.funds) r.status="INSUFFICIENT_FUNDS";
                            else { ready={company=q.company,start=q.start,end=q.end,
                                max_cost=q.max_cost,costs=r.costs}; r.status="READY"; }
                        }
                    } else {
                        local i=q.op=="road" ? 0 : (q.op=="stop" ? 1 : 2);
                        if(halted || q.op=="inspect" || i!=stage || !Matches(q) ||
                            (bound!=null && bound!=q.plan)) r.status="OUT_OF_ORDER";
                        else if((i==0 && !r.eligible) ||
                            (i>0 && (!Correct(q,r,i-1) ||
                                     !Vacant(i==1 ? q.start-1 : q.end+1))))
                            r.status="NOT_BUILDABLE";
                        else {
                            local t=Test(q,i); local remaining=0;
                            for(local j=i;j<3;j++) remaining+=ready.costs[j];
                            if(!t[0]) r.status="REJECTED";
                            else if(t[1]!=ready.costs[i]) r.status="COST_CHANGED";
                            else if(r.funds<remaining) r.status="INSUFFICIENT_FUNDS";
                            else {
                                bound=q.plan; halted=true; stage++;
                                local funds=r.funds; local accounting=GSAccounting();
                                local ok=Command(q,i); r.cost=accounting.GetCosts();
                                accounting=null; State(q,r);
                                if(!ok) r.status="REJECTED";
                                else if(!Correct(q,r,i) || r.cost!=ready.costs[i] ||
                                         funds-r.funds!=r.cost) r.status="READBACK_MISMATCH";
                                else { r.status="BUILT"; halted=false; }
                            }
                        }
                        if(r.status!="BUILT") halted=true;
                    }
                }
            }
            company=null;
        }
        if(r.funds < -2147483648 || r.funds > 2147483647 || r.cost < 0 ||
            r.cost > 2147483647) throw "FREIGHT_RESPONSE_OUT_OF_BOUNDS";
        foreach(c in r.costs) if(c<0 || c>2147483647) throw "FREIGHT_COST_OUT_OF_BOUNDS";
        if(!GSAdmin.Send(r)) throw "FREIGHT_RESPONSE_SEND_FAILED";
        GSLog.Info("FREIGHT_RESPONSE " + q.request_id + " " + r.status);
    }
    function Start() {
        GSLog.Info("ROAD_FREIGHT_READY");
        while(true) {
            while(GSEventController.IsEventWaiting()) {
                local e=GSEventController.GetNextEvent();
                if(e.GetEventType()==GSEvent.ET_ADMIN_PORT)
                    Handle(GSEventAdminPort.Convert(e).GetObject());
            }
            Sleep(1);
        }
    }
}
