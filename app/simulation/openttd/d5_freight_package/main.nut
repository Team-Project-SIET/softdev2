/* Separate bounded native corridor-freight-cycle handler. Additive: no
 * existing frozen package is modified or imported. The only native mutation
 * commands are GSVehicle.BuildVehicle (once), GSOrder.AppendOrder (twice:
 * pickup full-load, delivery no-load) and GSVehicle.StartStopVehicle (start
 * once, stop once at finish) in company mode, each executed at most once
 * against the fixed fifteen-exchange schedule; demolition, terraforming,
 * road, station, depot, refit, selling and second-vehicle commands are
 * absent by construction. GSCargoMonitor arming and consumption are
 * observation state, not commands.
 *
 * The handler ports the proven lifecycle kernel (freight_delivery_package:
 * engine enumeration under a bounded list, test-mode quote, BuildVehicle,
 * order appends, StartStopVehicle) plus the delivery-evidence kernel
 * (GSCargoMonitor armed with keep_monitoring=true before the first start,
 * equal amounts behind the verify gate, and consumed with keep=false
 * exactly once during the deliver-watch window), bound to the D4 corridor
 * geometry: pickup stop 45748 (front 45747), delivery stop 50351 (front
 * 50095), depot 45487 (front 45743), the ordered 24-tile witness path
 * re-checked connected on the company's own road, cargo 1, industries 0
 * (pickup) and 1 (delivery).
 *
 * Every exchange is one fixed stage of the plan: request id AND op must
 * equal the planned exchange of the current stage, so any replay or reorder
 * becomes OUT_OF_ORDER. Watch windows poll one script tick per sample with
 * clock sanity (regression/stall fail-closed, pause checked first), and
 * window/day caps bounded by the request echoes and the module constants
 * (2048 ticks, 30 in-game days) - caps, never promises. A refusal or an
 * inconclusive window halts the schedule prefix-preservingly: later
 * exchanges answer OUT_OF_ORDER, no op is ever reordered or retried, and
 * no failed command is ever reported as leaving the world unchanged.
 *
 * Native API pins carried from the proven 15.3 records (all opened natively
 * before): GSVehicle.{IsPrimaryVehicle,BuildVehicle,StartStopVehicle,
 * GetEngineType,GetOwner,GetLocation,GetCapacity,IsInDepot,GetCurrentSpeed,
 * GetState,GetCargoLoad}, GSEngine enumeration with GetCargoType/GetCapacity/
 * GetPrice for the default cargo, GSOrder.{AppendOrder,AreOrderFlagsValid,
 * GetOrderCount,GetOrderDestination,GetOrderFlags,IsGotoStationOrder},
 * GSIndustry.{GetLastMonthProduction,GetCargoLastAcceptedDate},
 * GSCompany.{GetBankBalance,GetQuarterlyIncome,GetQuarterlyCargoDelivered}
 * with GSCompany.CURRENT_QUARTER, GSCargoMonitor.GetIndustry{Pickup,
 * Delivery}Amount(company,cargo,industry,keep), GSGame.IsPaused,
 * GSDate.GetCurrentDate. GSVehicle.BuildVehicle returns the new VehicleID
 * in real mode (0 in test mode on success, any other value on failure,
 * exactly like the proven lifecycle kernel's purchase quote).
 *
 * The design document section 4 names GSStation.GetCargoAcceptance for the
 * delivery acceptance fact; that member does not exist in the 15.3 station
 * API family, so the fact is read through the proven catchment predicate
 * GSTile.GetCargoAcceptance(delivery_tile, cargo, 1, 1, radius) with the
 * truck-stop coverage radius - 0..8 eighths, the same shape the legacy
 * delivery proof verified natively (recorded as the acceptance-API
 * discrepancy note in the D5 preparation docs). The vehicle readback's
 * cargo slot is the admitted corridor cargo: no refit exists in this
 * machinery, and a vehicle carrying any other cargo reads capacity 0
 * there and is refused on that capacity. */
class D5FreightProof extends GSController {
    /* Schedule state: `stage` is the index of the one planned exchange that
     * may run next; `halted` stops every later exchange after any success
     * frame failed to produce its exact planned status. */
    stage = 0
    halted = false
    /* One-shot dispatcher budget accounting (unique ids, 32-request cap). */
    requests = 0
    used = null
    /* Latched prelaunch plan digest: the first accepted exchange fixes the
     * attempt's plan identity; every later exchange must match it. */
    plan_id = null
    /* Latched route digest supplied by the site exchange. Squirrel has no
     * SHA-256, so this is an opaque consistency tag, not independent
     * authentication: Python derives it from FreightPlan.witness and verifies
     * every request before dispatch. The GameScript's guarantee is narrower
     * but real: once the site route is latched, every later exchange must
     * present the same digest, so a stale route is refused before purchase. */
    route_digest = null

    /* Latched execution geometry. The site request carries the
     * optimizer-selected route; these fields are initialized from the D4
     * defaults only so the class is constructible before the site exchange,
     * and are replaced atomically when a valid route is latched. */
    pickup = -1
    pickup_front = -1
    delivery = -1
    delivery_front = -1
    depot_tile = -1
    depot_front = -1
    witness = null

    constructor() {
        this.pickup = PICKUP
        this.pickup_front = PICKUP_FRONT
        this.delivery = DELIVERY
        this.delivery_front = DELIVERY_FRONT
        this.depot_tile = DEPOT_TILE
        this.depot_front = DEPOT_FRONT
        this.witness = []
        foreach (tile in WITNESS) this.witness.append(tile)
    }

    /* Baked staged pins of the sealed D4 corridor close-out (candidate-5):
     * the defaults used when no site route has been latched, and the
     * demonstrated geometry the optimizer round-trips in staging. */
    PICKUP = 45748
    PICKUP_FRONT = 45747
    DELIVERY = 50351
    DELIVERY_FRONT = 50095
    DEPOT_TILE = 45487
    DEPOT_FRONT = 45743
    /* The ordered witness path of the D4 route receipt (24 tiles, 23 pairs);
     * the vehicle drive is validated against the latched ordered list. */
    WITNESS = [45748, 45747, 45746, 45745, 45744, 45743, 45999, 46255, 46511,
               46767, 47023, 47279, 47535, 47791, 48047, 48303, 48559, 48815,
               49071, 49327, 49583, 49839, 50095, 50351]
    MAX_ROUTE_TILES = 24
    /* Fixed corridor freight idents (the plan only drives this geometry). */
    FREIGHT_COMPANY = 0
    FREIGHT_CARGO = 1
    PICKUP_INDUSTRY = 0
    DELIVERY_INDUSTRY = 1
    /* Per-watch window caps (design section 8): caps, never promises. */
    MAX_TICKS = 2048
    MAX_DAYS = 30

    /* The fixed fifteen-exchange schedule: [request_id, op, success status],
     * the same order the Python contract's FREIGHT_EXCHANGE_IDS pins. */
    planned = [
        ["site-00", "site", "READY"],
        ["engine-00", "engine", "READY"],
        ["purchase-00", "purchase", "BUILT"],
        ["vread-00", "vread", "READ"],
        ["order-00", "order", "ORDERED"],
        ["order-01", "order", "ORDERED"],
        ["order-read-00", "order-read", "ORDER_SET_VERIFIED"],
        ["monitor-00", "monitor", "ARMED"],
        ["start-00", "start", "STARTED"],
        ["vread-01", "vread", "READ"],
        ["load-00", "load-watch", "LOADED"],
        ["transit-00", "transit-watch", "AT_DELIVERY"],
        ["deliver-00", "deliver-watch", "DELIVERED"],
        ["finance-00", "finance", "FINANCE_VERIFIED"],
        ["finish-00", "finish", "PHASE_STOPPED"]
    ]
    /* 15 planned exchanges, plus dispatcher slack only through unique ids:
     * request 33 is the first one the dispatcher drops. */
    max_requests = 32

    /* Latched admission facts (one attempt: one site, one engine, one
     * vehicle). Nothing here authorizes anything; every later exchange
     * re-observes its identity against these latches and refuses drift. */
    site_sid0 = -1
    site_sid1 = -1
    site_waiting = -1
    site_production = -1
    engine_id = -1
    engine_capacity = -1
    engine_quote = 0
    vehicle_id = -1
    monitor_armed = false
    armed_income = 0
    armed_delivered = 0
    observed_load = 0

    function PlannedIndex(q) {
        /* The planned exchange carrying BOTH the request id and its op. */
        for (local i = 0; i < planned.len(); i++)
            if (planned[i][0] == q.request_id && planned[i][1] == q.op) return i
        return -1
    }

    /* -- protocol 6: the read-only acceptance survey (D5-ACCEPT-SURVEY-1) ---- */
    /* Additive over the freight schedule: pure observation of the native
     * truck-stop coverage radius, tile-level cargo-1 acceptance over the
     * pinned control + candidate tiles, and the pickup-side production
     * control. No stop is built or assumed buildable at any tile; a
     * measured acceptance value is catchment evidence only. */
    survey_planned = [
        ["radius-00", "radius", "READY"],
        ["accept-00", "accept", "READY"],
        ["accept-01", "accept", "READY"],
        ["accept-02", "accept", "READY"],
        ["accept-03", "accept", "READY"],
        ["accept-04", "accept", "READY"],
        ["accept-05", "accept", "READY"],
        ["prod-00", "prod", "READY"]
    ]
    survey_stage = 0
    survey_halted = false
    /* Survey pins: the consumed attempt's delivery stop (control, expected
     * zero by the finding of record) and the five retained pre-construction
     * census candidate tiles. These are hypothesis locations, never proven
     * buildable stops and never a proven freight route. */
    ACCEPT_CONTROL = 50351
    ACCEPT_CANDIDATES = [50607, 50863, 51119, 51375, 50605]

    function SurveyOpAllowed(op) {
        return op == "radius" || op == "accept" || op == "prod"
    }

    function SurveyPlannedIndex(q) {
        for (local i = 0; i < survey_planned.len(); i++)
            if (survey_planned[i][0] == q.request_id && survey_planned[i][1] == q.op) return i
        return -1
    }

    function AcceptPinned(tile) {
        if (tile == ACCEPT_CONTROL) return true
        foreach (t in ACCEPT_CANDIDATES) if (t == tile) return true
        return false
    }

    function SurveyGuard(r) {
        if (r.funds < -2147483648 || r.funds > 2147483647 || r.cost < 0 ||
            r.cost > 2147483647) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("tile" in r && (r.tile < 0 || r.tile > 65535)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("radius" in r && (r.radius < 0 || r.radius > 255)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("accept" in r && (r.accept < 0 || r.accept > 8)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("prod" in r && (r.prod < 0 || r.prod > 2147483647)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
    }

    /* -- op: radius (pure observation, zero cost) --------------------------- */
    function SurveyRadiusOp(r) {
        local radius = GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP)
        if (radius < 0 || radius > 255) throw "D5_NATIVE_FACT"
        r.radius <- radius
        r.status = "READY"
    }

    /* -- op: accept (one pinned tile, zero cost) ----------------------------- */
    function SurveyAcceptOp(q, r) {
        /* Tile defence in depth: only the pinned control or a pinned
         * candidate may be queried; any other tile is an out-of-survey
         * location, refused before any observation. */
        if (!AcceptPinned(q.tile)) {
            r.status = "INVALID_LOCATION"
            return
        }
        local radius = GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP)
        if (radius < 0 || radius > 255) throw "D5_NATIVE_FACT"
        local accept = GSTile.GetCargoAcceptance(q.tile, FREIGHT_CARGO, 1, 1, radius)
        if (accept < 0 || accept > 8) throw "D5_NATIVE_FACT"
        /* A zero here is a MEASURED zero only under this correlated READY
         * reply with the native radius echo attached; refusals carry no
         * observation at all. */
        r.tile <- q.tile
        r.accept <- accept
        r.radius <- radius
        r.status = "READY"
    }

    /* -- op: prod (pickup-side production control, zero cost) ---------------- */
    function SurveyProdOp(r) {
        local production = GSIndustry.GetLastMonthProduction(PICKUP_INDUSTRY, FREIGHT_CARGO)
        if (production < 0) throw "D5_NATIVE_FACT"
        r.prod <- production
        r.status = "READY"
    }

    function SurveyHandle(q) {
        if (!("op" in q) || typeof q.op != "string" || !SurveyOpAllowed(q.op)) return
        if (!("request_id" in q) || typeof q.request_id != "string" ||
            q.request_id.len() < 1 || q.request_id.len() > 32 ||
            !IdShape(q.request_id)) return
        if (!("plan" in q) || typeof q.plan != "string" || !Hex64(q.plan)) return
        if (!("company" in q) || typeof q.company != "integer" ||
            q.company < 0 || q.company > 14) return
        if (!("max_cost" in q) || typeof q.max_cost != "integer" || q.max_cost != 0) return
        if (!("pickup" in q) || typeof q.pickup != "integer" ||
            q.pickup < 0 || q.pickup > 65535 ||
            !("delivery" in q) || typeof q.delivery != "integer" ||
            q.delivery < 0 || q.delivery > 65535 ||
            !("depot" in q) || typeof q.depot != "integer" ||
            q.depot < 0 || q.depot > 65535 ||
            q.pickup == q.delivery || q.depot == q.pickup ||
            q.depot == q.delivery) return
        /* tile is required (an integer in map bounds) on accept exactly and
         * null on the other survey ops — the wire serializes its absence. */
        if (!("tile" in q)) return
        if (q.op == "accept") {
            if (typeof q.tile != "integer" || q.tile < 0 || q.tile > 65535) return
        } else if (q.tile != null) return
        /* Shared one-shot budget accounting across both protocols: unique
         * request ids, the same 32-request cap; a duplicate id or an
         * exhausted budget is silently dropped. */
        if (used == null) used = {}
        if (q.request_id in used || this.requests >= this.max_requests) return
        used[q.request_id] <- true
        this.requests++
        local r = {
            protocol = 6, op = q.op, request_id = q.request_id, plan = q.plan,
            company = q.company, max_cost = q.max_cost, pickup = q.pickup,
            delivery = q.delivery, depot = q.depot, status = "OUT_OF_ORDER",
            funds = 0, cost = 0
        }
        if (q.op == "accept") r.tile <- q.tile
        local idx = SurveyPlannedIndex(q)
        if (idx < 0 || idx != this.survey_stage || this.survey_halted) {
            r.status = "OUT_OF_ORDER"
        } else if (this.plan_id != null && this.plan_id != q.plan) {
            r.status = "OUT_OF_ORDER"
        } else if (GSCompany.ResolveCompanyID(q.company) != q.company ||
                   q.company != FREIGHT_COMPANY) {
            r.status = "INVALID_COMPANY"
        } else if (q.pickup != this.pickup || q.delivery != this.delivery ||
                   q.depot != this.depot_tile) {
            r.status = "STALE_PIN"
        } else {
            if (this.plan_id == null) this.plan_id = q.plan
            if (GSGame.IsPaused()) {
                r.status = "PAUSED"
            } else {
                try {
                    local company = GSCompanyMode(q.company)
                    if (!GSCompanyMode.IsValid()) {
                        r.status = "INVALID_COMPANY"
                    } else {
                        /* Every survey reply carries the bank balance at the
                         * exchange boundary (recorded, never changed: the
                         * survey has no cost-bearing operation). */
                        r.funds = GSCompany.GetBankBalance(q.company)
                        if (q.op == "radius") {
                            SurveyRadiusOp(r)
                        } else if (q.op == "accept") {
                            SurveyAcceptOp(q, r)
                        } else {
                            SurveyProdOp(r)
                        }
                    }
                } catch (error) {
                    r.status = "UNSUPPORTED_NATIVE_FACT"
                }
            }
        }
        SurveyGuard(r)
        if (!GSAdmin.Send(r)) throw "D5_RESPONSE_SEND_FAILED"
        GSLog.Info("D5_SURVEY " + q.request_id + " " + r.status)
        /* Survey schedule accounting: only the exact READY status of the
         * planned exchange advances the survey stage; every other terminal
         * status halts the survey prefix-preservingly. Evidence, never
         * retries. The freight schedule accounting below stays untouched. */
        if (idx >= 0) {
            if (r.status == survey_planned[idx][2]) {
                if (idx == this.survey_stage && !this.survey_halted) this.survey_stage = idx + 1
            } else {
                this.survey_halted = true
            }
        }
    }

    /* -- protocol 7: the read-only terrain survey --------------------------- */
    /* Strictly additive over protocols 5 and 6: pure observation of the
     * branch pins' live terrain facts (slope, heights, buildable, owner,
     * tree/water/coast/farm/rock/rough and the four transport presences)
     * plus the acceptance control pair under the measured native radius.
     * The D5-CORRIDOR-EXTENSION-1 halt proved live slope 9/8 on the
     * predecessor's terrace stop while its census grade said flat; this
     * instrument samples those facts on tiles 50095/50096/50352/50608/
     * 50864/50863/50862 BEFORE any further extension mutates anything —
     * tile 50862 is added because the corrected terminal design places the
     * bay truck stop there (front 50863), a tile the consumed
     * D5-TERRAIN-SURVEY-1 never observed. Every observation here is fresh
     * evidence for the D5-CORRIDOR-EXTENSION-3-SURVEY-1 attempt; no
     * consumed survey observation is ever reused. A nonzero slope or an
     * occupied tile here is a FINDING of record, never a survey failure.
     * No stop is built and no mutation of any kind. */
    terrain_planned = [
        ["radius-00", "radius", "READY"],
        ["tile-00", "tile", "READY"],
        ["tile-01", "tile", "READY"],
        ["tile-02", "tile", "READY"],
        ["tile-03", "tile", "READY"],
        ["tile-04", "tile", "READY"],
        ["tile-05", "tile", "READY"],
        ["tile-06", "tile", "READY"],
        ["accept-00", "accept", "READY"],
        ["accept-01", "accept", "READY"]
    ]
    terrain_stage = 0
    terrain_halted = false
    /* Terrain pins: the built delivery front (its live company-road fact
     * defends the join start), the four south-branch full-run tiles, the
     * spur-end road tile and the proposed station ground (added by the
     * D5-CORRIDOR-EXTENSION-3 survey); the acceptance pair is the consumed
     * attempt's delivery stop (control, expected zero) and this survey's
     * proposed station tile. */
    TERRA_TILES = [50095, 50096, 50352, 50608, 50864, 50863, 50862]
    TERRA_ACCEPT_CONTROL = 50351
    TERRA_ACCEPT_STOP = 50862

    function TerrainOpAllowed(op) {
        return op == "radius" || op == "tile" || op == "accept"
    }

    function TerrainPlannedIndex(q) {
        for (local i = 0; i < terrain_planned.len(); i++)
            if (terrain_planned[i][0] == q.request_id && terrain_planned[i][1] == q.op) return i
        return -1
    }

    function TilePinned(tile) {
        foreach (t in TERRA_TILES) if (t == tile) return true
        return false
    }

    function TerrainAcceptPinned(tile) {
        return tile == TERRA_ACCEPT_CONTROL || tile == TERRA_ACCEPT_STOP
    }

    /* Native booleans may surface from some API layers as the integers
     * 0/1 instead of true/false; normalize every table fact to an explicit
     * Squirrel boolean before sending so the wire shape is deterministic. */
    function TerrainFactNorm(r) {
        foreach (pred in ["buildable", "tree", "water", "coast", "farm", "rock", "rough",
                          "road", "rail", "water_transport", "air_transport"]) {
            if (!(pred in r)) continue
            if (typeof r[pred] == "integer") {
                if (r[pred] != 0 && r[pred] != 1) throw "D5_NATIVE_FACT"
                r[pred] = r[pred] != 0
            } else if (typeof r[pred] != "bool") {
                throw "D5_NATIVE_FACT"
            }
        }
    }

    function TerrainGuard(r) {
        if (r.funds < -2147483648 || r.funds > 2147483647 || r.cost < 0 ||
            r.cost > 2147483647) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("tile" in r && (r.tile < 0 || r.tile > 65535)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("radius" in r && (r.radius < 0 || r.radius > 255)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("accept" in r && (r.accept < 0 || r.accept > 8)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("slope" in r && (r.slope < 0 || r.slope > 255)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("min_height" in r && (r.min_height < 0 || r.min_height > 255))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("max_height" in r && (r.max_height < 0 || r.max_height > 255))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("owner" in r && (r.owner < -2 || r.owner > 65535)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        foreach (pred in ["buildable", "tree", "water", "coast", "farm", "rock", "rough",
                          "road", "rail", "water_transport", "air_transport"]) {
            if (pred in r) {
                if (typeof r[pred] != "bool" && typeof r[pred] != "integer")
                    throw "D5_RESPONSE_OUT_OF_BOUNDS"
                if (typeof r[pred] == "integer" && (r[pred] != 0 && r[pred] != 1))
                    throw "D5_RESPONSE_OUT_OF_BOUNDS"
            }
        }
    }

    /* -- op: radius (pure observation, zero cost) --------------------------- */
    function TerrainRadiusOp(r) {
        local radius = GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP)
        if (radius < 0 || radius > 255) throw "D5_NATIVE_FACT"
        r.radius <- radius
        r.status = "READY"
    }

    /* Map-length-half defence: the tile's x/y identity is recomputed from
     * the live map, so a stale or out-of-map index can never be observed. */
    function TerrainTileOk(tile) {
        if (!GSMap.IsValidTile(tile)) return false
        local wx = GSMap.GetMapSizeX()
        return GSMap.GetTileX(tile) == tile % wx && GSMap.GetTileY(tile) == tile / wx
    }

    /* -- op: tile (one pinned branch tile, zero cost) ------------------------ */
    function TerrainTileOp(q, r) {
        if (!TilePinned(q.tile)) {
            r.status = "INVALID_LOCATION"
            return
        }
        if (!TerrainTileOk(q.tile)) throw "D5_NATIVE_FACT"
        r.tile <- q.tile
        r.slope <- GSTile.GetSlope(q.tile)
        r.min_height <- GSTile.GetMinHeight(q.tile)
        r.max_height <- GSTile.GetMaxHeight(q.tile)
        r.buildable <- GSTile.IsBuildable(q.tile)
        r.owner <- GSTile.GetOwner(q.tile)
        r.tree <- GSTile.HasTreeOnTile(q.tile)
        r.water <- GSTile.IsWaterTile(q.tile)
        r.coast <- GSTile.IsCoastTile(q.tile)
        r.farm <- GSTile.IsFarmTile(q.tile)
        r.rock <- GSTile.IsRockTile(q.tile)
        r.rough <- GSTile.IsRoughTile(q.tile)
        r.road <- GSTile.HasTransportType(q.tile, GSTile.TRANSPORT_ROAD)
        r.rail <- GSTile.HasTransportType(q.tile, GSTile.TRANSPORT_RAIL)
        r.water_transport <- GSTile.HasTransportType(q.tile, GSTile.TRANSPORT_WATER)
        r.air_transport <- GSTile.HasTransportType(q.tile, GSTile.TRANSPORT_AIR)
        r.status = "READY"
    }

    /* -- op: accept (one pinned control/acceptance tile, zero cost) ---------- */
    function TerrainAcceptOp(q, r) {
        if (!TerrainAcceptPinned(q.tile)) {
            r.status = "INVALID_LOCATION"
            return
        }
        local radius = GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP)
        if (radius < 0 || radius > 255) throw "D5_NATIVE_FACT"
        local accept = GSTile.GetCargoAcceptance(q.tile, FREIGHT_CARGO, 1, 1, radius)
        if (accept < 0 || accept > 8) throw "D5_NATIVE_FACT"
        r.tile <- q.tile
        r.accept <- accept
        r.radius <- radius
        r.status = "READY"
    }

    function TerrainHandle(q) {
        if (!("op" in q) || typeof q.op != "string" || !TerrainOpAllowed(q.op)) return
        if (!("request_id" in q) || typeof q.request_id != "string" ||
            q.request_id.len() < 1 || q.request_id.len() > 32 ||
            !IdShape(q.request_id)) return
        if (!("plan" in q) || typeof q.plan != "string" || !Hex64(q.plan)) return
        if (!("company" in q) || typeof q.company != "integer" ||
            q.company < 0 || q.company > 14) return
        if (!("max_cost" in q) || typeof q.max_cost != "integer" || q.max_cost != 0) return
        if (!("pickup" in q) || typeof q.pickup != "integer" ||
            q.pickup < 0 || q.pickup > 65535 ||
            !("delivery" in q) || typeof q.delivery != "integer" ||
            q.delivery < 0 || q.delivery > 65535 ||
            !("depot" in q) || typeof q.depot != "integer" ||
            q.depot < 0 || q.depot > 65535 ||
            q.pickup == q.delivery || q.depot == q.pickup ||
            q.depot == q.delivery) return
        /* tile is required (an integer in map bounds) on the tile and accept
         * ops exactly and null on radius — the wire serializes its absence. */
        if (!("tile" in q)) return
        if (q.op == "radius") {
            if (q.tile != null) return
        } else {
            if (typeof q.tile != "integer" || q.tile < 0 || q.tile > 65535) return
        }
        /* Shared one-shot budget accounting across all three protocols:
         * unique request ids, the same 32-request cap; a duplicate id or an
         * exhausted budget is silently dropped. */
        if (used == null) used = {}
        if (q.request_id in used || this.requests >= this.max_requests) return
        used[q.request_id] <- true
        this.requests++
        local r = {
            protocol = 7, op = q.op, request_id = q.request_id, plan = q.plan,
            company = q.company, max_cost = q.max_cost, pickup = q.pickup,
            delivery = q.delivery, depot = q.depot, status = "OUT_OF_ORDER",
            funds = 0, cost = 0
        }
        if (q.op != "radius") r.tile <- q.tile
        local idx = TerrainPlannedIndex(q)
        if (idx < 0 || idx != this.terrain_stage || this.terrain_halted) {
            r.status = "OUT_OF_ORDER"
        } else if (this.plan_id != null && this.plan_id != q.plan) {
            r.status = "OUT_OF_ORDER"
        } else if (GSCompany.ResolveCompanyID(q.company) != q.company ||
                   q.company != FREIGHT_COMPANY) {
            r.status = "INVALID_COMPANY"
        } else if (q.pickup != this.pickup || q.delivery != this.delivery ||
                   q.depot != this.depot_tile) {
            r.status = "STALE_PIN"
        } else {
            if (this.plan_id == null) this.plan_id = q.plan
            if (GSGame.IsPaused()) {
                r.status = "PAUSED"
            } else {
                try {
                    local company = GSCompanyMode(q.company)
                    if (!GSCompanyMode.IsValid()) {
                        r.status = "INVALID_COMPANY"
                    } else {
                        /* Every terrain-survey reply carries the bank
                         * balance at the exchange boundary (recorded, never
                         * changed: the survey has no cost-bearing op). */
                        r.funds = GSCompany.GetBankBalance(q.company)
                        if (q.op == "radius") {
                            TerrainRadiusOp(r)
                        } else if (q.op == "tile") {
                            TerrainTileOp(q, r)
                        } else {
                            TerrainAcceptOp(q, r)
                        }
                    }
                } catch (error) {
                    r.status = "UNSUPPORTED_NATIVE_FACT"
                }
            }
        }
        if (q.op == "tile" && r.status == "READY") TerrainFactNorm(r)
        TerrainGuard(r)
        if (!GSAdmin.Send(r)) throw "D5_RESPONSE_SEND_FAILED"
        GSLog.Info("D5_TERRAIN " + q.request_id + " " + r.status)
        /* Terrain schedule accounting: only the exact READY status of the
         * planned exchange advances the terrain stage; every other terminal
         * status halts the terrain prefix-preservingly. Evidence, never
         * retries. The freight (protocol 5) and acceptance-survey
         * (protocol 6) accounting below stays untouched. */
        if (idx >= 0) {
            if (r.status == terrain_planned[idx][2]) {
                if (idx == this.terrain_stage && !this.terrain_halted) {
                    this.terrain_stage = idx + 1
                }
            } else {
                this.terrain_halted = true
            }
        }
    }

    function OpAllowed(op) {
        return op == "site" || op == "engine" || op == "purchase" ||
            op == "vread" || op == "order" || op == "order-read" ||
            op == "monitor" || op == "start" || op == "load-watch" ||
            op == "transit-watch" || op == "deliver-watch" ||
            op == "finance" || op == "finish"
    }

    function Hex64(s) {
        if (s.len() != 64) return false
        for (local i = 0; i < 64; i++) {
            local c = s[i]
            if (!((c >= 48 && c <= 57) || (c >= 97 && c <= 102))) return false
        }
        return true
    }

    function IdShape(s) {
        for (local i = 0; i < s.len(); i++) {
            local c = s[i]
            if (!(c == 45 || (c >= 48 && c <= 57) || (c >= 97 && c <= 122)))
                return false
        }
        return true
    }

    function Adjacent(a, b) {
        local wx = GSMap.GetMapSizeX()
        local ax = a % wx
        local ay = a / wx
        local bx = b % wx
        local by = b / wx
        return (ax == bx && (ay == by + 1 || ay == by - 1)) ||
            (ay == by && (ax == bx + 1 || ax == bx - 1))
    }

    /* Validate the optimizer-selected route before latching any of it. The
     * same invariants the Python wire contract checks: 3..24 unique,
     * in-bounds, cardinally adjacent tiles, terminal stop match, and exactly
     * one corridor interior tile joined to the depot. */
    function RouteOk(route, pickup, delivery, depot) {
        if (typeof route != "array" || route.len() < 3 ||
            route.len() > MAX_ROUTE_TILES) return false
        local wx = GSMap.GetMapSizeX()
        local seen = {}
        for (local i = 0; i < route.len(); i++) {
            local tile = route[i]
            if (typeof tile != "integer" || tile < 0 || tile > 65535)
                return false
            if (!GSMap.IsValidTile(tile) || GSMap.GetTileX(tile) != tile % wx ||
                GSMap.GetTileY(tile) != tile / wx) return false
            if (tile in seen) return false
            seen[tile] <- true
            if (i > 0 && !Adjacent(route[i - 1], tile)) return false
        }
        if (route[0] != pickup || route[route.len() - 1] != delivery)
            return false
        if (depot in seen) return false
        local fronts = 0
        for (local i = 1; i + 1 < route.len(); i++)
            if (Adjacent(depot, route[i])) fronts++
        return fronts == 1
    }

    /* Latch the validated route and its derived fronts atomically. */
    function LatchRoute(q) {
        this.pickup = q.pickup
        this.pickup_front = q.route[1]
        this.delivery = q.delivery
        this.delivery_front = q.route[q.route.len() - 2]
        this.depot_tile = q.depot
        this.depot_front = -1
        for (local i = 1; i + 1 < q.route.len(); i++)
            if (Adjacent(q.depot, q.route[i])) this.depot_front = q.route[i]
        this.witness = []
        foreach (tile in q.route) this.witness.append(tile)
        this.route_digest = q.route_digest
    }

    /* Per-op request echo coherence, mirroring the Python validator's
     * quiet/pitched rules exactly; any incoherence is a malformed request
     * the dispatcher silently drops. */
    function EchoOk(q) {
        if (typeof q.engine != "integer" || q.engine < -1 || q.engine > 65535)
            return false
        if (typeof q.vehicle != "integer" || q.vehicle < -1 || q.vehicle > 65535)
            return false
        if (typeof q.expected_cost != "integer" || q.expected_cost < 0 ||
            q.expected_cost > 2147483647) return false
        if (typeof q.order_index != "integer" || q.order_index < -1 ||
            q.order_index > 1) return false
        if (typeof q.watch_ticks != "integer" || q.watch_ticks < -1 ||
            q.watch_ticks > MAX_TICKS) return false
        if (typeof q.watch_days != "integer" || q.watch_days < -1 ||
            q.watch_days > MAX_DAYS) return false
        local quiet = q.expected_cost == 0 && q.order_index == -1 &&
            q.watch_ticks == -1 && q.watch_days == -1
        local pitched = q.engine >= 0 && q.vehicle >= 0
        if (q.op == "site" || q.op == "engine")
            return q.engine == -1 && q.vehicle == -1 && quiet
        if (q.op == "purchase")
            return q.engine >= 0 && q.vehicle == -1 &&
                q.order_index == -1 && q.watch_ticks == -1 &&
                q.watch_days == -1 && q.expected_cost > 0 &&
                q.expected_cost <= q.max_cost
        if (q.op == "vread" || q.op == "order-read" || q.op == "monitor" ||
            q.op == "start" || q.op == "finance" || q.op == "finish")
            return pitched && quiet
        if (q.op == "order")
            return pitched &&
                (q.order_index == 0 || q.order_index == 1) &&
                q.expected_cost == 0 && q.watch_ticks == -1 &&
                q.watch_days == -1
        if (q.op == "load-watch")
            return pitched && q.order_index == -1 && q.expected_cost == 0 &&
                q.watch_ticks >= 1 && q.watch_days >= 1
        /* transit-watch / deliver-watch */
        return pitched && q.order_index == -1 && q.expected_cost == 0 &&
            q.watch_ticks >= 1 && q.watch_days == -1
    }

    function ObserveStop(tile, front, company) {
        local wx = GSMap.GetMapSizeX()
        if (!GSMap.IsValidTile(tile) || GSMap.GetTileX(tile) != tile % wx ||
            GSMap.GetTileY(tile) != tile / wx) throw "D5_NATIVE_FACT"
        if (!GSMap.IsValidTile(front) || GSMap.GetTileX(front) != front % wx ||
            GSMap.GetTileY(front) != front / wx) throw "D5_NATIVE_FACT"
        local stop_tile = GSRoad.IsRoadStationTile(tile)
        local drive_through = stop_tile && GSRoad.IsDriveThroughRoadStationTile(tile)
        local sid = stop_tile ? GSStation.GetStationID(tile) : -1
        local truck = stop_tile && !drive_through && GSStation.IsValidStation(sid) &&
            GSStation.HasStationType(sid, GSStation.STATION_TRUCK_STOP) &&
            !GSStation.HasStationType(sid, GSStation.STATION_BUS_STOP)
        local linked = stop_tile && GSStation.IsValidStation(sid) &&
            !drive_through && GSRoad.GetRoadStationFrontTile(tile) == front
        return {
            stop = stop_tile,
            truck = truck,
            sid = sid,
            linked = linked,
            owner = GSTile.GetOwner(tile),
            front_owner = GSTile.GetOwner(front),
            funds = GSCompany.GetBankBalance(company)
        }
    }

    function ObserveDepot(company) {
        local wx = GSMap.GetMapSizeX()
        if (!GSMap.IsValidTile(this.depot_tile) ||
            GSMap.GetTileX(this.depot_tile) != this.depot_tile % wx ||
            GSMap.GetTileY(this.depot_tile) != this.depot_tile / wx) throw "D5_NATIVE_FACT"
        local depot = GSRoad.IsRoadDepotTile(this.depot_tile)
        local front_id = depot ? GSRoad.GetRoadDepotFrontTile(this.depot_tile) : -1
        return {
            depot = depot,
            front_id = front_id,
            owner = depot ? GSTile.GetOwner(this.depot_tile) : GSCompany.COMPANY_INVALID,
            linked = depot && front_id == this.depot_front &&
                GSTile.GetOwner(this.depot_tile) == company &&
                GSTile.GetOwner(this.depot_front) == company &&
                GSRoad.IsRoadTile(this.depot_front)
        }
    }

    /* Witness re-check: every adjacent pair along the ordered path must be
     * joined by this company's road. Pure observation; the stops attach
     * through their fronts, which lie on the path itself. */
    function Witness(company) {
        local pairs_ok = 0
        local pair_total = this.witness.len() - 1
        local wx = GSMap.GetMapSizeX()
        for (local i = 1; i < this.witness.len(); i++) {
            local a = this.witness[i - 1]
            local b = this.witness[i]
            if (!GSMap.IsValidTile(a) || GSMap.GetTileX(a) != a % wx ||
                GSMap.GetTileY(a) != a / wx) throw "D5_NATIVE_FACT"
            if (!GSMap.IsValidTile(b) || GSMap.GetTileX(b) != b % wx ||
                GSMap.GetTileY(b) != b / wx) throw "D5_NATIVE_FACT"
            local joined = GSRoad.AreRoadTilesConnected(a, b) &&
                GSRoad.AreRoadTilesConnected(b, a) &&
                GSTile.GetOwner(a) == company && GSTile.GetOwner(b) == company
            if (joined) pairs_ok++
        }
        return {pairs_ok = pairs_ok, pair_total = pair_total}
    }

    /* The live vehicle position inside the ordered witness path, or -1 when
     * it stands anywhere else. */
    function WitnessIndex(tile) {
        for (local i = 0; i < this.witness.len(); i++)
            if (this.witness[i] == tile) return i
        return -1
    }

    /* Compatible buildable road truck engine predicate for the corridor
     * cargo, identical to the proven lifecycle kernel: default cargo IS the
     * corridor cargo, no refit exists in this machinery. */
    function Compatible(e) {
        return GSEngine.IsBuildable(e) && GSEngine.IsValidEngine(e) &&
            GSEngine.GetVehicleType(e) == GSVehicle.VT_ROAD &&
            !GSEngine.IsArticulated(e) &&
            GSEngine.CanRunOnRoad(e, 0) && GSEngine.HasPowerOnRoad(e, 0) &&
            GSCargo.IsValidCargo(GSEngine.GetCargoType(e)) &&
            GSEngine.GetCargoType(e) == FREIGHT_CARGO &&
            GSRoad.GetRoadVehicleTypeForCargo(GSEngine.GetCargoType(e)) ==
                GSRoad.ROADVEHTYPE_TRUCK &&
            GSEngine.CanRefitCargo(e, GSEngine.GetCargoType(e)) &&
            GSEngine.GetCapacity(e) > 0
    }

    /* One tested native quote for one engine at the depot: the fixed-demo
     * test-mode pattern (BuildVehicle answers 0 on success in test mode,
     * any other value on failure). */
    function QuoteBuild(engine) {
        local accounting = GSAccounting()
        local testing = GSTestMode()
        local value = GSVehicle.BuildVehicle(this.depot_tile, engine)
        local cost = accounting.GetCosts()
        testing = null
        accounting = null
        return [value == 0, cost]
    }

    /* The live vehicle's report, read natively. The cargo slot is the
     * admitted corridor cargo: a vehicle carrying any other cargo reads
     * capacity 0 there and the windows refuse on that capacity. */
    function VState(company) {
        local v = vehicle_id
        return {
            owner = GSVehicle.GetOwner(v),
            engine = GSVehicle.GetEngineType(v),
            location = GSVehicle.GetLocation(v),
            capacity = GSVehicle.GetCapacity(v, FREIGHT_CARGO),
            state_int = GSVehicle.GetState(v),
            in_depot = GSVehicle.IsInDepot(v),
            speed = GSVehicle.GetCurrentSpeed(v),
            load = GSVehicle.GetCargoLoad(v, FREIGHT_CARGO),
            funds = GSCompany.GetBankBalance(company)
        }
    }

    function StateName(s) {
        if (s == GSVehicle.VS_IN_DEPOT) return "IN_DEPOT"
        if (s == GSVehicle.VS_RUNNING) return "RUNNING"
        if (s == GSVehicle.VS_AT_STATION) return "AT_STATION"
        if (s == GSVehicle.VS_STOPPED) return "STOPPED"
        if (s == GSVehicle.VS_BROKEN) return "BROKEN"
        if (s == GSVehicle.VS_CRASHED) return "CRASHED"
        return "INVALID"
    }

    /* The live vehicle identity check every post-purchase exchange makes
     * against the latched engine and vehicle. */
    function VehicleReady(q) {
        return this.vehicle_id >= 0 &&
            GSVehicle.IsValidVehicle(this.vehicle_id) &&
            GSVehicle.IsPrimaryVehicle(this.vehicle_id) &&
            GSVehicle.GetOwner(this.vehicle_id) == q.company &&
            q.engine == this.engine_id && q.vehicle == this.vehicle_id &&
            q.pickup == this.pickup && q.delivery == this.delivery &&
            q.depot == this.depot_tile
    }

    /* -- op: site admission (pure observation, zero cost) ------------------- */
    function SiteOp(q, r) {
        local obs = null
        try {
            local paused = GSGame.IsPaused()
            local pup = ObserveStop(this.pickup, this.pickup_front, q.company)
            local del = ObserveStop(this.delivery, this.delivery_front, q.company)
            local dep = ObserveDepot(q.company)
            local wit = Witness(q.company)
            local fleet = 0
            local list = GSVehicleList()
            for (local i = list.Begin(); !list.IsEnd(); i = list.Next())
                if (GSVehicle.IsValidVehicle(i) && GSVehicle.IsPrimaryVehicle(i) &&
                    GSVehicle.GetOwner(i) == q.company) fleet++
            obs = {
                paused = paused, pup = pup, del = del, depot = dep,
                wit = wit, fleet = fleet
            }
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
            return
        }
        r.funds = obs.pup.funds
        if (obs.paused) {
            r.status = "PAUSED"
        } else if (!obs.pup.stop || !obs.pup.truck || obs.pup.sid < 0 ||
                   !obs.pup.linked || obs.pup.owner != q.company) {
            r.status = "INVALID_SITE"
        } else if (!obs.del.stop || !obs.del.truck || obs.del.sid < 0 ||
                   obs.del.sid == obs.pup.sid || !obs.del.linked ||
                   obs.del.owner != q.company) {
            r.status = "INVALID_SITE"
        } else if (!obs.depot.depot || obs.depot.owner != q.company ||
                   obs.depot.front_id != this.depot_front || !obs.depot.linked) {
            r.status = "INVALID_SITE"
        } else if (obs.wit.pairs_ok != obs.wit.pair_total) {
            r.status = "INVALID_SITE"
        } else if (obs.fleet != 0) {
            /* A D5 site admits only a company with zero vehicles. This
             * refusal is issued before any observation field attaches, so
             * the reply keeps the contract's refusal shape (a refusal
             * readback carries no observation set). */
            r.status = "INVALID_SITE"
        } else {
            /* The acceptance fact is the proven catchment predicate over the
             * delivery stop tile (0..8 eighths). The production and waiting
             * levels are reported as facts; they gate the honest load
             * window later, not admission. */
            try {
                local radius = GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP)
                if (radius < 0) throw "D5_NATIVE_FACT"
                local accept = GSTile.GetCargoAcceptance(this.delivery, FREIGHT_CARGO, 1, 1, radius)
                local production = GSIndustry.GetLastMonthProduction(PICKUP_INDUSTRY, FREIGHT_CARGO)
                local waiting = GSStation.GetCargoWaiting(obs.pup.sid, FREIGHT_CARGO)
                if (accept < 0 || accept > 8 || production < 0 || waiting < 0)
                    throw "D5_NATIVE_FACT"
                r.paused <- obs.paused
                r.truck0 <- obs.pup.truck
                r.sid0 <- obs.pup.sid
                r.truck1 <- obs.del.truck
                r.sid1 <- obs.del.sid
                r.depot_ok <- obs.depot.depot && obs.depot.linked
                r.owner <- obs.depot.owner
                r.pairs_ok <- obs.wit.pairs_ok
                r.pair_total <- obs.wit.pair_total
                r.accept <- accept
                r.prod <- production
                r.wait <- waiting
                r.vehicles <- obs.fleet
                r.status = "READY"
                this.site_sid0 = obs.pup.sid
                this.site_sid1 = obs.del.sid
                this.site_waiting = waiting
                this.site_production = production
            } catch (error) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
            }
        }
    }

    /* -- op: engine enumeration + admission (observation + one test quote) -- */
    function EngineOp(q, r) {
        if (GSGame.IsPaused()) {
            r.status = "PAUSED"
            return
        }
        try {
            local list = GSEngineList(GSVehicle.VT_ROAD)
            local count = 0
            local best = -1
            for (local e = list.Begin(); !list.IsEnd(); e = list.Next()) {
                count++
                if (count > 32) break
                if (Compatible(e) && (best == -1 || e < best)) best = e
            }
            if (count > 32) {
                r.status = "ENGINE_LIMIT"
                return
            }
            if (best == -1) {
                r.status = "NO_ENGINE"
                return
            }
            local funds = GSCompany.GetBankBalance(q.company)
            r.funds = funds
            if (!GSEngine.IsBuildable(best)) {
                r.status = "UNAVAILABLE_ENGINE"
                return
            }
            local tested = QuoteBuild(best)
            if (!tested[0] || tested[1] <= 0) {
                r.status = "UNAVAILABLE_ENGINE"
                return
            }
            /* The engine reply's tested quote must equal the engine's own
             * price: a differently priced world is refused outright. */
            if (tested[1] != GSEngine.GetPrice(best)) {
                r.status = "COST_CHANGED"
                return
            }
            if (tested[1] > q.max_cost) {
                r.status = "COST_LIMIT"
                return
            }
            if (funds < tested[1]) {
                r.status = "INSUFFICIENT_FUNDS"
                return
            }
            local capacity = GSEngine.GetCapacity(best)
            r.available <- true
            r.compatible <- true
            r.capacity <- capacity
            r.cargo <- FREIGHT_CARGO
            r.engine = best
            r.cost = tested[1]
            r.status = "READY"
            this.engine_id = best
            this.engine_capacity = capacity
            this.engine_quote = tested[1]
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- op: purchase (one test-equal re-quote, one real BuildVehicle) ------ */
    function PurchaseOp(q, r) {
        if (GSGame.IsPaused()) {
            r.status = "PAUSED"
            return
        }
        if (this.engine_id < 0 || this.site_sid0 < 0 || this.site_sid1 < 0 ||
            q.engine != this.engine_id || q.expected_cost != this.engine_quote) {
            r.status = "STALE_ADMISSION"
            return
        }
        try {
            local funds = GSCompany.GetBankBalance(q.company)
            r.funds = funds
            local quote = QuoteBuild(q.engine)
            if (!quote[0] || quote[1] <= 0) {
                r.status = "UNAVAILABLE_ENGINE"
                return
            }
            if (quote[1] != q.expected_cost || quote[1] > q.max_cost) {
                r.status = "COST_CHANGED"
                return
            }
            if (funds < quote[1]) {
                r.status = "INSUFFICIENT_FUNDS"
                return
            }
            /* The one real build command: accounting around it records the
             * realized cost; BuildVehicle answers the new VehicleID. */
            local accounting = GSAccounting()
            local built = GSVehicle.BuildVehicle(this.depot_tile, q.engine)
            local cost = accounting.GetCosts()
            accounting = null
            if (!GSVehicle.IsValidVehicle(built)) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
                return
            }
            if (cost != quote[1]) {
                r.status = "COST_CHANGED"
                return
            }
            local after = GSCompany.GetBankBalance(q.company)
            if (funds - after != cost) {
                r.status = "READBACK_MISMATCH"
                return
            }
            r.funds = after
            r.cost = cost
            r.vehicle = built
            r.status = "BUILT"
            this.vehicle_id = built
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- op: independent vehicle readback (pure observation, zero cost) ----- */
    function VReadOp(q, r) {
        if (!VehicleReady(q)) {
            r.status = "STALE_ADMISSION"
            return
        }
        try {
            local obs = VState(q.company)
            if (obs.owner != q.company || obs.capacity < 0 || obs.speed < 0 ||
                obs.load < 0 || obs.in_depot == null) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
                return
            }
            r.funds = obs.funds
            r.owner <- obs.owner
            r.location <- obs.location
            r.capacity <- obs.capacity
            r.cargo <- FREIGHT_CARGO
            r.state <- StateName(obs.state_int)
            r.in_depot <- obs.in_depot
            r.speed <- obs.speed
            r.status = "READ"
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- op: order appends (station ids from the site readback, pinned flags) */
    function OrderOp(q, r) {
        if (GSGame.IsPaused()) {
            r.status = "PAUSED"
            return
        }
        if (!VehicleReady(q)) {
            r.status = "STALE_ADMISSION"
            return
        }
        local dest = q.order_index == 0 ? this.site_sid0 : this.site_sid1
        if (dest < 0) {
            r.status = "STALE_ADMISSION"
            return
        }
        try {
            /* Stopped-style preconditions: the vehicle reads stopped in its
             * building depot and the order list is exactly this index long. */
            if (!GSVehicle.IsInDepot(this.vehicle_id) ||
                GSOrder.GetOrderCount(this.vehicle_id) != q.order_index) {
                r.status = "STALE_ADMISSION"
                return
            }
            local flags = q.order_index == 0 ? GSOrder.OF_FULL_LOAD : GSOrder.OF_NO_LOAD
            if (!GSOrder.AreOrderFlagsValid(flags) ||
                !GSOrder.AppendOrder(this.vehicle_id, dest, flags)) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
                return
            }
            local d = GSOrder.GetOrderDestination(this.vehicle_id, q.order_index)
            local f = GSOrder.GetOrderFlags(this.vehicle_id, q.order_index)
            local g = GSOrder.IsGotoStationOrder(this.vehicle_id, q.order_index)
            if (d != dest || f != flags || g != true) {
                r.status = "READBACK_MISMATCH"
                return
            }
            r.dest <- d
            r.flags <- f
            r.goto <- g
            r.status = "ORDERED"
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- op: exact order inventory ------------------------------------------ */
    function OrderReadOp(q, r) {
        if (!VehicleReady(q)) {
            r.status = "STALE_ADMISSION"
            return
        }
        try {
            local count = GSOrder.GetOrderCount(this.vehicle_id)
            if (count != 2) {
                r.status = "READBACK_MISMATCH"
                return
            }
            local d0 = GSOrder.GetOrderDestination(this.vehicle_id, 0)
            local f0 = GSOrder.GetOrderFlags(this.vehicle_id, 0)
            local g0 = GSOrder.IsGotoStationOrder(this.vehicle_id, 0)
            local d1 = GSOrder.GetOrderDestination(this.vehicle_id, 1)
            local f1 = GSOrder.GetOrderFlags(this.vehicle_id, 1)
            local g1 = GSOrder.IsGotoStationOrder(this.vehicle_id, 1)
            if (d0 != this.site_sid0 || f0 != GSOrder.OF_FULL_LOAD || g0 != true ||
                d1 != this.site_sid1 || f1 != GSOrder.OF_NO_LOAD || g1 != true) {
                r.status = "READBACK_MISMATCH"
                return
            }
            r.order_len <- count
            r.dest0 <- d0
            r.flags0 <- f0
            r.goto0 <- g0
            r.dest1 <- d1
            r.flags1 <- f1
            r.goto1 <- g1
            r.status = "ORDER_SET_VERIFIED"
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- op: pre-start monitor arming (keep_monitoring=true, zero baseline) -- */
    function MonitorOp(q, r) {
        if (GSGame.IsPaused()) {
            r.status = "PAUSED"
            return
        }
        if (!VehicleReady(q)) {
            r.status = "STALE_ADMISSION"
            return
        }
        try {
            local pickup = GSCargoMonitor.GetIndustryPickupAmount(
                q.company, FREIGHT_CARGO, PICKUP_INDUSTRY, true)
            local delivery = GSCargoMonitor.GetIndustryDeliveryAmount(
                q.company, FREIGHT_CARGO, DELIVERY_INDUSTRY, true)
            local income = GSCompany.GetQuarterlyIncome(q.company, GSCompany.CURRENT_QUARTER)
            local delivered = GSCompany.GetQuarterlyCargoDelivered(q.company, GSCompany.CURRENT_QUARTER)
            if (pickup < 0 || delivery < 0 || delivered < 0 ||
                income < -2147483648 || income > 2147483647) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
                return
            }
            if (pickup != 0 || delivery != 0) {
                /* A nonzero pre-start monitor baseline is a refused
                 * observation set, never a claimed ARMED state. */
                r.status = "READBACK_MISMATCH"
                return
            }
            r.pickup_amount <- pickup
            r.delivery_amount <- delivery
            r.income <- income
            r.delivered <- delivered
            r.status = "ARMED"
            this.monitor_armed = true
            this.armed_income = income
            this.armed_delivered = delivered
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- op: start ---------------------------------------------------------- */
    function StartOp(q, r) {
        if (GSGame.IsPaused()) {
            r.status = "PAUSED"
            return
        }
        if (!VehicleReady(q)) {
            r.status = "STALE_ADMISSION"
            return
        }
        try {
            if (!GSVehicle.StartStopVehicle(this.vehicle_id)) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
                return
            }
            local state = StateName(GSVehicle.GetState(this.vehicle_id))
            local speed = GSVehicle.GetCurrentSpeed(this.vehicle_id)
            if (state != "RUNNING" || speed < 0) {
                r.status = "READBACK_MISMATCH"
                return
            }
            r.state <- state
            r.speed <- speed
            r.status = "STARTED"
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- watch window helpers ------------------------------------------------ */
    function WindowCaps(q) {
        local cap_t = q.watch_ticks < MAX_TICKS ? q.watch_ticks : MAX_TICKS
        /* transit/deliver windows carry no day echo (-1); they are bounded by
         * the module day cap, not by a nonsensical negative budget. */
        local cap_d = q.watch_days < 0 ? MAX_DAYS :
            (q.watch_days < MAX_DAYS ? q.watch_days : MAX_DAYS)
        return [cap_t, cap_d]
    }

    /* -- op: load-watch (window 1: one positive full cargo load) ------------- */
    function LoadWatch(q, r) {
        if (!VehicleReady(q)) {
            r.status = "STALE_ADMISSION"
            return
        }
        try {
            local caps = WindowCaps(q)
            local cap_t = caps[0]
            local cap_d = caps[1]
            local capacity = GSVehicle.GetCapacity(this.vehicle_id, FREIGHT_CARGO)
            if (capacity != this.engine_capacity) {
                r.status = "READBACK_MISMATCH"
                return
            }
            local prev = GetTick()
            local started_day = GSDate.GetCurrentDate()
            if (started_day < 0) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
                return
            }
            local samples = 0
            for (;;) {
                /* Pause is refused on every sample (fail-closed, first
                 * sample included); the clock sanity follows only real
                 * sleeps: a regression or a non-advancing tick is stalled. */
                if (GSGame.IsPaused()) {
                    r.status = "PAUSED"
                    return
                }
                if (samples > 0) {
                    Sleep(1)
                    local now = GetTick()
                    if (now <= prev) {
                        r.tick <- now
                        r.day <- GSDate.GetCurrentDate()
                        r.status = "CLOCK_STALLED"
                        return
                    }
                    prev = now
                }
                local day = GSDate.GetCurrentDate()
                if (day - started_day >= cap_d) {
                    r.tick <- prev
                    r.day <- day
                    r.status = "WINDOW_EXHAUSTED"
                    return
                }
                local load = GSVehicle.GetCargoLoad(this.vehicle_id, FREIGHT_CARGO)
                if (load < 0) {
                    r.status = "UNSUPPORTED_NATIVE_FACT"
                    return
                }
                if (load > 0 && load == capacity) {
                    local wait = GSStation.GetCargoWaiting(this.site_sid0, FREIGHT_CARGO)
                    if (wait < 0) {
                        r.status = "UNSUPPORTED_NATIVE_FACT"
                        return
                    }
                    r.paused <- false
                    r.load <- load
                    r.capacity <- capacity
                    r.wait <- wait
                    r.tick <- prev
                    r.day <- day
                    r.status = "LOADED"
                    this.observed_load = load
                    return
                }
                samples++
                if (samples > cap_t) {
                    r.tick <- prev
                    r.day <- day
                    r.status = "WINDOW_EXHAUSTED"
                    return
                }
            }
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- op: transit-watch (window 2: the ordered witness walk to delivery) -- */
    function TransitWatch(q, r) {
        if (!VehicleReady(q)) {
            r.status = "STALE_ADMISSION"
            return
        }
        try {
            local caps = WindowCaps(q)
            local cap_t = caps[0]
            local cap_d = caps[1]
            local capacity = GSVehicle.GetCapacity(this.vehicle_id, FREIGHT_CARGO)
            if (capacity != this.engine_capacity) {
                r.status = "READBACK_MISMATCH"
                return
            }
            local prev = GetTick()
            local started_day = GSDate.GetCurrentDate()
            if (started_day < 0) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
                return
            }
            local samples = 0
            local last_progress = -1
            for (;;) {
                if (GSGame.IsPaused()) {
                    r.status = "PAUSED"
                    return
                }
                if (samples > 0) {
                    Sleep(1)
                    local now = GetTick()
                    if (now <= prev) {
                        r.tick <- now
                        r.day <- GSDate.GetCurrentDate()
                        r.status = "CLOCK_STALLED"
                        return
                    }
                    prev = now
                }
                local day = GSDate.GetCurrentDate()
                if (day - started_day >= cap_d) {
                    r.tick <- prev
                    r.day <- day
                    r.status = "WINDOW_EXHAUSTED"
                    return
                }
                local loc = GSVehicle.GetLocation(this.vehicle_id)
                /* Pre-departure observation: the vehicle stands in the pinned
                 * depot (off the ordered witness path by construction) until
                 * it leaves; that is waiting, not a routing defect. Any other
                 * off-witness tile is a typed INVALID_ROUTE: the vehicle
                 * drove where the corridor receipt never built road. */
                if (loc != this.depot_tile && WitnessIndex(loc) < 0) {
                    r.status = "INVALID_ROUTE"
                    return
                }
                local progress = WitnessIndex(loc)
                /* Sampled-direction monotonicity: this window's samples may
                 * only advance along the ordered witness. A sample behind an
                 * earlier one is a backward drive (or a revisit) the corridor
                 * receipt never describes: typed INVALID_ROUTE, fail-closed.
                 * This is sampled evidence, not tile-by-tile continuity. */
                if (progress >= 0) {
                    if (last_progress >= 0 && progress < last_progress) {
                        r.status = "INVALID_ROUTE"
                        return
                    }
                    last_progress = progress
                }
                local load = GSVehicle.GetCargoLoad(this.vehicle_id, FREIGHT_CARGO)
                if (load < 0) {
                    r.status = "UNSUPPORTED_NATIVE_FACT"
                    return
                }
                if (loc == this.delivery && load > 0 && load == capacity) {
                    r.paused <- false
                    r.position <- loc
                    r.progress <- progress
                    r.load <- load
                    r.tick <- prev
                    r.day <- day
                    r.status = "AT_DELIVERY"
                    return
                }
                samples++
                if (samples > cap_t) {
                    r.tick <- prev
                    r.day <- day
                    if (progress >= 0) r.progress <- progress
                    r.status = "WINDOW_EXHAUSTED"
                    return
                }
            }
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- op: deliver-watch (window 3: unload + monitor arithmetic) ----------- */
    function DeliverWatch(q, r) {
        if (!VehicleReady(q)) {
            r.status = "STALE_ADMISSION"
            return
        }
        try {
            local caps = WindowCaps(q)
            local cap_t = caps[0]
            local cap_d = caps[1]
            local prev = GetTick()
            local started_day = GSDate.GetCurrentDate()
            if (started_day < 0) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
                return
            }
            local samples = 0
            for (;;) {
                if (GSGame.IsPaused()) {
                    r.status = "PAUSED"
                    return
                }
                if (samples > 0) {
                    Sleep(1)
                    local now = GetTick()
                    if (now <= prev) {
                        r.tick <- now
                        r.day <- GSDate.GetCurrentDate()
                        r.status = "CLOCK_STALLED"
                        return
                    }
                    prev = now
                }
                local day = GSDate.GetCurrentDate()
                if (day - started_day >= cap_d) {
                    r.tick <- prev
                    r.day <- day
                    r.status = "WINDOW_EXHAUSTED"
                    return
                }
                local load = GSVehicle.GetCargoLoad(this.vehicle_id, FREIGHT_CARGO)
                if (load < 0) {
                    r.status = "UNSUPPORTED_NATIVE_FACT"
                    return
                }
                if (load == 0) {
                    local pickup = GSCargoMonitor.GetIndustryPickupAmount(
                        q.company, FREIGHT_CARGO, PICKUP_INDUSTRY, true)
                    local delivery = GSCargoMonitor.GetIndustryDeliveryAmount(
                        q.company, FREIGHT_CARGO, DELIVERY_INDUSTRY, true)
                    if (pickup < 0 || delivery < 0) {
                        r.status = "UNSUPPORTED_NATIVE_FACT"
                        return
                    }
                    /* Monitor arithmetic must reconcile the observed full
                     * load exactly before anything is consumed. */
                    if (pickup != this.observed_load || delivery != this.observed_load) {
                        r.status = "READBACK_MISMATCH"
                        return
                    }
                    /* The single consumption (keep_monitoring=false) of the
                     * delivery monitor, behind the equal-readback gate: the
                     * consumed value must equal the observed amount and the
                     * re-armed monitor must read zero. */
                    local consumed = GSCargoMonitor.GetIndustryDeliveryAmount(
                        q.company, FREIGHT_CARGO, DELIVERY_INDUSTRY, false)
                    local recheck = GSCargoMonitor.GetIndustryDeliveryAmount(
                        q.company, FREIGHT_CARGO, DELIVERY_INDUSTRY, true)
                    if (consumed != this.observed_load || recheck != 0) {
                        r.status = "READBACK_MISMATCH"
                        return
                    }
                    r.paused <- false
                    r.load <- load
                    r.pickup_amount <- pickup
                    r.delivery_amount <- delivery
                    r.tick <- prev
                    r.day <- day
                    r.status = "DELIVERED"
                    return
                }
                samples++
                if (samples > cap_t) {
                    r.tick <- prev
                    r.day <- day
                    r.status = "WINDOW_EXHAUSTED"
                    return
                }
            }
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- op: finance corroboration (quarter income/delivered/accepted) ------- */
    function FinanceOp(q, r) {
        if (!VehicleReady(q)) {
            r.status = "STALE_ADMISSION"
            return
        }
        if (!this.monitor_armed) {
            r.status = "STALE_ADMISSION"
            return
        }
        try {
            local income = GSCompany.GetQuarterlyIncome(q.company, GSCompany.CURRENT_QUARTER)
            local delivered = GSCompany.GetQuarterlyCargoDelivered(q.company, GSCompany.CURRENT_QUARTER)
            local last_accepted = GSIndustry.GetCargoLastAcceptedDate(DELIVERY_INDUSTRY, FREIGHT_CARGO)
            if (income < -2147483648 || income > 2147483647 || delivered < 0 ||
                last_accepted < -1) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
                return
            }
            r.income <- income
            r.delivered <- delivered
            r.last_accepted <- last_accepted
            r.status = "FINANCE_VERIFIED"
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- op: finish (the issued stop; the vehicle is never sold) ------------- */
    function FinishOp(q, r) {
        if (!VehicleReady(q)) {
            r.status = "STALE_ADMISSION"
            return
        }
        try {
            /* StartStopVehicle is a toggle: read the current state first and
             * stop only an un-stopped vehicle, then prove the final readback
             * stopped. An already-stopped vehicle is not commanded again and
             * reports stop_issued = false, which the Python verifier refuses
             * (an honest halt, never a claimed stop that did not happen). */
            local state = StateName(GSVehicle.GetState(this.vehicle_id))
            if (GSVehicle.GetCurrentSpeed(this.vehicle_id) < 0) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
                return
            }
            local issued = false
            if (state != "STOPPED" && state != "IN_DEPOT") {
                if (!GSVehicle.StartStopVehicle(this.vehicle_id)) {
                    r.status = "UNSUPPORTED_NATIVE_FACT"
                    return
                }
                issued = true
            }
            local in_depot = GSVehicle.IsInDepot(this.vehicle_id)
            local speed = GSVehicle.GetCurrentSpeed(this.vehicle_id)
            if (speed < 0 || in_depot == null) {
                r.status = "UNSUPPORTED_NATIVE_FACT"
                return
            }
            state = StateName(GSVehicle.GetState(this.vehicle_id))
            if (speed != 0 || (state != "STOPPED" && state != "IN_DEPOT")) {
                r.status = "READBACK_MISMATCH"
                return
            }
            r.state <- state
            r.speed <- speed
            r.in_depot <- in_depot
            r.stop_issued <- issued
            r.status = "PHASE_STOPPED"
        } catch (error) {
            r.status = "UNSUPPORTED_NATIVE_FACT"
        }
    }

    /* -- the guarded wire entry point --------------------------------------- */
    function Handle(q) {
        if (typeof q != "table") return
        if (!("protocol" in q)) return
        /* Protocol 6 is the additive read-only acceptance survey; it shares
         * only the request budget accounting with the freight schedule. */
        if (q.protocol == 6) {
            SurveyHandle(q)
            return
        }
        /* Protocol 7 is the additive read-only terrain survey; TerrainHandle
         * validates its own request shape and shares only the one-shot
         * budget accounting with the freight and survey schedules. */
        if (q.protocol == 7) {
            TerrainHandle(q)
            return
        }
        if (q.protocol != 5) return
        if (!("op" in q) || typeof q.op != "string" || !OpAllowed(q.op)) return
        if (!("request_id" in q) || typeof q.request_id != "string" ||
            q.request_id.len() < 1 || q.request_id.len() > 32 ||
            !IdShape(q.request_id)) return
        if (!("plan" in q) || typeof q.plan != "string" || !Hex64(q.plan)) return
        if (!("route_digest" in q) || typeof q.route_digest != "string" ||
            !Hex64(q.route_digest)) return
        if (!("company" in q) || typeof q.company != "integer" ||
            q.company < 0 || q.company > 14) return
        if (!("max_cost" in q) || typeof q.max_cost != "integer" ||
            q.max_cost < 0 || q.max_cost > 2147483647) return
        if (!("pickup" in q) || typeof q.pickup != "integer" ||
            q.pickup < 0 || q.pickup > 65535 ||
            !("delivery" in q) || typeof q.delivery != "integer" ||
            q.delivery < 0 || q.delivery > 65535 ||
            !("depot" in q) || typeof q.depot != "integer" ||
            q.depot < 0 || q.depot > 65535 ||
            q.pickup == q.delivery || q.depot == q.pickup ||
            q.depot == q.delivery) return
        /* The site exchange carries the optimizer-selected route. Later
         * exchanges omit it (the wire serializes the absent field as null);
         * a route on any other op is malformed at the wire layer. */
        if (q.op == "site") {
            if (!("route" in q) || typeof q.route != "array" ||
                q.route.len() < 3 || q.route.len() > MAX_ROUTE_TILES) return
        } else if (("route" in q) && q.route != null) return
        /* Every request echoes the full correlation stride. */
        if (!("engine" in q) || !("vehicle" in q) || !("expected_cost" in q) ||
            !("order_index" in q) || !("watch_ticks" in q) ||
            !("watch_days" in q)) return
        if (!EchoOk(q)) return
        /* One-shot budget accounting: unique request ids, capped count; a
         * duplicate id or an exhausted budget is silently dropped. */
        if (used == null) used = {}
        if (q.request_id in used || this.requests >= this.max_requests) return
        used[q.request_id] <- true
        this.requests++
        /* Base response: every contract-required key echoes the request
         * correlation set; per-op observation fields attach below. */
        local r = {
            protocol = 5, op = q.op, request_id = q.request_id, plan = q.plan,
            company = q.company, max_cost = q.max_cost, pickup = q.pickup,
            delivery = q.delivery, depot = q.depot,
            route_digest = q.route_digest, engine = q.engine,
            vehicle = q.vehicle, expected_cost = q.expected_cost,
            order_index = q.order_index, watch_ticks = q.watch_ticks,
            watch_days = q.watch_days, status = "OUT_OF_ORDER", funds = 0,
            cost = 0
        }
        local idx = PlannedIndex(q)
        if (idx < 0 || idx != this.stage || this.halted) {
            r.status = "OUT_OF_ORDER"
        } else if (this.plan_id != null && this.plan_id != q.plan) {
            r.status = "OUT_OF_ORDER"
        } else if (GSCompany.ResolveCompanyID(q.company) != q.company ||
                   q.company != FREIGHT_COMPANY) {
            /* Company defence-in-depth (M9): the Python plan and verifier pin
             * company FREIGHT_COMPANY; the native handler refuses any other
             * resolvable company outright, before any admission or command. */
            r.status = "INVALID_COMPANY"
        } else {
            if (this.plan_id == null) this.plan_id = q.plan
            if (q.op == "site" && !RouteOk(q.route, q.pickup, q.delivery, q.depot)) {
                r.status = "INVALID_ROUTE"
            } else if (q.op != "site" &&
                       (q.pickup != this.pickup || q.delivery != this.delivery ||
                        q.depot != this.depot_tile ||
                        this.route_digest == null || q.route_digest != this.route_digest)) {
                r.status = "STALE_ADMISSION"
            } else {
                if (q.op == "site") LatchRoute(q)
                local company = GSCompanyMode(q.company)
                if (!GSCompanyMode.IsValid()) {
                    r.status = "INVALID_COMPANY"
                } else {
                    GSRoad.SetCurrentRoadType(GSRoad.ROADTYPE_ROAD)
                    /* Per-exchange funds readback (design D5-M6): every reply
                     * carries the company balance at the exchange boundary. */
                    r.funds = GSCompany.GetBankBalance(q.company)
                    if (GSRoad.GetCurrentRoadType() != 0 || !GSRoad.IsRoadTypeAvailable(0)) {
                        r.status = "UNSUPPORTED_NATIVE_FACT"
                    } else if (q.op == "site") {
                        SiteOp(q, r)
                    } else if (q.op == "engine") {
                        EngineOp(q, r)
                    } else if (q.op == "purchase") {
                        PurchaseOp(q, r)
                    } else if (q.op == "vread") {
                        VReadOp(q, r)
                    } else if (q.op == "order") {
                        OrderOp(q, r)
                    } else if (q.op == "order-read") {
                        OrderReadOp(q, r)
                    } else if (q.op == "monitor") {
                        MonitorOp(q, r)
                    } else if (q.op == "start") {
                        StartOp(q, r)
                    } else if (q.op == "load-watch") {
                        LoadWatch(q, r)
                    } else if (q.op == "transit-watch") {
                        TransitWatch(q, r)
                    } else if (q.op == "deliver-watch") {
                        DeliverWatch(q, r)
                    } else if (q.op == "finance") {
                        FinanceOp(q, r)
                    } else if (q.op == "finish") {
                        FinishOp(q, r)
                    }
                }
                company = null
            }
        }
        Guard(r)
        if (!GSAdmin.Send(r)) throw "D5_RESPONSE_SEND_FAILED"
        GSLog.Info("D5_RESPONSE " + q.request_id + " " + r.status)
        /* Schedule accounting: only the exact planned status of the planned
         * exchange advances the stage; every other terminal status halts the
         * schedule prefix-preservingly. Evidence, never retries. */
        if (idx >= 0) {
            if (r.status == planned[idx][2]) {
                if (idx == this.stage && !this.halted) this.stage = idx + 1
            } else {
                this.halted = true
            }
        }
    }

    /* Numeric bounds keep even the largest response honest and small; the
     * largest D5 reply is the site readback (13 observation fields below the
     * protocol-5 640-byte response bound, MAX_FREIGHT_RESPONSE_BYTES). They
     * mirror the FreightReadback field bounds exactly. */
    function Guard(r) {
        if ("route_digest" in r &&
            (typeof r.route_digest != "string" || !Hex64(r.route_digest)))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if (r.funds < -2147483648 || r.funds > 2147483647 || r.cost < 0 ||
            r.cost > 2147483647) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if (r.engine < -1 || r.engine > 65535 || r.vehicle < -1 ||
            r.vehicle > 65535) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if (r.expected_cost < 0 || r.expected_cost > 2147483647 ||
            r.order_index < -1 || r.order_index > 1 ||
            r.watch_ticks < -1 || r.watch_ticks > MAX_TICKS ||
            r.watch_days < -1 || r.watch_days > MAX_DAYS)
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("paused" in r && typeof r.paused != "bool") throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("truck0" in r && typeof r.truck0 != "bool") throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("truck1" in r && typeof r.truck1 != "bool") throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("depot_ok" in r && typeof r.depot_ok != "bool") throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("available" in r && typeof r.available != "bool") throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("compatible" in r && typeof r.compatible != "bool") throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("in_depot" in r && typeof r.in_depot != "bool") throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("goto" in r && typeof r.goto != "bool") throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("goto0" in r && typeof r.goto0 != "bool") throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("goto1" in r && typeof r.goto1 != "bool") throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("stop_issued" in r && typeof r.stop_issued != "bool")
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("sid0" in r && (r.sid0 < -1 || r.sid0 > 1073741824)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("sid1" in r && (r.sid1 < -1 || r.sid1 > 1073741824)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("dest0" in r && (r.dest0 < -1 || r.dest0 > 1073741824)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("dest1" in r && (r.dest1 < -1 || r.dest1 > 1073741824)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("dest" in r && (r.dest < 0 || r.dest > 1073741824)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("owner" in r && (r.owner < -1 || r.owner > 14)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("pairs_ok" in r && (r.pairs_ok < 0 || r.pairs_ok > 48)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("pair_total" in r && (r.pair_total < 0 || r.pair_total > 48))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("accept" in r && (r.accept < 0 || r.accept > 8)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("prod" in r && (r.prod < 0 || r.prod > 2147483647)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("wait" in r && (r.wait < 0 || r.wait > 2147483647)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("vehicles" in r && (r.vehicles < 0 || r.vehicles > 2147483647))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("capacity" in r && (r.capacity < 0 || r.capacity > 2147483647))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("cargo" in r && (r.cargo < 0 || r.cargo > 63)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("location" in r && (r.location < 0 || r.location > 65535))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("state" in r && typeof r.state != "string") throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("speed" in r && (r.speed < 0 || r.speed > 2147483647)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("flags" in r && (r.flags < 0 || r.flags > 15)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("flags0" in r && (r.flags0 < 0 || r.flags0 > 15)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("flags1" in r && (r.flags1 < 0 || r.flags1 > 15)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("order_len" in r && (r.order_len < 0 || r.order_len > 65535))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("pickup_amount" in r && (r.pickup_amount < 0 || r.pickup_amount > 2147483647))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("delivery_amount" in r && (r.delivery_amount < 0 || r.delivery_amount > 2147483647))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("income" in r && (r.income < -2147483648 || r.income > 2147483647))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("delivered" in r && (r.delivered < 0 || r.delivered > 2147483647))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("load" in r && (r.load < 0 || r.load > 2147483647)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("position" in r && (r.position < 0 || r.position > 65535))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("progress" in r && (r.progress < 0 || r.progress > 47)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("tick" in r && (r.tick < 0 || r.tick > 2147483647)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("day" in r && (r.day < 0 || r.day > 2147483647)) throw "D5_RESPONSE_OUT_OF_BOUNDS"
        if ("last_accepted" in r && (r.last_accepted < -1 || r.last_accepted > 2147483647))
            throw "D5_RESPONSE_OUT_OF_BOUNDS"
    }

    function Start() {
        GSLog.Info("D5_READY")
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
class NetworkFreightProof extends D5FreightProof {
}
