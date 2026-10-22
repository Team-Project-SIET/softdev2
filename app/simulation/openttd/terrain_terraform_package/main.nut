/* Separate bounded one-corner terraforming handler. Additive: no existing
 * frozen package is modified or imported. The only native mutation commands
 * are GSTile.RaiseTile and GSTile.LowerTile in company mode, always with
 * exactly one official corner bit; GSTile.LevelTiles, demolition, road,
 * station and vehicle commands are absent by construction. Classification
 * predicates are identical to the staged classification bridge and the Python
 * precedence authority, evaluated fully so an incomplete read is impossible
 * by design.
 *
 * A RAISED/LOWERED status asserts the observed post-command host corner
 * geometry only (the commanded corner moved by exactly one step, the other
 * three host corners did not move, the min height stayed algebraically
 * consistent and the tile is still classified clear and unowned). No failed
 * command is ever reported as leaving the world unchanged: a failed terraform
 * may still have auto-cleared tiles and the phase evidence keeps the world
 * state explicitly uncertain. */
class TerrainTerraformProof extends GSController {
    attempted = null
    requests = 0
    used = null
    /* Bound admission facts for the stale-state guard. */
    admitted = null
    /* The reviewed terrain budget admits up to 32 bounded corner ops; one op
     * consumes 9 wire exchanges (inspect + 3 neighbor reads + terraform + 4
     * independent verification reads). 32 x 9 = 288 exchanges, plus slack, so
     * request 297 is the first one the dispatcher refuses. */
    max_requests = 296

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

    function MaskFor(corner) {
        /* Exactly one official slope_type.h corner bit per named corner. */
        switch (corner) {
            case "N": return GSTile.SLOPE_N
            case "E": return GSTile.SLOPE_E
            case "W": return GSTile.SLOPE_W
            case "S": return GSTile.SLOPE_S
        }
        return null
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
        local min_height = GSTile.GetMinHeight(tile)
        local slope = GSTile.GetSlope(tile)
        /* slope > 31 means a halftile encoding (>= 0x20): native corner
         * heights would be outside the acquirable contract, so fail closed
         * before any corner height can be reported. */
        if (min_height < 0 || min_height > 255 || slope < 0 || slope > 31)
            throw "TERRAIN_NATIVE_FACT"
        local h_n = GSTile.GetCornerHeight(tile, GSTile.CORNER_N)
        local h_e = GSTile.GetCornerHeight(tile, GSTile.CORNER_E)
        local h_s = GSTile.GetCornerHeight(tile, GSTile.CORNER_S)
        local h_w = GSTile.GetCornerHeight(tile, GSTile.CORNER_W)
        if (h_n < 0 || h_n > 255 || h_e < 0 || h_e > 255 ||
            h_s < 0 || h_s > 255 || h_w < 0 || h_w > 255) throw "TERRAIN_NATIVE_FACT"
        r.flags = flags
        r.industry = industry
        r.owner = owner
        r.min_height = min_height
        r.slope = slope
        r.h_n = h_n
        r.h_e = h_e
        r.h_s = h_s
        r.h_w = h_w
        r.funds = GSCompany.GetBankBalance(q.company)
    }

    function TestCost(q, r) {
        local accounting = GSAccounting()
        local testing = GSTestMode()
        local mask = MaskFor(q.corner)
        local ok = null
        if (q.direction == "up") ok = GSTile.RaiseTile(q.tile, mask)
        else ok = GSTile.LowerTile(q.tile, mask)
        r.cost = accounting.GetCosts()
        testing = null
        accounting = null
        return ok
    }

    function CornerDeltaHolds(corner, direction, admitted_heights, reported_heights) {
        /* RAISED/LOWERED host post-check: the commanded corner moved by
         * exactly one step in the commanded direction, every other corner
         * kept its admitted height. */
        local step = direction == "up" ? 1 : -1
        if (reported_heights[corner] != admitted_heights[corner] + step) return false
        foreach (other in ["N", "E", "W", "S"])
            if (other != corner && reported_heights[other] != admitted_heights[other])
                return false
        return true
    }

    function Handle(q) {
        if (typeof q != "table" || q.len() != 9) return
        foreach (k in ["protocol", "op", "request_id", "plan", "company", "tile",
            "corner", "direction", "max_cost"])
            if (!(k in q)) return
        if (q.protocol != 3 || typeof q.op != "string" ||
            (q.op != "inspect" && q.op != "terraform" && q.op != "read") ||
            typeof q.request_id != "string" || q.request_id.len() < 1 ||
            q.request_id.len() > 32 ||
            typeof q.plan != "string" || q.plan.len() != 64) return
        for (local i = 0; i < q.request_id.len(); i++) {
            local c = q.request_id[i]
            if (!(c == 45 || (c >= 48 && c <= 57) || (c >= 97 && c <= 122))) return
        }
        for (local i = 0; i < q.plan.len(); i++) {
            local c = q.plan[i]
            if (!((c >= 48 && c <= 57) || (c >= 97 && c <= 102))) return
        }
        if (typeof q.corner != "string" || q.corner.len() != 1 ||
            !(q.corner == "N" || q.corner == "E" || q.corner == "W" || q.corner == "S"))
            return
        if (typeof q.direction != "string" ||
            !(q.direction == "up" || q.direction == "down")) return
        foreach (k in ["company", "tile", "max_cost"])
            if (typeof q[k] != "integer") return
        if (q.company < 0 || q.company > 14 || q.tile < 0 || q.tile > 65535 ||
            q.max_cost < 0 || q.max_cost > 2147483647) return
        if (used == null) used = {}
        if (attempted == null) attempted = {}
        if (admitted == null) admitted = {}
        if (q.request_id in used || this.requests >= this.max_requests) return
        used[q.request_id] <- true
        this.requests++
        local r = {protocol=3, op=q.op, request_id=q.request_id, plan=q.plan,
            company=q.company, tile=q.tile, corner=q.corner, direction=q.direction,
            status="REJECTED", flags=0, industry=null,
            owner=GSCompany.COMPANY_INVALID, min_height=0, slope=0,
            h_n=0, h_e=0, h_s=0, h_w=0, eligible=false, funds=0, cost=0}
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
                    /* Terraforming needs classified-clear flat-hostable
                     * ground: only a classified CLEAR unowned tile is
                     * eligible; never a road-readiness claim. */
                    r.eligible = cls == "CLEAR" && r.owner == GSCompany.COMPANY_INVALID
                } catch (error) {
                    r.status = "UNSUPPORTED_NATIVE_FACT"
                }
                /* Read-only: pure observation. */
                if (r.status == "UNSUPPORTED_NATIVE_FACT") {
                    /* fail closed, no command */
                } else if (q.op == "read") {
                    r.status = "READ"
                } else if ((q.tile + "-" + q.corner) in attempted) {
                    r.status = "ALREADY_ATTEMPTED"
                } else if (cls != "CLEAR") {
                    /* Trees, buildings, water, transport and unknown
                     * occupancy must be cleared or refused first; there is
                     * no terraforming of an obstructed host here, and no
                     * demolition command in this package. */
                    r.status = "FORBIDDEN_CLASS"
                } else if (r.owner != GSCompany.COMPANY_INVALID) {
                    /* Foreign-owned or protected infrastructure is refused. */
                    r.status = "OWNERSHIP_MISMATCH"
                } else {
                    /* One tested native quote: the exact D2 quote pattern
                     * (GSTestMode around the real command interface). */
                    local quoted = TestCost(q, r)
                    if (!quoted && r.cost <= 0) {
                        /* Zero-cost native refusal: the exact signature of an
                         * already-at-target height, a map-edge refusal, a
                         * native terraform-limit exhaustion or any native
                         * refusal with no effect. Terminal and fail-closed:
                         * no command is issued or authorized from here. */
                        r.status = "NO_OP"
                    } else if (!quoted) {
                        r.status = "REJECTED"
                    } else if (r.cost > q.max_cost) {
                        r.status = "COST_LIMIT"
                    } else if (r.funds < r.cost) {
                        r.status = "INSUFFICIENT_FUNDS"
                    } else if (q.op == "inspect") {
                        r.status = "READY"
                        /* Bind admission facts for the stale-state guard at
                         * execution. The company identity and the plan
                         * identity are bound too: a mutation submitted by
                         * another company or under another plan must never
                         * reuse this admission. */
                        admitted[q.tile + "-" + q.corner] <- {
                            flags = r.flags,
                            industry = r.industry,
                            owner = r.owner,
                            min_height = r.min_height,
                            slope = r.slope,
                            h_n = r.h_n,
                            h_e = r.h_e,
                            h_s = r.h_s,
                            h_w = r.h_w,
                            classification = cls,
                            cost = r.cost,
                            funds = r.funds,
                            plan = q.plan,
                            company = q.company,
                            corner = q.corner,
                            direction = q.direction
                        }
                    } else {

                    /* Execution path: re-observe tile state before the real
                     * command. Neighbor drift since the inspect phase stays
                     * observable to the commanding layer via its independent
                     * verification reads and expectations. */
                    local key = q.tile + "-" + q.corner
                    if (!(key in admitted)) {
                        r.status = "STALE_ADMISSION"
                    } else {
                        local admit = admitted[key]
                        /* The observation table must carry every key that
                         * State() assigns before the re-observation. */
                        local fresh = {flags=0, industry=null, owner=GSCompany.COMPANY_INVALID,
                            min_height=0, slope=0, h_n=0, h_e=0, h_s=0, h_w=0,
                            funds=0, classification="UNKNOWN"}
                        try {
                            State(q, fresh)
                            fresh.classification = Classify(fresh.flags, fresh.industry)
                        } catch (error) {
                            fresh = null
                        }
                        if (fresh == null) {
                            r.status = "UNSUPPORTED_NATIVE_FACT"
                        } else if (q.plan != admit.plan ||
                            q.company != admit.company ||
                            q.corner != admit.corner ||
                            q.direction != admit.direction ||
                            fresh.flags != admit.flags ||
                            fresh.industry != admit.industry ||
                            fresh.owner != admit.owner ||
                            fresh.min_height != admit.min_height ||
                            fresh.slope != admit.slope ||
                            fresh.h_n != admit.h_n ||
                            fresh.h_e != admit.h_e ||
                            fresh.h_s != admit.h_s ||
                            fresh.h_w != admit.h_w ||
                            fresh.classification != admit.classification) {
                            r.status = "STALE_ADMISSION"
                        } else if (fresh.classification != "CLEAR") {
                            r.status = "FORBIDDEN_CLASS"
                        } else if (fresh.owner != GSCompany.COMPANY_INVALID) {
                            r.status = "OWNERSHIP_MISMATCH"
                        } else {
                            /* Latch before the real command, including a
                             * rejected native command: one corner op runs at
                             * most once, ever. */
                            attempted[key] <- true
                            local accounting = GSAccounting()
                            local mask = MaskFor(q.corner)
                            local ok = null
                            if (q.direction == "up") ok = GSTile.RaiseTile(q.tile, mask)
                            else ok = GSTile.LowerTile(q.tile, mask)
                            r.cost = accounting.GetCosts()
                            accounting = null
                            /* Post-execution readback for receipt
                             * verification; whatever state the world holds
                             * after a failed command is reported as seen,
                             * never as unchanged. */
                            local geometry_ok = false
                            try {
                                State(q, r)
                            } catch (error) {
                                r.status = "UNSUPPORTED_NATIVE_FACT"
                            }
                            if (r.status != "UNSUPPORTED_NATIVE_FACT") {
                                local cls2 = Classify(r.flags, r.industry)
                                local admitted_heights =
                                    {N=admit.h_n, E=admit.h_e, W=admit.h_w, S=admit.h_s}
                                local reported_heights = {N=r.h_n, E=r.h_e, W=r.h_w, S=r.h_s}
                                /* The written corner moves the tile minimum
                                 * by at most one step in the commanded
                                 * direction: raising the last minimum corner
                                 * raises the tile minimum, lowering the sole
                                 * minimum corner lowers it. */
                                geometry_ok = q.direction == "up"
                                    ? (r.min_height == admit.min_height ||
                                       r.min_height == admit.min_height + 1)
                                    : (r.min_height == admit.min_height ||
                                       r.min_height == admit.min_height - 1)
                                if (!ok) {
                                    /* Native refusal: uncertainty preserved. */
                                    r.status = "REJECTED"
                                } else if (cls2 == "CLEAR" &&
                                        r.owner == GSCompany.COMPANY_INVALID &&
                                        geometry_ok &&
                                        CornerDeltaHolds(q.corner, q.direction,
                                            admitted_heights, reported_heights)) {
                                    r.status = q.direction == "up" ? "RAISED" : "LOWERED"
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
        }
        // These numeric and ASCII bounds keep even the largest response below 512 bytes.
        if (r.funds < -2147483648 || r.funds > 2147483647 || r.cost < 0 ||
            r.cost > 2147483647 || r.flags < 0 || r.flags > 32767 ||
            r.min_height < 0 || r.min_height > 255 || r.slope < 0 || r.slope > 31 ||
            r.h_n < 0 || r.h_n > 255 || r.h_e < 0 || r.h_e > 255 ||
            r.h_s < 0 || r.h_s > 255 || r.h_w < 0 || r.h_w > 255 ||
            r.owner < -1 || r.owner > 14) throw "TERRAIN_RESPONSE_OUT_OF_BOUNDS"
        if (!GSAdmin.Send(r)) throw "TERRAIN_RESPONSE_SEND_FAILED"
        GSLog.Info("TERRAFORM_RESPONSE " + q.request_id + " " + r.status)
    }

    function Start() {
        GSLog.Info("TERRAFORM_READY")
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
class NetworkFreightProof extends TerrainTerraformProof {
}
