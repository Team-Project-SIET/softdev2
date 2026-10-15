class RoadMutationProof extends GSController {
    attempted = false;
    requests = 0;
    used = null;

    function Vacant(tile) {
        return GSTile.IsBuildable(tile) && GSTile.GetSlope(tile) == 0 &&
            GSTile.GetOwner(tile) == GSCompany.COMPANY_INVALID &&
            !GSTile.IsWaterTile(tile) && !GSTile.IsCoastTile(tile) &&
            !GSTile.HasTreeOnTile(tile) && !GSTile.IsFarmTile(tile) &&
            !GSTile.IsRockTile(tile) && !GSTile.IsRoughTile(tile) &&
            !GSTile.HasTransportType(tile, GSTile.TRANSPORT_ROAD) &&
            !GSTile.HasTransportType(tile, GSTile.TRANSPORT_RAIL) &&
            !GSTile.HasTransportType(tile, GSTile.TRANSPORT_WATER) &&
            !GSTile.HasTransportType(tile, GSTile.TRANSPORT_AIR);
    }

    function State(q, r) {
        r.owner0 = GSTile.GetOwner(q.start);
        r.owner1 = GSTile.GetOwner(q.end);
        r.road0 = GSRoad.IsRoadTile(q.start);
        r.road1 = GSRoad.IsRoadTile(q.end);
        r.connected = GSRoad.AreRoadTilesConnected(q.start, q.end) &&
                      GSRoad.AreRoadTilesConnected(q.end, q.start);
        r.eligible = Vacant(q.start) && Vacant(q.end) &&
                    GSTile.GetMinHeight(q.start) == GSTile.GetMinHeight(q.end);
        r.funds = GSCompany.GetBankBalance(q.company);
    }

    function TestCost(q, r) {
        local accounting = GSAccounting();
        local testing = GSTestMode();
        local ok = GSRoad.BuildRoad(q.start, q.end);
        r.cost = accounting.GetCosts();
        testing = null;
        accounting = null;
        return ok;
    }

    function Handle(q) {
        if (typeof q != "table" || q.len() != 8) return;
        foreach (k in ["protocol", "op", "request_id", "plan", "company", "start", "end", "max_cost"])
            if (!(k in q)) return;
        if (q.protocol != 1 || typeof q.op != "string" ||
            (q.op != "inspect" && q.op != "build" && q.op != "read") ||
            typeof q.request_id != "string" || q.request_id.len() < 1 || q.request_id.len() > 32 ||
            typeof q.plan != "string" || q.plan.len() != 64) return;
        for (local i = 0; i < q.request_id.len(); i++) {
            local c = q.request_id[i];
            if (!(c == 45 || (c >= 48 && c <= 57) || (c >= 97 && c <= 122))) return;
        }
        for (local i = 0; i < q.plan.len(); i++) {
            local c = q.plan[i];
            if (!((c >= 48 && c <= 57) || (c >= 97 && c <= 102))) return;
        }
        foreach (k in ["company", "start", "end", "max_cost"])
            if (typeof q[k] != "integer") return;
        if (q.company < 0 || q.company > 14 || q.start < 0 || q.start > 4095 ||
            q.end < 0 || q.end > 4095 || q.max_cost < 0 || q.max_cost > 2147483647) return;
        if (used == null) used = {};
        if (q.request_id in used || requests >= 36) return;
        used[q.request_id] <- true;
        requests++;
        local r = {protocol=1, op=q.op, request_id=q.request_id, plan=q.plan,
            company=q.company, start=q.start, end=q.end, status="REJECTED",
            owner0=GSCompany.COMPANY_INVALID, owner1=GSCompany.COMPANY_INVALID,
            road0=false, road1=false, connected=false,
            eligible=false, funds=0, cost=0};
        if (GSCompany.ResolveCompanyID(q.company) != q.company) {
            r.status = "INVALID_COMPANY";
        } else if (!GSMap.IsValidTile(q.start) || !GSMap.IsValidTile(q.end) ||
                   GSMap.DistanceManhattan(q.start, q.end) != 1) {
            r.status = "INVALID_LOCATION";
        } else {
            local company = GSCompanyMode(q.company);
            if (!GSCompanyMode.IsValid()) { r.status = "INVALID_COMPANY"; }
            else {
                GSRoad.SetCurrentRoadType(GSRoad.ROADTYPE_ROAD);
                if (GSRoad.GetCurrentRoadType() != 0 || !GSRoad.IsRoadTypeAvailable(0)) {
                    r.status = "UNSUPPORTED_ROAD_TYPE";
                } else {
                    State(q, r);
                    if (q.op == "read") r.status = "READ";
                    else if (q.op == "build" && attempted) r.status = "ALREADY_ATTEMPTED";
                    else if (!r.eligible) r.status = "NOT_BUILDABLE";
                    else if (!TestCost(q, r) || r.cost <= 0) r.status = "REJECTED";
                    else if (r.cost > q.max_cost) r.status = "COST_LIMIT";
                    else if (r.funds < r.cost) r.status = "INSUFFICIENT_FUNDS";
                    else if (q.op == "inspect") r.status = "READY";
                    else {
                        // Latch before the real command, including a rejected native command.
                        attempted = true;
                        local accounting = GSAccounting();
                        local ok = GSRoad.BuildRoad(q.start, q.end);
                        r.cost = accounting.GetCosts();
                        accounting = null;
                        State(q, r);
                        r.status = !ok ? "REJECTED" :
                            (r.owner0 == q.company && r.owner1 == q.company &&
                             r.road0 && r.road1 && r.connected ? "BUILT" : "READBACK_MISMATCH");
                    }
                }
            }
            company = null;
        }
        // These numeric and ASCII bounds keep even the largest response below 512 bytes.
        if (r.funds < -2147483648 || r.funds > 2147483647 || r.cost < 0 ||
            r.cost > 2147483647) throw "ROAD_RESPONSE_OUT_OF_BOUNDS";
        if (!GSAdmin.Send(r)) throw "ROAD_RESPONSE_SEND_FAILED";
        GSLog.Info("ROAD_RESPONSE " + q.request_id + " " + r.status);
    }

    function Start() {
        GSLog.Info("ROAD_MUTATION_READY");
        while (true) {
            while (GSEventController.IsEventWaiting()) {
                local event = GSEventController.GetNextEvent();
                if (event.GetEventType() == GSEvent.ET_ADMIN_PORT)
                    Handle(GSEventAdminPort.Convert(event).GetObject());
            }
            Sleep(1);
        }
    }
}
