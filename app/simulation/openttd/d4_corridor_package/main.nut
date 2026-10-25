/* Separate bounded native corridor-construction handler. Additive: no existing
 * frozen package is modified or imported. The only native mutation commands
 * are GSRoad.BuildRoadFull, GSRoad.BuildRoad, GSRoad.BuildRoadStation and
 * GSRoad.BuildRoadDepot in company mode, each executed at most once against
 * its baked staged pins; demolition, terraforming, rail, dock, airport and
 * vehicle commands are absent by construction. Classification and vacancy
 * predicates are identical to the proven classification bridge and the
 * fixed-demo infrastructure pattern, evaluated fully by the classification
 * path so an incomplete read is impossible by design.
 *
 * Every op runs one fixed-demo exchange group: one inspected native quote
 * (GSTestMode) latched into a plan-bound admission table, one real command
 * behind an equal re-quote, one independent readback. A BUILT status asserts
 * only the observed post-command state (endpoint ownership/road flags and the
 * run coverage/pair summary, or the exact stop/depot footprint vs its front).
 * No failed command is ever reported as leaving the world unchanged: a failed
 * road command may still have built pieces, and the phase evidence keeps the
 * world state explicitly uncertain.
 *
 * Scripted BuildRoadFull builds both straight road bits at both span
 * endpoints, so the two collinear run-B segments auto-connect. Only the
 * perpendicular corner between the two straight runs needs its own
 * BuildRoad op, with both endpoints already company road and the pair not
 * yet connected. The geometry stays two straight runs joined by one corner;
 * that join is a build operation, not a second corner.
 *
 * Wire contract v4 mirrors the proven identity style: command requests carry
 * the prelaunch seal the inspect latched; independent reads are intent-scoped
 * and carry the CorridorIntent digest. Tile bounds are 256x256-safe (pins
 * bounded 0..65535) so the historical 64x64 road contracts' window never
 * limits this corridor.-road */
class D4CorridorProof extends GSController {
    attempted = null
    admitted = null
    used = null
    /* Progress state: the schedule has seven staged ops; `stage` is the index
     * of the one whose exchange group may run next. `halted` stops every op
     * after any command exchange failed to reach BUILT: schedule evidence is
     * prefix-preserving and no op is ever reordered or retried. */
    stage = 0
    halted = false
    /* One-shot dispatcher budget accounting. */
    requests = 0
    /* Baked staged pins of the sealed D4 corridor schedule (mirrored by the
     * Python staging module's split-run-B derivation): pickup stop 45748 on
     * the front run-A tile 45747; run A 45747..45743, then the compiled run B
     * staged as its two contiguous collinear segments 45999..48047 and
     * 48303..50095 (x 175, y 179..195), which auto-connect at 48047-48303
     * because BuildRoadFull gives both straight bits at span endpoints;
     * then the run A end 45743 corners to the run B start 45999 (its own
     * perpendicular join op); delivery stop 50351 on the front run-B tile
     * 50095; and the depot 45487 fronts the run A end 45743. Full runs are
     * straight spans within the Python contract's MAX_FULL_SPAN bound of 36
     * delta steps. */
    PICKUP = 45748
    PICKUP_FRONT = 45747
    DELIVERY = 50351
    DELIVERY_FRONT = 50095
    DEPOT_TILE = 45487
    DEPOT_FRONT = 45743
    MAX_RUN = 36
    /* 7 x 3 planned exchanges + 1 route read = 22, plus 6 slack, so request
     * 29 is the first one the dispatcher refuses. */
    max_requests = 28

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

    function Vacant(t) {
        /* Identical predicate set to the fixed-demo road infrastructure:
         * buildable, slopeless, unowned, no water/coast/tree/farm/rock/rough
         * and no existing transport of any kind. */
        return GSTile.IsBuildable(t) && GSTile.GetSlope(t) == 0 &&
            GSTile.GetOwner(t) == GSCompany.COMPANY_INVALID &&
            !GSTile.IsWaterTile(t) && !GSTile.IsCoastTile(t) &&
            !GSTile.HasTreeOnTile(t) && !GSTile.IsFarmTile(t) &&
            !GSTile.IsRockTile(t) && !GSTile.IsRoughTile(t) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_ROAD) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_RAIL) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_WATER) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_AIR)
    }

    function Linked(a, b) {
        return GSRoad.AreRoadTilesConnected(a, b) && GSRoad.AreRoadTilesConnected(b, a)
    }

    function ShapeKey(kind, a, b) {
        local lo = a
        local hi = b
        if (lo > hi) {
            lo = b
            hi = a
        }
        return kind + "-" + lo + "-" + hi
    }

    function KindKey(kind, tile) {
        return kind + "-" + tile
    }

    /* The baked staged schedule keys in execution order: run A, both run-B
     * segments (collinear, auto-connected by full-build endpoint bits), the
     * perpendicular corner road join, both stops, the depot. */
    function StageIndex(key) {
        local stages = [ShapeKey("full", 45747, 45743),
                        ShapeKey("full", 45999, 48047),
                        ShapeKey("full", 48303, 50095),
                        ShapeKey("road", 45743, 45999),
                        KindKey("station", 45748),
                        KindKey("station", 50351),
                        KindKey("depot", 45487)]
        for (local i = 0; i < 7; i++)
            if (key == stages[i]) return i
        return -1
    }

    /* Straight inclusive walk observation between two map tiles; any walk the
     * contract cannot carry is a native fact exception. */
    function ObserveRoad(a, b, company) {
        local wx = GSMap.GetMapSizeX()
        local dx = (b % wx) - (a % wx)
        local dy = (b / wx) - (a / wx)
        local span = dx == 0 ? (dy < 0 ? -dy : dy) : (dx < 0 ? -dx : dx)
        if ((dx != 0 && dy != 0) || span < 1 || span > MAX_RUN) throw "D4_NATIVE_FACT"
        local step = dx == 0 ? wx * (dy < 0 ? -1 : 1) : (dx < 0 ? -1 : 1)
        local count = span + 1
        local covered = 0
        local pairs_ok = 0
        local tile = a
        for (local i = 0; i < count; i++) {
            if (!GSMap.IsValidTile(tile) ||
                GSMap.GetTileX(tile) != tile % wx ||
                GSMap.GetTileY(tile) != tile / wx) throw "D4_NATIVE_FACT"
            if (GSRoad.IsRoadTile(tile)) covered++
            if (i > 0 && Linked(tile - step, tile)) pairs_ok++
            tile += step
        }
        return {
            owner0 = GSTile.GetOwner(a),
            owner1 = GSTile.GetOwner(b),
            road0 = GSRoad.IsRoadTile(a),
            road1 = GSRoad.IsRoadTile(b),
            run_len = count,
            covered = covered,
            pairs_ok = pairs_ok,
            pair_total = count - 1,
            funds = GSCompany.GetBankBalance(company)
        }
    }

    /* Site observation for one stop/depot tile with its pinned front; every
     * field is a native fact, no planned-world assertion is folded in. */
    function ObserveSite(tile, front, company) {
        local wx = GSMap.GetMapSizeX()
        if (!GSMap.IsValidTile(tile) || GSMap.GetTileX(tile) != tile % wx ||
            GSMap.GetTileY(tile) != tile / wx) throw "D4_NATIVE_FACT"
        if (!GSMap.IsValidTile(front) || GSMap.GetTileX(front) != front % wx ||
            GSMap.GetTileY(front) != front / wx) throw "D4_NATIVE_FACT"
        local stop = GSRoad.IsRoadStationTile(tile)
        local drive_through = stop && GSRoad.IsDriveThroughRoadStationTile(tile)
        local sid = stop ? GSStation.GetStationID(tile) : -1
        local truck = stop && !drive_through && GSStation.IsValidStation(sid) &&
            GSStation.HasStationType(sid, GSStation.STATION_TRUCK_STOP) &&
            !GSStation.HasStationType(sid, GSStation.STATION_BUS_STOP)
        local depot = GSRoad.IsRoadDepotTile(tile)
        local front_owner = GSTile.GetOwner(front)
        local linked = stop && GSStation.IsValidStation(sid) &&
            !drive_through && GSRoad.GetRoadStationFrontTile(tile) == front
        local depot_front_id = depot ? GSRoad.GetRoadDepotFrontTile(tile) : -1
        local depot_linked = depot && depot_front_id == front &&
            front_owner == company && GSRoad.IsRoadTile(front)
        return {
            stop = stop,
            drive_through = drive_through,
            truck = truck,
            sid = sid,
            stop_owner = GSTile.GetOwner(tile),
            front_owner = front_owner,
            linked = linked,
            depot = depot,
            depot_front_id = depot_front_id,
            depot_linked = depot_linked,
            stop_min_height = GSTile.GetMinHeight(tile),
            stop_slope = GSTile.GetSlope(tile),
            front_min_height = GSTile.GetMinHeight(front),
            front_slope = GSTile.GetSlope(front),
            funds = GSCompany.GetBankBalance(company)
        }
    }

    /* One tested native quote: the exact fixed-demo test-mode pattern. */
    function Quote(kind, q) {
        local accounting = GSAccounting()
        local testing = GSTestMode()
        local ok = RunCommand(kind, q)
        local cost = accounting.GetCosts()
        testing = null
        accounting = null
        return [ok, cost]
    }

    /* The single native build command of one op kind, pinned from its own
     * request shape only (the wire omits inapplicable keys entirely). */
    function RunCommand(kind, q) {
        if (kind == "full") return GSRoad.BuildRoadFull(q.start, q.end)
        if (kind == "road") return GSRoad.BuildRoad(q.start, q.end)
        if (kind == "station")
            return GSRoad.BuildRoadStation(q.tile, q.front, GSRoad.ROADVEHTYPE_TRUCK,
                GSStation.STATION_NEW)
        return GSRoad.BuildRoadDepot(q.tile, q.front)
    }

    /* The op kind's factual eligibility verdict on the current world state:
     * roadless unowned ground for a full run, company road on both corner
     * endpoints with no existing link for the corner piece, unplanned ground
     * fronting this company road for a stop/depot. Never a claim that a build
     * will succeed: the native quote decides buildability. */
    function Eligible(kind, company, obs) {
        if (kind == "full")
            return obs.owner0 == GSCompany.COMPANY_INVALID &&
                obs.owner1 == GSCompany.COMPANY_INVALID &&
                obs.road0 == false && obs.road1 == false &&
                obs.covered == 0 && obs.pairs_ok == 0
        if (kind == "road")
            return obs.owner0 == company && obs.owner1 == company &&
                obs.road0 == true && obs.road1 == true &&
                obs.covered == obs.run_len && obs.pairs_ok == 0
        local unplanned = obs.stop_owner == GSCompany.COMPANY_INVALID &&
            Vacant(kind == "station" ? obs.stop_tile : obs.depot_tile)
        if (kind == "station")
            return unplanned && !obs.stop && !obs.drive_through &&
                !obs.truck && obs.depot == false
        return unplanned && !obs.depot && !obs.depot_linked
    }

    /* The post-command structural verdict of one op kind's observation. The
     * front pin is read only where the op carries one (site ops). */
    function PostHolds(kind, company, q, obs) {
        if (kind == "full" || kind == "road")
            return obs.owner0 == company && obs.owner1 == company &&
                obs.road0 == true && obs.road1 == true &&
                obs.covered == obs.run_len &&
                obs.pairs_ok == obs.pair_total &&
                obs.pair_total == obs.run_len - 1
        if (kind == "station")
            return obs.stop == true && obs.drive_through == false &&
                obs.truck == true && obs.sid >= 0 &&
                obs.stop_owner == company && obs.front_owner == company &&
                obs.linked == true && obs.depot == false
        return obs.depot == true && obs.depot_front_id == q.front &&
            obs.depot_linked == true && obs.front_owner == company &&
            obs.stop == false && obs.truck == false
    }

    /* Corridor route observation: every adjacent pair along the ordered path
     * must be joined by this company's road (stops attach through their
     * fronts); stop facts are reported for the path's own endpoints and the
     * depot pin is observed at the baked depot pin. Pure observation: no
     * quote, no command, cost always 0. */
    function ObserveRoute(q, r) {
        local path = q.tiles
        local pairs = path.len() - 1
        local connected = 0
        local fail = -1
        for (local i = 0; i < pairs; i++) {
            local a = path[i]
            local b = path[i + 1]
            local joined = Linked(a, b) && GSTile.GetOwner(a) == q.company &&
                GSTile.GetOwner(b) == q.company
            if (joined) connected++
            else if (fail < 0) fail = i
        }
        r.connected_pairs <- connected
        r.first_fail <- fail
        local head = path[0]
        local head_stop = GSRoad.IsRoadStationTile(head)
        local head_sid = head_stop ? GSStation.GetStationID(head) : -1
        r.pickup_stop <- head_stop
        r.pickup_truck <- head_stop && !GSRoad.IsDriveThroughRoadStationTile(head) &&
            GSStation.IsValidStation(head_sid) &&
            GSStation.HasStationType(head_sid, GSStation.STATION_TRUCK_STOP) &&
            !GSStation.HasStationType(head_sid, GSStation.STATION_BUS_STOP)
        r.pickup_sid <- head_sid
        local tail = path[path.len() - 1]
        local tail_stop = GSRoad.IsRoadStationTile(tail)
        local tail_sid = tail_stop ? GSStation.GetStationID(tail) : -1
        r.delivery_stop <- tail_stop
        r.delivery_truck <- tail_stop && !GSRoad.IsDriveThroughRoadStationTile(tail) &&
            GSStation.IsValidStation(tail_sid) &&
            GSStation.HasStationType(tail_sid, GSStation.STATION_TRUCK_STOP) &&
            !GSStation.HasStationType(tail_sid, GSStation.STATION_BUS_STOP)
        r.delivery_sid <- tail_sid
        r.depot_pin_ok <- GSRoad.IsRoadDepotTile(DEPOT_TILE) &&
            GSRoad.GetRoadDepotFrontTile(DEPOT_TILE) == DEPOT_FRONT &&
            GSTile.GetOwner(DEPOT_TILE) == q.company
        r.funds = GSCompany.GetBankBalance(q.company)
        r.eligible = connected == pairs && fail == -1 &&
            r.pickup_stop == true && r.pickup_truck == true &&
            r.delivery_stop == true && r.delivery_truck == true &&
            r.depot_pin_ok == true
        r.status = "READ"
    }

    /* Contract observation fills: only the reply's own contract fields, in
     * the shapes `ObserveRoad`/`ObserveSite` return. The Step-injected
     * vacancy keys and the bank balance never join the reply table. */
    function FillRoad(r, obs) {
        r.owner0 <- obs.owner0
        r.owner1 <- obs.owner1
        r.road0 <- obs.road0
        r.road1 <- obs.road1
        r.run_len <- obs.run_len
        r.covered <- obs.covered
        r.pairs_ok <- obs.pairs_ok
        r.pair_total <- obs.pair_total
    }

    function FillSite(r, obs) {
        r.stop <- obs.stop
        r.drive_through <- obs.drive_through
        r.truck <- obs.truck
        r.stop_owner <- obs.stop_owner
        r.front_owner <- obs.front_owner
        r.depot <- obs.depot
        r.depot_linked <- obs.depot_linked
        r.stop_min_height <- obs.stop_min_height
        r.stop_slope <- obs.stop_slope
        r.front_min_height <- obs.front_min_height
        r.front_slope <- obs.front_slope
        /* Only the applicable id/linkage fields join the reply: the absent
         * slot parses to the contract's None default, which the admission
         * rules accept exactly like a reported -1, and the depot replies
         * omit `linked` (definitionally false, read by no depot rule). */
        if (obs.stop) r.sid <- obs.sid
        if (obs.depot == false) r.linked <- obs.linked
        if (obs.depot) r.depot_front_id <- obs.depot_front_id
    }

    /* Admission/execution flow for one staged op kind. */
    function Step(q, r, kind, key, company) {
        local on_road = kind == "full" || kind == "road"
        local obs = null
        try {
            obs = on_road ? ObserveRoad(q.start, q.end, company)
                          : ObserveSite(q.tile, q.front, company)
            if (on_road) FillRoad(r, obs)
            else {
                obs.stop_tile <- q.tile
                obs.depot_tile <- q.tile
                FillSite(r, obs)
            }
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
            return
        }
        r.eligible = Eligible(kind, company, obs)
        local funds = obs.funds
        r.funds = funds
        if (q.op == "read") {
            r.status = "READ"
            return
        }
        local idx = StageIndex(key)
        if (key in attempted) {
            r.status = "ALREADY_ATTEMPTED"
        } else if (idx != stage || halted) {
            r.status = "OUT_OF_ORDER"
        } else if (q.op == "inspect") {
            if (!r.eligible) {
                r.status = "NOT_BUILDABLE"
            } else {
                local quote = Quote(kind, q)
                /* By the contract a READY admission carries its positive
                 * tested cost in the reply itself (the Python side refuses a
                 * zero-cost quote before any command can be dispatched). */
                r.cost = quote[1]
                if (!quote[0] || quote[1] <= 0) {
                    r.status = "REJECTED"
                } else if (quote[1] > q.max_cost) {
                    r.status = "COST_LIMIT"
                } else if (funds < quote[1]) {
                    r.status = "INSUFFICIENT_FUNDS"
                } else {
                    r.status = "READY"
                    admitted[key] <- {plan=q.plan, company=q.company,
                        max_cost=q.max_cost, kind=kind, cost=quote[1]}
                    if (on_road) {
                        admitted[key].owner0 <- obs.owner0
                        admitted[key].owner1 <- obs.owner1
                        admitted[key].road0 <- obs.road0
                        admitted[key].road1 <- obs.road1
                        admitted[key].run_len <- obs.run_len
                        admitted[key].covered <- obs.covered
                        admitted[key].pairs_ok <- obs.pairs_ok
                        admitted[key].pair_total <- obs.pair_total
                    } else {
                        admitted[key].stop <- obs.stop
                        admitted[key].drive_through <- obs.drive_through
                        admitted[key].truck <- obs.truck
                        admitted[key].sid <- obs.sid
                        admitted[key].stop_owner <- obs.stop_owner
                        admitted[key].front_owner <- obs.front_owner
                        admitted[key].linked <- obs.linked
                        admitted[key].depot <- obs.depot
                        admitted[key].depot_front_id <- obs.depot_front_id
                        admitted[key].depot_linked <- obs.depot_linked
                        admitted[key].stop_min_height <- obs.stop_min_height
                        admitted[key].stop_slope <- obs.stop_slope
                        admitted[key].front_min_height <- obs.front_min_height
                        admitted[key].front_slope <- obs.front_slope
                    }
                }
            }
        } else {
            /* Command op: the staged execution behind a plan-bound
             * admission, a fresh re-observation and an equal re-quote. */
            if (!(key in admitted)) {
                r.status = "STALE_ADMISSION"
            } else {
                local admit = admitted[key]
                local drifted = q.plan != admit.plan || q.company != admit.company ||
                    q.max_cost != admit.max_cost ||
                    r.eligible == false
                if (on_road) {
                    drifted = drifted || r.owner0 != admit.owner0 ||
                        r.owner1 != admit.owner1 || r.road0 != admit.road0 ||
                        r.road1 != admit.road1 || r.run_len != admit.run_len ||
                        r.covered != admit.covered ||
                        r.pairs_ok != admit.pairs_ok ||
                        r.pair_total != admit.pair_total
                } else {
                    /* The sid/depot_front_id slots only exist where their
                     * structure exists; an absent slot is the reported -1. */
                    local post_sid = "sid" in r ? r.sid : -1
                    local post_front_id = "depot_front_id" in r ? r.depot_front_id : -1
                    drifted = drifted || r.stop != admit.stop ||
                        r.drive_through != admit.drive_through ||
                        r.truck != admit.truck || post_sid != admit.sid ||
                        r.stop_owner != admit.stop_owner ||
                        r.front_owner != admit.front_owner ||
                        r.linked != admit.linked || r.depot != admit.depot ||
                        post_front_id != admit.depot_front_id ||
                        r.depot_linked != admit.depot_linked ||
                        r.stop_min_height != admit.stop_min_height ||
                        r.stop_slope != admit.stop_slope ||
                        r.front_min_height != admit.front_min_height ||
                        r.front_slope != admit.front_slope
                }
                if (drifted) {
                    r.status = "STALE_ADMISSION"
                } else {
                    local quote = Quote(kind, q)
                    if (!quote[0] || quote[1] <= 0) {
                        r.status = "REJECTED"
                    } else if (quote[1] != admit.cost) {
                        r.status = "COST_CHANGED"
                    } else if (funds < admit.cost) {
                        r.status = "INSUFFICIENT_FUNDS"
                    } else {
                        /* Latch before the real command, including a
                         * rejected native command: one op runs at most
                         * once, ever. */
                        attempted[key] <- true
                        local accounting = GSAccounting()
                        local ok = RunCommand(kind, q)
                        r.cost = accounting.GetCosts()
                        accounting = null
                        /* Post-execution observation; whatever state the
                         * world holds after a failed command is reported
                         * as seen, never as unchanged. */
                        local post = null
                        local native_fact_ok = true
                        try {
                            post = on_road ? ObserveRoad(q.start, q.end, company)
                                           : ObserveSite(q.tile, q.front, company)
                            if (on_road) FillRoad(r, post)
                            else FillSite(r, post)
                        } catch (error) {
                            native_fact_ok = false
                        }
                        if (!native_fact_ok) {
                            r.status = "UNSUPPORTED_NATIVE_FACT"
                        } else {
                            r.funds = post.funds
                            r.eligible = PostHolds(kind, company, q, post)
                            if (!ok) {
                                /* Native refusal: uncertainty preserved. */
                                r.status = "REJECTED"
                            } else if (r.cost != admit.cost ||
                                       funds - r.funds != r.cost ||
                                       !PostHolds(kind, company, q, post)) {
                                r.status = "READBACK_MISMATCH"
                            } else {
                                r.status = "BUILT"
                                stage++
                            }
                        }
                    }
                }
            }
            if (r.status != "BUILT") halted = true
        }
    }

    /* Corridor route observation entry for pure-read dispatch. */
    function Route(q, r) {
        foreach (t in q.tiles)
            if (!GSMap.IsValidTile(t) ||
                GSMap.GetTileX(t) != t % GSMap.GetMapSizeX() ||
                GSMap.GetTileY(t) != t / GSMap.GetMapSizeX()) {
                r.status = "INVALID_LOCATION"
                return
            }
        ObserveRoute(q, r)
    }

    function Handle(q) {
        if (typeof q != "table") return
        if (!("protocol" in q) || q.protocol != 4) return
        if (!("op" in q) || typeof q.op != "string" ||
            !(q.op == "inspect" || q.op == "read" || q.op == "route" ||
              q.op == "full" || q.op == "road" || q.op == "station" ||
              q.op == "depot")) return
        if (!("request_id" in q) || typeof q.request_id != "string" ||
            q.request_id.len() < 1 || q.request_id.len() > 32) return
        if (!("plan" in q) || typeof q.plan != "string" || q.plan.len() != 64) return
        for (local i = 0; i < q.request_id.len(); i++) {
            local c = q.request_id[i]
            if (!(c == 45 || (c >= 48 && c <= 57) || (c >= 97 && c <= 122))) return
        }
        for (local i = 0; i < q.plan.len(); i++) {
            local c = q.plan[i]
            if (!((c >= 48 && c <= 57) || (c >= 97 && c <= 102))) return
        }
        if (typeof q.company != "integer" || q.company < 0 || q.company > 14) return
        if (typeof q.max_cost != "integer" || q.max_cost < 0 ||
            q.max_cost > 2147483647) return
        /* Reserved shapes must never appear where the op shape excludes them,
         * and each op shape always supplies exactly its own pins. Command ops
         * must be direct spans/pins bounded like the Python contract. */
        local op = q.op
        if (op == "inspect" || op == "read") {
            if (!("target" in q) || typeof q.target != "string" ||
                !(q.target == "full" || q.target == "road" ||
                  q.target == "station" || q.target == "depot")) return
            local kind = q.target
            if (kind == "full" || kind == "road") {
                if (!("start" in q) || !("end" in q) || "tile" in q ||
                    "front" in q || "tiles" in q) return
                if (typeof q.start != "integer" || typeof q.end != "integer" ||
                    q.start < 0 || q.start > 65535 || q.end < 0 ||
                    q.end > 65535) return
                local wx = GSMap.GetMapSizeX()
                local dx = abs_int(q.start % wx - q.end % wx)
                local dy = abs_int(q.start / wx - q.end / wx)
                if (kind == "full"
                        ? (dx != 0 && dy != 0) || dx + dy < 1 || dx + dy > 36
                        : dx + dy != 1) return
            } else {
                if (!("tile" in q) || !("front" in q) || "start" in q ||
                    "end" in q || "tiles" in q) return
                if (typeof q.tile != "integer" || typeof q.front != "integer" ||
                    q.tile < 0 || q.tile > 65535 || q.front < 0 ||
                    q.front > 65535) return
                if (adjacent(q.tile, q.front) != true) return
            }
        } else if (op == "full" || op == "road") {
            if ("target" in q || "tile" in q || "front" in q || "tiles" in q) return
            if (!("start" in q) || !("end" in q) ||
                typeof q.start != "integer" || typeof q.end != "integer" ||
                q.start < 0 || q.start > 65535 || q.end < 0 ||
                q.end > 65535) return
            local wx = GSMap.GetMapSizeX()
            local dx = abs_int(q.start % wx - q.end % wx)
            local dy = abs_int(q.start / wx - q.end / wx)
            if (op == "full"
                    ? (dx != 0 && dy != 0) || dx + dy < 1 || dx + dy > 36
                    : dx + dy != 1) return
        } else if (op == "station" || op == "depot") {
            if ("target" in q || "start" in q || "end" in q || "tiles" in q) return
            if (!("tile" in q) || !("front" in q) ||
                typeof q.tile != "integer" || typeof q.front != "integer" ||
                q.tile < 0 || q.tile > 65535 || q.front < 0 ||
                q.front > 65535) return
            if (adjacent(q.tile, q.front) != true) return
        } else {
            if ("target" in q || "start" in q || "end" in q || "tile" in q ||
                "front" in q) return
            if (!("tiles" in q) || typeof q.tiles != "array" ||
                q.tiles.len() < 2 || q.tiles.len() > 48) return
            foreach (t in q.tiles)
                if (typeof t != "integer" || t < 0 || t > 65535) return
            if (q.tiles[0] == q.tiles[q.tiles.len() - 1]) return
            for (local i = 1; i < q.tiles.len(); i++)
                if (adjacent(q.tiles[i - 1], q.tiles[i]) != true) return
        }
        if (used == null) used = {}
        if (attempted == null) attempted = {}
        if (admitted == null) admitted = {}
        if (q.request_id in used || this.requests >= this.max_requests) return
        used[q.request_id] <- true
        this.requests++
        /* Base response: every contract-required key (the correlation set
         * echoes as-is; null stands for the pins the op does not carry);
         * optional observation fields are created only for their op kind. */
        local r = {protocol=4, op=q.op, request_id=q.request_id, plan=q.plan,
            company=q.company, max_cost=q.max_cost, target=null,
            start=null, end=null, tile=null, front=null, tiles=null,
            status="REJECTED", eligible=false, funds=0, cost=0}
        if ("target" in q) r.target = q.target
        if ("start" in q) {
            r.start = q.start
            r.end = q.end
        }
        if ("tile" in q) {
            r.tile = q.tile
            r.front = q.front
        }
        if ("tiles" in q) r.tiles = q.tiles
        if (GSCompany.ResolveCompanyID(q.company) != q.company) {
            r.status = "INVALID_COMPANY"
        } else if (op == "route") {
            /* Route reads are pure observation of the ordered corridor
             * witness path: no company mode, no quote, no command. */
            Route(q, r)
        } else {
            local map_ok = true
            foreach (pin in PinsOf(q))
                if (!GSMap.IsValidTile(pin) ||
                    GSMap.GetTileX(pin) != pin % GSMap.GetMapSizeX() ||
                    GSMap.GetTileY(pin) != pin / GSMap.GetMapSizeX()) map_ok = false
            if (map_ok) {
                local kind = op == "inspect" || op == "read" ? q.target : q.op
                local key = kind == "full" || kind == "road"
                    ? ShapeKey(kind, q.start, q.end)
                    : KindKey(kind, q.tile)
                local company = GSCompanyMode(q.company)
                if (!GSCompanyMode.IsValid()) {
                    r.status = "INVALID_COMPANY"
                } else {
                    GSRoad.SetCurrentRoadType(GSRoad.ROADTYPE_ROAD)
                    if (GSRoad.GetCurrentRoadType() != 0 ||
                        !GSRoad.IsRoadTypeAvailable(0)) {
                        r.status = "UNSUPPORTED_NATIVE_FACT"
                    } else {
                        Step(q, r, kind, key, q.company)
                    }
                }
                company = null
            } else {
                r.status = "INVALID_LOCATION"
            }
        }
        Guard(r)
        if (!GSAdmin.Send(r)) throw "D4_RESPONSE_SEND_FAILED"
        GSLog.Info("D4_RESPONSE " + q.request_id + " " + r.status)
    }

    function PinsOf(q) {
        local out = []
        if ("start" in q) {
            out.append(q.start)
            out.append(q.end)
        }
        if ("tile" in q) {
            out.append(q.tile)
            out.append(q.front)
        }
        return out
    }

    function adjacent(a, b) {
        local wx = GSMap.GetMapSizeX()
        local dx = a % wx > b % wx ? a % wx - b % wx : b % wx - a % wx
        local dy = a / wx > b / wx ? a / wx - b / wx : b / wx - a / wx
        return dx + dy == 1
    }

    function abs_int(v) {
        return v < 0 ? -v : v
    }

    /* Numeric bounds keep even the largest response honest and small; the
     * final route read binds below the D4 contract's 640-byte response gate
     * (its 24-tile witness echo is the largest allowed reply). They mirror
     * the CorridorReadback field bounds exactly. */
    function Guard(r) {
        if (r.funds < -2147483648 || r.funds > 2147483647 || r.cost < 0 ||
            r.cost > 2147483647) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("owner0" in r && (r.owner0 < -1 || r.owner0 > 14)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("owner1" in r && (r.owner1 < -1 || r.owner1 > 14)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("run_len" in r && (r.run_len < 0 || r.run_len > 48)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("covered" in r && (r.covered < 0 || r.covered > 48)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("pairs_ok" in r && (r.pairs_ok < 0 || r.pairs_ok > 48)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("pair_total" in r && (r.pair_total < 0 || r.pair_total > 48)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("sid" in r && (r.sid < -1 || r.sid > 1073741824)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("stop_owner" in r && (r.stop_owner < -1 || r.stop_owner > 14)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("front_owner" in r && (r.front_owner < -1 || r.front_owner > 14)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("depot_front_id" in r && (r.depot_front_id < -1 || r.depot_front_id > 1073741824))
            throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("stop_min_height" in r && (r.stop_min_height < 0 || r.stop_min_height > 255))
            throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("stop_slope" in r && (r.stop_slope < 0 || r.stop_slope > 31)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("front_min_height" in r && (r.front_min_height < 0 || r.front_min_height > 255))
            throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("front_slope" in r && (r.front_slope < 0 || r.front_slope > 31)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("connected_pairs" in r && (r.connected_pairs < 0 || r.connected_pairs > 48))
            throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("first_fail" in r && (r.first_fail < -1 || r.first_fail > 48)) throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("pickup_sid" in r && (r.pickup_sid < -1 || r.pickup_sid > 1073741824))
            throw "D4_RESPONSE_OUT_OF_BOUNDS"
        if ("delivery_sid" in r && (r.delivery_sid < -1 || r.delivery_sid > 1073741824))
            throw "D4_RESPONSE_OUT_OF_BOUNDS"
    }

    function Start() {
        GSLog.Info("D4_READY")
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
class NetworkFreightProof extends D4CorridorProof {
}
