/* Separate one-tile bounded clearing handler. Additive: the frozen Tile
 * Classification observation package is not modified or imported. The only
 * mutation command is GSTile.DemolishTile in company mode; there is no
 * terraform, road or station command here. Classification predicates are
 * identical to the staged classification bridge and the Python precedence
 * authority, evaluated fully so an incomplete read is impossible by design. */
class TerrainClearingProof extends GSController {
    attempted = null
    requests = 0
    used = null
    /* Bound admission facts for stale-state guard. */
    admitted = null

    function Classify(flags, industry) {
        /* Precedence mirrors tile_classification.classify_tile exactly:
         * house > station > industry > water > coast > airport > road > rail
         * > dock > trees > farm > rock > rough > clear > unknown. */
        if (flags & (1 << 13)) return "HOUSE"
        if (flags & (1 << 14)) return "STATION"
        if (industry != null) return "INDUSTRY"
        if (flags & (1 << 1)) return "WATER"
        if (flags & (1 << 2)) return "COAST"
        if (flags & (1 << 12)) return "AIRPORT"
        if (flags & ((1 << 7) | (1 << 8) | (1 << 9))) return "ROAD"
        if (flags & (1 << 10)) return "RAIL"
        if (flags & (1 << 11)) return "DOCK"
        if (flags & (1 << 3)) return "TREES"
        if (flags & (1 << 4)) return "FARM"
        if (flags & (1 << 5)) return "ROCK"
        if (flags & (1 << 6)) return "ROUGH"
        if (flags & 1) return "CLEAR"
        return "UNKNOWN_OCCUPANCY"
    }

    function State(q, r) {
        local tile = q.tile
        /* Identical predicate set to the classification bridge, fully
         * evaluated (no short-circuit) so an incomplete read is impossible. */
        local buildable = GSTile.IsBuildable(tile)
        local water = GSTile.IsWaterTile(tile)
        local coast = GSTile.IsCoastTile(tile)
        local tree = GSTile.HasTreeOnTile(tile)
        local farm = GSTile.IsFarmTile(tile)
        local rock = GSTile.IsRockTile(tile)
        local rough = GSTile.IsRoughTile(tile)
        local road_tile = GSRoad.IsRoadTile(tile)
        local road_track = GSTile.HasTransportType(tile, GSTile.TRANSPORT_ROAD)
        local road_src = GSRoad.HasRoadType(tile, 0)
        local rail = GSTile.HasTransportType(tile, GSTile.TRANSPORT_RAIL)
        local dock = GSTile.HasTransportType(tile, GSTile.TRANSPORT_WATER)
        local airport = GSAirport.IsAirportTile(tile)
        local house = GSTile.IsHouseTile(tile)
        local station = GSTile.IsStationTile(tile)
        local predicates = [buildable, water, coast, tree, farm, rock, rough,
            road_tile, road_track, road_src, rail, dock, airport, house, station]
        foreach (v in predicates)
            if (typeof v != "bool") throw "TERRAIN_NATIVE_FACT"
        local flags = 0
        for (local i = 0; i < predicates.len(); i++)
            if (predicates[i]) flags = flags | (1 << i)
        local industry = GSIndustry.GetIndustryID(tile)
        if (!GSIndustry.IsValidIndustry(industry)) industry = null
        else if (industry < 0 || industry > 63999) throw "TERRAIN_NATIVE_FACT"
        local owner = GSTile.GetOwner(tile)
        if (owner < -1 || owner > 14) throw "TERRAIN_NATIVE_FACT"
        local elevation = GSTile.GetMinHeight(tile)
        local slope = GSTile.GetSlope(tile)
        if (elevation < 0 || elevation > 255 || slope < 0 || slope > 31) throw "TERRAIN_NATIVE_FACT"
        r.flags = flags
        r.industry = industry
        r.owner = owner
        r.elevation = elevation
        r.slope = slope
        r.funds = GSCompany.GetBankBalance(q.company)
    }

    function TestCost(q, r) {
        local accounting = GSAccounting()
        local testing = GSTestMode()
        local ok = GSTile.DemolishTile(q.tile)
        r.cost = accounting.GetCosts()
        testing = null
        accounting = null
        return ok
    }

    function Handle(q) {
        if (typeof q != "table" || q.len() != 7) return
        foreach (k in ["protocol", "op", "request_id", "plan", "company", "tile", "max_cost"])
            if (!(k in q)) return
        if (q.protocol != 2 || typeof q.op != "string" ||
            (q.op != "inspect" && q.op != "clear" && q.op != "read") ||
            typeof q.request_id != "string" || q.request_id.len() < 1 || q.request_id.len() > 32 ||
            typeof q.plan != "string" || q.plan.len() != 64) return
        for (local i = 0; i < q.request_id.len(); i++) {
            local c = q.request_id[i]
            if (!(c == 45 || (c >= 48 && c <= 57) || (c >= 97 && c <= 122))) return
        }
        for (local i = 0; i < q.plan.len(); i++) {
            local c = q.plan[i]
            if (!((c >= 48 && c <= 57) || (c >= 97 && c <= 102))) return
        }
        foreach (k in ["company", "tile", "max_cost"])
            if (typeof q[k] != "integer") return
        if (q.company < 0 || q.company > 14 || q.tile < 0 || q.tile > 65535 ||
            q.max_cost < 0 || q.max_cost > 2147483647) return
        if (used == null) used = {}
        if (attempted == null) attempted = {}
        if (admitted == null) admitted = {}
        if (q.request_id in used || requests >= 24) return
        used[q.request_id] <- true
        requests++
        local r = {protocol=2, op=q.op, request_id=q.request_id, plan=q.plan,
            company=q.company, tile=q.tile, status="REJECTED", flags=0,
            industry=null, owner=GSCompany.COMPANY_INVALID,
            elevation=0, slope=0, eligible=false, funds=0, cost=0}
        if (GSCompany.ResolveCompanyID(q.company) != q.company) {
            r.status = "INVALID_COMPANY"
        } else if (!GSMap.IsValidTile(q.tile) ||
                   GSMap.GetTileX(q.tile) != q.tile % GSMap.GetMapSizeX() ||
                   GSMap.GetTileY(q.tile) != q.tile / GSMap.GetMapSizeX()) {
            r.status = "INVALID_LOCATION"
        } else {
            local company = GSCompanyMode(q.company)
            if (!GSCompanyMode.IsValid()) { r.status = "INVALID_COMPANY" }
            else {
                local cls = null
                try {
                    State(q, r)
                    cls = Classify(r.flags, r.industry)
                    r.eligible = (cls == "TREES" || cls == "FARM" || cls == "ROUGH" ||
                                  cls == "ROCK") && r.owner == GSCompany.COMPANY_INVALID
                } catch (error) {
                    r.status = "UNSUPPORTED_NATIVE_FACT"
                }
                /* Read-only: pure observation. */
                if (r.status == "UNSUPPORTED_NATIVE_FACT") {
                    /* fail closed, no command */
                } else if (q.op == "read") {
                    r.status = "READ"
                } else if (cls == "CLEAR") {
                    /* Already-clear tiles are NO_OP: no quote, no demolition. */
                    r.status = "NO_OP"
                } else if (q.tile in attempted) {
                    r.status = "ALREADY_ATTEMPTED"
                } else if (cls != "TREES" && cls != "FARM" && cls != "ROUGH" && cls != "ROCK") {
                    /* House, station, industry, water, coast, airport, road,
                     * rail, dock and unknown occupancy are never cleared. */
                    r.status = "FORBIDDEN_CLASS"
                } else if (r.owner != GSCompany.COMPANY_INVALID) {
                    /* Foreign-owned or protected infrastructure is refused. */
                    r.status = "OWNERSHIP_MISMATCH"
                } else if (!TestCost(q, r) || r.cost <= 0) {
                    r.status = "REJECTED"
                } else if (r.cost > q.max_cost) {
                    r.status = "COST_LIMIT"
                } else if (r.funds < r.cost) {
                    r.status = "INSUFFICIENT_FUNDS"
                } else if (q.op == "inspect") {
                    r.status = "READY"
                    /* Bind admission facts for stale-state guard at execution.
                     * The company identity is bound too: a demolition command
                     * submitted by another company must never reuse this
                     * admission, so the executing company is compared here. */
                    admitted[q.tile] <- {
                        flags = r.flags,
                        industry = r.industry,
                        owner = r.owner,
                        elevation = r.elevation,
                        slope = r.slope,
                        classification = cls,
                        cost = r.cost,
                        funds = r.funds,
                        plan = q.plan,
                        company = q.company
                    }
                } else {
                    /* Execution path: re-observe tile state before real command. */
                    if (!(q.tile in admitted)) {
                        r.status = "STALE_ADMISSION"
                    } else {
                        local admit = admitted[q.tile]
                        /* Fresh observation for stale-state comparison. */
                        local tile = q.tile
                        local buildable = GSTile.IsBuildable(tile)
                        local water = GSTile.IsWaterTile(tile)
                        local coast = GSTile.IsCoastTile(tile)
                        local tree = GSTile.HasTreeOnTile(tile)
                        local farm = GSTile.IsFarmTile(tile)
                        local rock = GSTile.IsRockTile(tile)
                        local rough = GSTile.IsRoughTile(tile)
                        local road_tile = GSRoad.IsRoadTile(tile)
                        local road_track = GSTile.HasTransportType(tile, GSTile.TRANSPORT_ROAD)
                        local road_src = GSRoad.HasRoadType(tile, 0)
                        local rail = GSTile.HasTransportType(tile, GSTile.TRANSPORT_RAIL)
                        local dock = GSTile.HasTransportType(tile, GSTile.TRANSPORT_WATER)
                        local airport = GSAirport.IsAirportTile(tile)
                        local house = GSTile.IsHouseTile(tile)
                        local station = GSTile.IsStationTile(tile)
                        local fresh_predicates = [buildable, water, coast, tree, farm, rock, rough,
                            road_tile, road_track, road_src, rail, dock, airport, house, station]
                        foreach (v in fresh_predicates)
                            if (typeof v != "bool") throw "TERRAIN_NATIVE_FACT"
                        local fresh_flags = 0
                        for (local i = 0; i < fresh_predicates.len(); i++)
                            if (fresh_predicates[i]) fresh_flags = fresh_flags | (1 << i)
                        local fresh_industry = GSIndustry.GetIndustryID(tile)
                        if (!GSIndustry.IsValidIndustry(fresh_industry)) fresh_industry = null
                        else if (fresh_industry < 0 || fresh_industry > 63999) throw "TERRAIN_NATIVE_FACT"
                        local fresh_owner = GSTile.GetOwner(tile)
                        if (fresh_owner < -1 || fresh_owner > 14) throw "TERRAIN_NATIVE_FACT"
                        local fresh_elevation = GSTile.GetMinHeight(tile)
                        local fresh_slope = GSTile.GetSlope(tile)
                        if (fresh_elevation < 0 || fresh_elevation > 255 || fresh_slope < 0 || fresh_slope > 31) throw "TERRAIN_NATIVE_FACT"
                        local fresh_cls = Classify(fresh_flags, fresh_industry)

                        /* Stale-state guard: every bound fact must match,
                         * starting with the admission's plan and company
                         * identities. Adopted wire contract v2: the executing
                         * clear presents the ADMISSION plan (the plan of the
                         * inspect request that latched this entry); a clear
                         * under any other plan is foreign evidence and is
                         * refused here, before GSTile.DemolishTile can run. */
                        if (q.plan != admit.plan ||
                            q.company != admit.company ||
                            fresh_flags != admit.flags ||
                            fresh_industry != admit.industry ||
                            fresh_owner != admit.owner ||
                            fresh_elevation != admit.elevation ||
                            fresh_slope != admit.slope ||
                            fresh_cls != admit.classification) {
                            r.status = "STALE_ADMISSION"
                        } else if (fresh_cls != "TREES" && fresh_cls != "FARM" && fresh_cls != "ROUGH" && fresh_cls != "ROCK") {
                            r.status = "FORBIDDEN_CLASS"
                        } else if (fresh_owner != GSCompany.COMPANY_INVALID) {
                            r.status = "OWNERSHIP_MISMATCH"
                        } else {
                            /* Latch before the real command, including a rejected native command. */
                            attempted[q.tile] <- true
                            local accounting = GSAccounting()
                            local ok = GSTile.DemolishTile(q.tile)
                            r.cost = accounting.GetCosts()
                            accounting = null
                            /* Post-execution readback for receipt verification. */
                            try {
                                State(q, r)
                            } catch (error) {
                                r.status = "UNSUPPORTED_NATIVE_FACT"
                                r.elevation = fresh_elevation
                                r.slope = fresh_slope
                            }
                            if (r.status != "UNSUPPORTED_NATIVE_FACT") {
                                local cls2 = Classify(r.flags, r.industry)
                                if (!ok) {
                                    r.status = "REJECTED"
                                } else if (cls2 == "CLEAR" &&
                                     r.owner == GSCompany.COMPANY_INVALID &&
                                     r.elevation == fresh_elevation && r.slope == fresh_slope) {
                                    r.status = "CLEARED"
                                } else {
                                    r.status = "READBACK_MISMATCH"
                                }
                            }
                        }
                    }
                }
            }
            company = null
        }
        // These numeric and ASCII bounds keep even the largest response below 512 bytes.
        if (r.funds < -2147483648 || r.funds > 2147483647 || r.cost < 0 ||
            r.cost > 2147483647 || r.flags < 0 || r.flags > 32767 ||
            r.elevation < 0 || r.elevation > 255 || r.slope < 0 || r.slope > 31 ||
            r.owner < -1 || r.owner > 14) throw "TERRAIN_RESPONSE_OUT_OF_BOUNDS"
        if (!GSAdmin.Send(r)) throw "TERRAIN_RESPONSE_SEND_FAILED"
        GSLog.Info("TERRAIN_CLEARING_RESPONSE " + q.request_id + " " + r.status)
    }

    function Start() {
        GSLog.Info("TERRAIN_CLEARING_READY")
        while (true) {
            while (GSEventController.IsEventWaiting()) {
                local event = GSEventController.GetNextEvent()
                if (event.GetEventType() == GSEvent.ET_ADMIN_PORT)
                    Handle(GSEventAdminPort.Convert(event).GetObject())
            }
            Sleep(1)
        }
    }
}

/* Save-restore identity bridge: the retained frozen-source.zip info.nut
 * declares CreateInstance() returning "NetworkFreightProof". This subclass
 * satisfies that contract without modifying any retained identity byte. */
class NetworkFreightProof extends TerrainClearingProof {
}