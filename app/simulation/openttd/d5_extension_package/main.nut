/* Separate bounded native corridor-extension handler (the D5 branch package).
 * Additive: no existing frozen package is modified or imported, and the proven
 * D4 corridor is never rebuilt, reordered or touched by this handler. The
 * only native mutation commands are GSRoad.BuildRoadFull, GSRoad.BuildRoad
 * and GSRoad.BuildRoadStation in company mode, each executed at most once
 * against its baked staged pins; there is no depot op in this schedule, and
 * demolition, terraforming, rail, dock, airport and vehicle commands are
 * absent by construction. There is no acceptance or survey logic here either:
 * the acceptance recheck is a separate read-only survey session. Classification
 * and vacancy predicates are identical to the proven classification bridge and
 * the fixed-demo infrastructure pattern, evaluated fully by the classification
 * path so an incomplete read is impossible by design.
 *
 * Every op runs one fixed-demo exchange group: one inspected native quote
 * (GSTestMode) latched into a plan-bound admission table, one real command
 * behind an equal re-quote, one independent readback. A BUILT status asserts
 * only the observed post-command state (endpoint ownership/road flags and the
 * run coverage/pair summary, or the exact stop footprint vs its front).
 * No failed command is ever reported as leaving the world unchanged: a failed
 * road command may still have built pieces, and the phase evidence keeps the
 * world state explicitly uncertain.
 *
 * The extension is a south branch of the built D4 corridor at the delivery
 * front: the D4-after-layer town census graded the stop 50351 catchment
 * tiles to the south as vacant unowned roadless flat ground — but the
 * halted D5-CORRIDOR-EXTENSION-1 attempt proved that grade stale for the
 * delivery edge: the D3 terraforming raised the terrace corner points
 * (175..176, 190..197) and the delivered world holds native slopes at
 * 50607 (slope 9) and — after the branch road built — its front 50608
 * (slope 8), so tile 50607 is NOT buildable stop ground and never was in
 * the graded census. The recovery therefore moves the branch stop two
 * rows south, outside the raised terrace's corner influence: a vertical
 * full run east of the delivery front (50096..50608..50864, tile =
 * y*256 + x on the 256x256 Seed-17 map) builds the branch road; the
 * horizontal join 50095-50096 then ties the branch head to the delivery
 * front's existing company road. The v2 design (postmortem §3) then adds
 * the DEDICATED spur road piece 50864-50863 as its own op kind with
 * GSRoad.BuildRoadFull semantics — the consumed v1 attempt proved a plain
 * BuildRoad on that company-road/roadless corner runs BUILT while
 * relocating the missing front end-bit (pair-28 dead road end) — and the
 * NEW bay truck stop 50862 fronts the spur end 50863 (the A0 native survey
 * D5CE3-SURVEY-3 observed 50862 live-flat, buildable, unowned, roadless,
 * with full 8/8 radius-3 cargo-1 acceptance). The full run cannot start on
 * 50095: that tile is already company road, and a `full` op requires
 * roadless unowned ground, so the run starts at the east neighbour 50096.
 * The road join is second in execution order exactly because `road`
 * eligibility requires both of its endpoints to be company road already
 * (50095 already is; 50096 becomes one only after the full run builds).
 * The stop build pins GSRoad.STATION_NEW: a new distinct station is the
 * pinned design, and it must never merge into the corridor's station sid 0
 * (pickup 45748) or sid 1 (delivery 50351).
 *
 * Wire contract v4 mirrors the proven identity style: command requests carry
 * the prelaunch seal the inspect latched; independent reads are intent-scoped
 * and carry the CorridorIntent digest. Tile bounds are 256x256-safe (pins
 * bounded 0..65535) so the historical 64x64 road contracts' window never
 * limits this corridor.-road */
class D5CorridorExtensionProof extends GSController {
    attempted = null
    admitted = null
    used = null
    /* Progress state: the schedule has four staged extension ops; `stage`
     * is the index of the one whose exchange group may run next. `halted`
     * stops every op after any command exchange failed to reach BUILT:
     * schedule evidence is prefix-preserving and no op is ever reordered or
     * retried. */
    stage = 0
    halted = false
    /* One-shot dispatcher budget accounting. */
    requests = 0
    /* Baked staged pins of the sealed D5 corridor-extension schedule, drawn
     * on the untouched built D4 corridor (OpenTTD 15.3 Seed-17, 256x256,
     * tile = y*256+x): the retained census graded the stop 50351 catchment
     * tiles to the south as vacant unowned roadless flat ground, but the
     * halted D5-CORRIDOR-EXTENSION-1 attempt proved that grade LIVE-STALE on
     * the terrace edge (native slope 9 at 50607, 8 at 50608, raised by the
     * D3 terraforming receipts' corner points (175..176, 190..197)), so the
     * branch stop sits two rows south of the delivery stop, outside that
     * raised corner influence: the branch is a vertical full run at x 176,
     * tiles 50096=(176,195), 50352=(176,196), 50608=(176,197),
     * 50864=(176,198) — span arithmetic y 195..198, run_len 4. The full run
     * starts at the east neighbour 50096 and cannot start on 50095: that
     * front tile is already company road, and a `full` op requires roadless
     * unowned ground with pair links at zero. The horizontal join
     * 50095-50096 (run_len 2) runs second because `road` eligibility
     * requires both endpoints to be already company road — 50095 is the
     * built corridor's delivery front; 50096 becomes one only after the
     * full run builds. The v2 spur road piece 50864-50863 runs third with
     * BuildRoadFull semantics — its start corner is the built run end and
     * its end corner is roadless unowned ground (the plain-BuildRoad variant
     * is not scheduled: the consumed v1 record proved it leaves the missing
     * front end-bit on the road corner). The NEW bay truck stop 50862
     * fronts the spur end 50863 and its build pins GSStation.STATION_NEW:
     * a new distinct station is the pinned design, never a merge into the
     * corridor's station sid 0 (pickup 45748) or sid 1 (delivery 50351).
     * No depot op is scheduled. The final route read stays pure
     * observation: DELIVERY is the new tail classification target classified
     * from the witness path itself (ObserveRoute reads path[0] and
     * path[len-1]), so no delivery constant is baked.
     *
     * Zero-surprise admission (engine-honest): the census grade is
     * hypothesis-grade evidence and no part of this schedule is trusted from
     * it. Native test mode validates and prices a command but never persists
     * its effects and never creates the infrastructure a dependent command
     * would need, so a whole-schedule simulated build chain is impossible in
     * the engine (the freight records prove this exactly: a vehicle
     * test-mode purchase cannot succeed on an unbuilt depot, and the road
     * fair-use records refuse to assume test mode simulates a preceding
     * construction). The pre-admission gate therefore proves, with ZERO
     * native mutation, every fact that is independently provable on the live
     * world before the first real command: the whole branch geometry's live
     * terrain — each full-run tile, the join's new end, the stop tile and
     * its front, exactly the terrace edge whose stale census grade hid the
     * native slope 9 that sank D5-CORRIDOR-EXTENSION-1 — must be live-vacant
     * and live-unowned ground, the stop tiles and their front live-flat (the
     * survey measured both 0), the delivery front must hold its built
     * company road, and BOTH independent road commands — the whole branch
     * full run and the horizontal join — must pass native test-mode
     * validation at a positive price on the live world. Sloped run tiles are
     * NOT refused here on their slope: the consumed A0 native survey
     * D5CE3-SURVEY-3 receipts of record measured 50096, 50352 live slope 12 and 50608 live slope 8 —
     * escarpment-side ramp tiles the 15.3 road command legitimately admit
     * with a foundation price (run tiles stay inside the observation
     * requirement; the viable straight road bits and the price are the
     * engine's own answer, read from the test-mode quote against the live
     * build_on_slopes setting). A refusal there refuses the stage-0
     * admission itself, so the world cannot be mutated by any road piece
     * while any branch fact fails. Failed limit: the stop op's own native
     * buildability cannot be pre-verified before its front road exists (the
     * station entrance requires the real built front), so this gate is
     * necessary, not sufficient; the residual post-gate exposure is bounded
     * to the schedule's road prefix, which the prefix-preserving halt and
     * funds rules cover. */
    PICKUP = 45748
    PICKUP_FRONT = 45747
    EXT_STOP = 50862
    EXT_FRONT = 50863
    BRANCH_RUN = [50096, 50864]
    EXT_SPUR = [50864, 50863]
    BRANCH_JOIN = [50095, 50096]
    DEPOT_TILE = 45487
    DEPOT_FRONT = 45743
    MAX_RUN = 36
    /* 4 x 3 planned exchanges + 1 route read = 13, plus 5 slack, so request
     * 19 is the first one the dispatcher refuses. */
    max_requests = 18

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
        return GSTile.GetSlope(t) == 0 && FootprintVacant(t);
    }

    function FootprintVacant(t) {
        /* The road-footprint vacancy predicate WITHOUT the flatness clause:
         * the surveyed escarpment ramp tiles (live slope 12/12/8 of record)
         * are not admission refusals — a straight road on such ramps is native
         * legal with a foundation price under live build_on_slopes, so the
         * run's own command quote is the native verdict and only the full
         * run (single command) rides this predicate. Stop/depot ground stays
         * held to the flat Vacant predicate. */
        return GSTile.IsBuildable(t) &&
            GSTile.GetOwner(t) == GSCompany.COMPANY_INVALID &&
            !GSTile.IsWaterTile(t) && !GSTile.IsCoastTile(t) &&
            !GSTile.HasTreeOnTile(t) && !GSTile.IsFarmTile(t) &&
            !GSTile.IsRockTile(t) && !GSTile.IsRoughTile(t) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_ROAD) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_RAIL) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_WATER) &&
            !GSTile.HasTransportType(t, GSTile.TRANSPORT_AIR);
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

    /* The baked staged schedule keys in execution order: the branch full
     * run, the horizontal join to the delivery front, the dedicated spur
     * road piece, and the NEW bay truck stop. No depot key is scheduled. */
    function StageIndex(key) {
        local stages = [ShapeKey("full", 50096, 50864),
                        ShapeKey("road", 50095, 50096),
                        ShapeKey("spur", 50864, 50863),
                        KindKey("station", 50862)]
        for (local i = 0; i < 4; i++)
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
        if ((dx != 0 && dy != 0) || span < 1 || span > MAX_RUN) throw "D5_EXT_NATIVE_FACT"
        local step = dx == 0 ? wx * (dy < 0 ? -1 : 1) : (dx < 0 ? -1 : 1)
        local count = span + 1
        local covered = 0
        local pairs_ok = 0
        local tile = a
        for (local i = 0; i < count; i++) {
            if (!GSMap.IsValidTile(tile) ||
                GSMap.GetTileX(tile) != tile % wx ||
                GSMap.GetTileY(tile) != tile / wx) throw "D5_EXT_NATIVE_FACT"
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
            GSMap.GetTileY(tile) != tile / wx) throw "D5_EXT_NATIVE_FACT"
        if (!GSMap.IsValidTile(front) || GSMap.GetTileX(front) != front % wx ||
            GSMap.GetTileY(front) != front / wx) throw "D5_EXT_NATIVE_FACT"
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
        /* The front's road fact joins the observation table only; the reply
         * filler exposes no new field, and the stop eligibility reads it so
         * a stop may only ever be admitted fronting an existing company
         * road attachment (the same gate the Python admission enforces). */
        local front_road = GSRoad.IsRoadTile(front)
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
            front_road = front_road,
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

    /* The zero-mutation pre-admission gate (see the baked-pins comment for
     * the engine-honest budget): native test mode validates and prices a
     * command but never persists its effects and never creates the
     * infrastructure a dependent command would need (the freight records:
     * a vehicle test-mode purchase cannot succeed on an unbuilt depot; the
     * road fair-use records refuse to assume test mode simulates a
     * preceding construction). A whole-schedule simulated build chain is
     * therefore impossible in the engine, and the gate proves instead,
     * with zero mutation, every independent fact on the live world:
     *  1. the WHOLE branch geometry's live terrain (pure observation):
     *     each full-run tile, the join's new end 50096, the stop tile and
     *     its front must be live-vacant and live-unowned ground, the stop
     *     tile and its front live-flat (the survey measured both slope 0),
     *     and the delivery front must hold its built company road.
     *     This is exactly the terrace edge whose stale census grade hid
     *     the native slope 9 that sank D5-CORRIDOR-EXTENSION-1 after two
     *     road builds had already mutated the world.
     *  2. BOTH independent road commands pass native test-mode validation
     *     at a positive price on the live world under the per-command cost
     *     ceiling, with live funds covering each: the branch full run
     *     (BuildRoadFull across the surveyed escarpment ramp tiles; the
     *     run is one command, so its quote proves the whole run's slope
     *     foundation pricing and acceptance before any mutation), and the
     *     horizontal join (BuildRoad on the live unbuilt join ground).
     *     The preview debits and persists nothing; the schedule's own
     *     per-op exchange later re-quotes each command against its own
     *     fresh admission.
     * The return table carries `costs` (the preview quote) on success, or
     * the refusal reason plus the failing state's own observation table
     * (site facts from ObserveSite for any stop/front-related refusal) —
     * wire diagnostics, never a pass label. The stop op's own native
     * buildability cannot be pre-verified before its front road exists
     * (the station entrance requires the real built front), so this gate
     * is necessary, not sufficient; the residual post-gate exposure is
     * bounded to the schedule's road prefix itself. */
    function Chain(company, max_cost) {
        local out = { ok = false, costs = [] }
        local run = [50096, 50352, 50608, 50864]
        local site = null
        foreach (tile in run) {
            if (!GSMap.IsValidTile(tile)) {
                out.reason <- "BRANCH_NATIVE_FACT"
                out.blocker <- "full"
                out.slope_facts <- null
                return out
            }
            /* Slopes are not refused here: the survey receipts measured the
             * escarpment ramp tiles 50096/50352 live slope 12 and 50608
             * live slope 8, and a straight road on either slope is native
             * legal with a foundation price under live build_on_slopes —
             * the run's own preview quote below is the native verdict. */
            if (!FootprintVacant(tile)) {
                out.reason <- "BRANCH_NOT_VACANT"
                out.blocker <- "full"
                out.slope_facts <- null
                return out
            }
        }
        /* The stop tile's own site facts: the exact evidence that refused
         * the halted predecessor's stop build, sampled before any mutation. */
        try {
            site = ObserveSite(EXT_STOP, EXT_FRONT, company)
            site.stop_tile <- EXT_STOP
        } catch (error) {
            out.reason <- "BRANCH_NATIVE_FACT"
            out.blocker <- "station"
            out.slope_facts <- null
            return out
        }
        if (site.stop_slope != 0 || site.front_slope != 0) {
            out.reason <- site.stop_slope != 0 ? "STOP_TILE_SLOPED" : "FRONT_TILE_SLOPED"
            out.blocker <- "station"
            out.slope_facts <- { stop_min_height = site.stop_min_height,
                                 stop_slope = site.stop_slope,
                                 front_min_height = site.front_min_height,
                                 front_slope = site.front_slope }
            return out
        }
        if (!Vacant(EXT_STOP) || site.stop || site.drive_through || site.truck ||
            site.depot || site.depot_linked) {
            out.reason <- "BRANCH_STOP_OCCUPIED"
            out.blocker <- "station"
            out.slope_facts <- { stop_min_height = site.stop_min_height,
                                 stop_slope = site.stop_slope,
                                 front_min_height = site.front_min_height,
                                 front_slope = site.front_slope }
            return out
        }
        /* The join's existing end must still be the built delivery road. */
        if (!GSRoad.IsRoadTile(50095) || GSTile.GetOwner(50095) != company) {
            out.reason <- "BRANCH_JOIN_NOT_ROAD"
            out.blocker <- "road"
            out.slope_facts <- null
            return out
        }
        /* Native validation of the independent branch-run command on the
         * live (unbuilt) run ground: the whole run is ONE command, so its
         * test-mode price covers the escarpment ramp tiles' foundation
         * pricing — acceptance, legality and funds are proven before any
         * mutation. The preview debits and persists nothing. */
        local run_preview = Quote("full", { kind = "full", start = 50096, end = 50864 })
        if (!run_preview[0]) {
            out.reason <- "full_QUOTE_REFUSED"
            out.blocker <- "full"
            out.slope_facts <- null
            return out
        }
        if (run_preview[1] <= 0) {
            out.reason <- "full_ZERO_COST"
            out.blocker <- "full"
            out.slope_facts <- null
            return out
        }
        if (run_preview[1] > max_cost) {
            out.reason <- "full_COST_LIMIT"
            out.blocker <- "full"
            out.slope_facts <- null
            return out
        }
        if (GSCompany.GetBankBalance(company) < run_preview[1]) {
            out.reason <- "full_INSUFFICIENT_FUNDS"
            out.blocker <- "full"
            out.slope_facts <- null
            return out
        }
        out.costs.append(run_preview[1])
        /* Native validation of the independent join command on the live
         * (unbuilt) join ground: a positive tested price, at or under the
         * ceiling, covered by live funds. */
        local preview = Quote("road", { kind = "road", start = 50095, end = 50096 })
        if (!preview[0]) {
            out.reason <- "road_QUOTE_REFUSED"
            out.blocker <- "road"
            out.slope_facts <- null
            return out
        }
        if (preview[1] <= 0) {
            out.reason <- "road_ZERO_COST"
            out.blocker <- "road"
            out.slope_facts <- null
            return out
        }
        if (preview[1] > max_cost) {
            out.reason <- "road_COST_LIMIT"
            out.blocker <- "road"
            out.slope_facts <- null
            return out
        }
        if (GSCompany.GetBankBalance(company) < preview[1]) {
            out.reason <- "road_INSUFFICIENT_FUNDS"
            out.blocker <- "road"
            out.slope_facts <- null
            return out
        }
        out.costs.append(preview[1])
        out.ok = true
        return out
    }

    /* The single native build command of one op kind, pinned from its own
     * request shape only (the wire omits inapplicable keys entirely). */
    function RunCommand(kind, q) {
        if (kind == "full") return GSRoad.BuildRoadFull(q.start, q.end)
        if (kind == "road") return GSRoad.BuildRoad(q.start, q.end)
        if (kind == "spur") return GSRoad.BuildRoadFull(q.start, q.end)
        if (kind == "station")
            return GSRoad.BuildRoadStation(q.tile, q.front, GSRoad.ROADVEHTYPE_TRUCK,
                GSStation.STATION_NEW)
        return GSRoad.BuildRoadDepot(q.tile, q.front)
    }

    /* The op kind's factual eligibility verdict on the current world state:
     * roadless unowned ground for a full run, company road on both corner
     * endpoints with no existing link for the corner piece, a built company
     * road into unplanned company-invalid roadless ground for the spur
     * (its post-build receipt natively proves the spur end's missing bit:
     * pairs_ok 1 and covered 2; the stop-facing bit is proven only by the
     * terminal route-witness pair), unplanned ground fronting this company
     * road for a stop. (No depot is scheduled; the depot predicates stay as
     * the preserved handler shape.) Never a claim that a build will
     * succeed: the native quote decides buildability. */
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
        if (kind == "spur")
            return obs.owner0 == company && obs.owner1 == GSCompany.COMPANY_INVALID &&
                obs.road0 == true && obs.road1 == false &&
                obs.covered == 1 && obs.pairs_ok == 0
        local unplanned = obs.stop_owner == GSCompany.COMPANY_INVALID &&
            Vacant(kind == "station" ? obs.stop_tile : obs.depot_tile)
        if (kind == "station")
            return unplanned && !obs.stop && !obs.drive_through &&
                !obs.truck && obs.depot == false &&
                obs.front_owner == company && obs.front_road == true
        return unplanned && !obs.depot && !obs.depot_linked &&
            obs.front_owner == company && obs.front_road == true
    }

    /* The post-command structural verdict of one op kind's observation. The
     * front pin is read only where the op carries one (site ops). */
    function PostHolds(kind, company, q, obs) {
        if (kind == "full" || kind == "road" || kind == "spur")
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
        local on_road = kind == "full" || kind == "road" || kind == "spur"
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
            if (r.eligible && kind == "full" && stage == 0) {
                /* Zero-surprise gate: no staged op may be admitted (let
                 * alone dispatched) while any fact the whole branch needs
                 * is indeterminate on the live world. Native test mode
                 * validates/prices but never persists a build, so the gate
                 * proves every independently provable fact instead: the
                 * whole branch geometry's live terrain (exactly the
                 * terrace edge whose stale census grade hid the native
                 * slope 9 that sank D5-CORRIDOR-EXTENSION-1 after two road
                 * builds) at zero mutation — the run tiles' slopes of
                 * record are escarpment ramps, not refusals — plus native
                 * test-mode validations of BOTH independent road commands
                 * (the whole full run and the join). The stop op's own
                 * buildability cannot be natively pre-verified before its
                 * front road exists; the residual exposure is bounded to
                 * the schedule's road prefix (see the class comment). */
                local chain = Chain(company, q.max_cost)
                if (chain.ok) {
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
                    }
                } else {
                    r.status = chain.reason == "road_QUOTE_REFUSED" ||
                        chain.reason == "road_ZERO_COST" ||
                        chain.reason == "full_QUOTE_REFUSED" ||
                        chain.reason == "full_ZERO_COST" ? "REJECTED" :
                        chain.reason == "road_COST_LIMIT" ||
                        chain.reason == "full_COST_LIMIT" ? "COST_LIMIT" :
                        chain.reason == "road_INSUFFICIENT_FUNDS" ||
                        chain.reason == "full_INSUFFICIENT_FUNDS" ?
                        "INSUFFICIENT_FUNDS" :
                        chain.reason == "BRANCH_NATIVE_FACT" ?
                        "UNSUPPORTED_NATIVE_FACT" : "NOT_BUILDABLE"
                    if (chain.slope_facts != null) {
                        r.stop_min_height <- chain.slope_facts.stop_min_height
                        r.stop_slope <- chain.slope_facts.stop_slope
                        r.front_min_height <- chain.slope_facts.front_min_height
                        r.front_slope <- chain.slope_facts.front_slope
                    }
                }
                if (r.status == "READY") {
                    admitted[key] <- {plan=q.plan, company=q.company,
                        max_cost=q.max_cost, kind=kind, cost=r.cost}
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
            } else if (r.eligible) {
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
            } else {
                r.status = "NOT_BUILDABLE"
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
              q.op == "full" || q.op == "road" || q.op == "spur" ||
              q.op == "station" || q.op == "depot")) return
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
                  q.target == "spur" ||
                  q.target == "station" || q.target == "depot")) return
            local kind = q.target
            if (kind == "full" || kind == "road" || kind == "spur") {
                if (!("start" in q) || !("end" in q) || "tile" in q ||
                    "front" in q || "tiles" in q) return
                if (typeof q.start != "integer" || typeof q.end != "integer" ||
                    q.start < 0 || q.start > 65535 || q.end < 0 ||
                    q.end > 65535) return
                local wx = GSMap.GetMapSizeX()
                local dx = abs_int(q.start % wx - q.end % wx)
                local dy = abs_int(q.start / wx - q.end / wx)
                if (kind == "full" || kind == "spur"
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
        } else if (op == "full" || op == "road" || op == "spur") {
            if ("target" in q || "tile" in q || "front" in q || "tiles" in q) return
            if (!("start" in q) || !("end" in q) ||
                typeof q.start != "integer" || typeof q.end != "integer" ||
                q.start < 0 || q.start > 65535 || q.end < 0 ||
                q.end > 65535) return
            local wx = GSMap.GetMapSizeX()
            local dx = abs_int(q.start % wx - q.end % wx)
            local dy = abs_int(q.start / wx - q.end / wx)
            if (op == "road"
                    ? dx + dy != 1
                    : (dx != 0 && dy != 0) || dx + dy < 1 || dx + dy > 36) return
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
                local key = kind == "full" || kind == "road" || kind == "spur"
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
        if (!GSAdmin.Send(r)) throw "D5_EXT_RESPONSE_SEND_FAILED"
        GSLog.Info("D5_EXT_RESPONSE " + q.request_id + " " + r.status)
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
     * final route read binds below the corridor contract's 640-byte response
     * gate (its 31-tile witness echo is the largest allowed reply). They mirror
     * the CorridorReadback field bounds exactly. */
    function Guard(r) {
        if (r.funds < -2147483648 || r.funds > 2147483647 || r.cost < 0 ||
            r.cost > 2147483647) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("owner0" in r && (r.owner0 < -1 || r.owner0 > 14)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("owner1" in r && (r.owner1 < -1 || r.owner1 > 14)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("run_len" in r && (r.run_len < 0 || r.run_len > 48)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("covered" in r && (r.covered < 0 || r.covered > 48)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("pairs_ok" in r && (r.pairs_ok < 0 || r.pairs_ok > 48)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("pair_total" in r && (r.pair_total < 0 || r.pair_total > 48)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("sid" in r && (r.sid < -1 || r.sid > 1073741824)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("stop_owner" in r && (r.stop_owner < -1 || r.stop_owner > 14)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("front_owner" in r && (r.front_owner < -1 || r.front_owner > 14)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("depot_front_id" in r && (r.depot_front_id < -1 || r.depot_front_id > 1073741824))
            throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("stop_min_height" in r && (r.stop_min_height < 0 || r.stop_min_height > 255))
            throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("stop_slope" in r && (r.stop_slope < 0 || r.stop_slope > 31)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("front_min_height" in r && (r.front_min_height < 0 || r.front_min_height > 255))
            throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("front_slope" in r && (r.front_slope < 0 || r.front_slope > 31)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("connected_pairs" in r && (r.connected_pairs < 0 || r.connected_pairs > 48))
            throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("first_fail" in r && (r.first_fail < -1 || r.first_fail > 48)) throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("pickup_sid" in r && (r.pickup_sid < -1 || r.pickup_sid > 1073741824))
            throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
        if ("delivery_sid" in r && (r.delivery_sid < -1 || r.delivery_sid > 1073741824))
            throw "D5_EXT_RESPONSE_OUT_OF_BOUNDS"
    }

    function Start() {
        GSLog.Info("D5_EXT_READY")
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
class NetworkFreightProof extends D5CorridorExtensionProof {
}
