/* OpenTTD 15.3 AdminPort communication only. No game-state commands. */
class NoMutationBridge extends GSController {
    /* Formal evidence never renders null through native object/debug conversion. */
    function EvidenceOptionalInt(value) {
        if (value == null) return "null";
        if (typeof value != "integer") throw "non-integer evidence scalar";
        return value.tostring();
    }

    function EvidenceBool(value) {
        if (typeof value != "bool") throw "non-boolean evidence scalar";
        return value ? "true" : "false";
    }

    function ValidRequestID(value) {
        if (typeof value != "string" || value.len() < 1 || value.len() > 64) return false;
        for (local i = 0; i < value.len(); i++) {
            local ch = value[i];
            local alnum = (ch >= 48 && ch <= 57) || (ch >= 65 && ch <= 90) || (ch >= 97 && ch <= 122);
            if (!alnum && (i == 0 || (ch != 45 && ch != 95))) return false;
        }
        return true;
    }

    function Handle(request) {
        if (typeof request != "table" || (request.len() != 3 && request.len() != 4 && request.len() != 5)) return false;
        if (!("protocol" in request) || !("type" in request) || !("request_id" in request)) return false;
        if (typeof request.protocol != "integer" || request.protocol != 1) return false;
        if (typeof request.type != "string" || (request.type != "ping" && request.type != "world_info" && request.type != "industry_page" && request.type != "industry_cargo" && request.type != "cargo_page" && request.type != "industry_production")) return false;
        if (!this.ValidRequestID(request.request_id)) return false;
        if (request.type == "industry_production") return this.IndustryProduction(request);
        if (request.type == "cargo_page") return this.CargoPage(request);
        if (request.type == "industry_cargo") return this.IndustryCargo(request);
        if (request.type == "industry_page") return this.IndustryPage(request);
        if (request.len() != 3) return false;
        if (request.type == "world_info") return this.WorldInfo(request);
        /* Fixed envelope plus at most 64 unescaped ASCII ID bytes: <= 121 bytes.
           Both application maximum (512) and documented GSAdmin.Send limit (1450)
           are respected by construction, without serializing arbitrary input. */
        local ack = { protocol = 1, type = "ack", request_id = request.request_id, status = "ok" };
        GSLog.Info("BRIDGE_REQUEST_RECEIVED request_id=" + request.request_id);
        if (!GSAdmin.Send(ack)) return false;
        GSLog.Info("BRIDGE_ACK_SENT request_id=" + request.request_id);
        return true;
    }

    function WorldInfo(request) {
        GSLog.Info("BRIDGE_REQUEST_RECEIVED request_id=" + request.request_id + " type=world_info protocol=1");
        local width = GSMap.GetMapSizeX();
        local height = GSMap.GetMapSizeY();
        if (typeof width != "integer" || typeof height != "integer" ||
            width <= 0 || height <= 0 || width >= 65536 || height >= 65536 ||
            (width & (width - 1)) != 0 || (height & (height - 1)) != 0) return false;
        GSLog.Info("WORLD_INFO_READ request_id=" + request.request_id + " map_width=" + this.EvidenceOptionalInt(width) + " map_height=" + this.EvidenceOptionalInt(height));
        /* Safe ASCII ID <=64 and uint16 dimensions bound the fixed envelope to <=185 bytes. */
        local response = { protocol = 1, type = "world_info_result", request_id = request.request_id,
                           status = "ok", map_width = width, map_height = height };
        if (!GSAdmin.Send(response)) return false;
        GSLog.Info("BRIDGE_RESPONSE_SENT request_id=" + request.request_id + " type=world_info_result status=ok protocol=1");
        return true;
    }

    function IndustryPage(request) {
        if (request.len() != 5 || !("after_id" in request) || !("limit" in request)) return false;
        if (request.after_id != null && (typeof request.after_id != "integer" ||
            request.after_id < 0 || request.after_id >= 64000)) return false;
        /* 192-byte conservative envelope + 62 bytes/record: five <=502, six >512. */
        if (typeof request.limit != "integer" || request.limit < 1 || request.limit > 5) return false;
        GSLog.Info("BRIDGE_REQUEST_RECEIVED request_id=" + request.request_id + " type=industry_page protocol=1");
        local source = GSIndustryList();
        source.Sort(GSList.SORT_BY_ITEM, GSList.SORT_ASCENDING);
        local records = [];
        local more = false;
        for (local id = source.Begin(); !source.IsEnd(); id = source.Next()) {
            if (request.after_id != null && id <= request.after_id) continue;
            /* Industry may have disappeared since native list construction. Skip it. */
            if (!GSIndustry.IsValidIndustry(id)) continue;
            if (records.len() == request.limit) { more = true; break; }
            local tile = GSIndustry.GetLocation(id);
            local kind = GSIndustry.GetIndustryType(id);
            if (id < 0 || id >= 64000 || kind < 0 || kind >= 240 || !GSMap.IsValidTile(tile)) return false;
            local x = GSMap.GetTileX(tile);
            local y = GSMap.GetTileY(tile);
            if (x < 0 || y < 0 || x >= GSMap.GetMapSizeX() || y >= GSMap.GetMapSizeY() ||
                tile != y * GSMap.GetMapSizeX() + x) return false;
            if (records.len() && id <= records[records.len() - 1].id) return false;
            records.append({ id = id, type = kind, tile = tile, x = x, y = y });
        }
        local next = more ? records[records.len() - 1].id : null;
        GSLog.Info("INDUSTRY_PAGE_READ request_id=" + request.request_id + " after_id=" + this.EvidenceOptionalInt(request.after_id) +
                   " limit=" + this.EvidenceOptionalInt(request.limit) + " returned_count=" + this.EvidenceOptionalInt(records.len()) +
                   " first_id=" + this.EvidenceOptionalInt(records.len() ? records[0].id : null) +
                   " last_id=" + this.EvidenceOptionalInt(records.len() ? records[records.len() - 1].id : null) +
                   " next_after_id=" + this.EvidenceOptionalInt(next) + " has_more=" + this.EvidenceBool(more));
        local response = { protocol = 1, type = "industry_page_result", request_id = request.request_id,
                           status = "ok", industries = records, next_after_id = next, has_more = more };
        if (!GSAdmin.Send(response)) return false;
        GSLog.Info("BRIDGE_RESPONSE_SENT request_id=" + request.request_id + " type=industry_page_result status=ok protocol=1");
        return true;
    }

    function CargoIDs(source) {
        source.Sort(GSList.SORT_BY_ITEM, GSList.SORT_ASCENDING);
        local result = [];
        for (local id = source.Begin(); !source.IsEnd(); id = source.Next()) {
            if (typeof id != "integer" || id < 0 || id >= 64 || !GSCargo.IsValidCargo(id) ||
                result.len() >= 16 || (result.len() && id <= result[result.len() - 1])) throw "invalid cargo list";
            result.append(id);
        }
        return result;
    }

    function IndustryProduction(request) {
        if (request.len() != 5 || !("industry_id" in request) || !("cargo_id" in request) ||
            typeof request.industry_id != "integer" || typeof request.cargo_id != "integer" ||
            request.industry_id < 0 || request.industry_id >= 64000 || request.cargo_id < 0 || request.cargo_id >= 64 ||
            !GSIndustry.IsValidIndustry(request.industry_id) || !GSCargo.IsValidCargo(request.cargo_id)) return false;
        GSLog.Info("BRIDGE_REQUEST_RECEIVED request_id=" + request.request_id + " type=industry_production protocol=1");
        local before = GSDate.GetCurrentDate();
        local produced = GSIndustry.GetLastMonthProduction(request.industry_id, request.cargo_id);
        local transported = GSIndustry.GetLastMonthTransported(request.industry_id, request.cargo_id);
        local percentage = GSIndustry.GetLastMonthTransportedPercentage(request.industry_id, request.cargo_id);
        local after = GSDate.GetCurrentDate();
        /* -1 means invalid/non-produced relationship, not valid zero history. */
        if (typeof produced != "integer" || produced < 0 || produced > 65535 ||
            typeof transported != "integer" || transported < 0 || transported > 65535 ||
            typeof percentage != "integer" || percentage < 0 || percentage > 100 ||
            typeof before != "integer" || before < 0 || before > 2147483647 ||
            typeof after != "integer" || after < before || after > 2147483647) return false;
        local values = [request.industry_id, request.cargo_id, before, after, produced, transported, percentage];
        local names = ["industry_id", "cargo_id", "economy_date_before", "economy_date_after", "last_month_produced", "last_month_transported", "last_month_transported_pct"];
        local metadata = "";
        for (local index = 0; index < names.len(); index++) metadata += " " + names[index] + "=" + this.EvidenceOptionalInt(values[index]);
        GSLog.Info("INDUSTRY_PRODUCTION_READ request_id=" + request.request_id + metadata);
        /* Worst-case335 bytes: <=512 application limit and <1450 native ceiling. */
        local response = {protocol=1, type="industry_production_result", request_id=request.request_id, status="ok",
            industry_id=request.industry_id, cargo_id=request.cargo_id, economy_date_before=before, economy_date_after=after,
            last_month_produced=produced, last_month_transported=transported, last_month_transported_pct=percentage};
        if (!GSAdmin.Send(response)) return false;
        GSLog.Info("BRIDGE_RESPONSE_SENT request_id=" + request.request_id + " type=industry_production_result status=ok protocol=1");
        return true;
    }

    function IndustryCargo(request) {
        if (request.len() != 4 || !("industry_id" in request) || typeof request.industry_id != "integer" ||
            request.industry_id < 0 || request.industry_id >= 64000 || !GSIndustry.IsValidIndustry(request.industry_id)) return false;
        GSLog.Info("BRIDGE_REQUEST_RECEIVED request_id=" + request.request_id + " type=industry_cargo protocol=1");
        local produces = this.CargoIDs(GSCargoList_IndustryProducing(request.industry_id));
        local accepts = this.CargoIDs(GSCargoList_IndustryAccepting(request.industry_id));
        GSLog.Info("INDUSTRY_CARGO_READ request_id=" + request.request_id + " industry_id=" + this.EvidenceOptionalInt(request.industry_id) +
            " produced_count=" + this.EvidenceOptionalInt(produces.len()) + " accepted_count=" + this.EvidenceOptionalInt(accepts.len()) +
            " first_produced=" + this.EvidenceOptionalInt(produces.len() ? produces[0] : null) +
            " last_produced=" + this.EvidenceOptionalInt(produces.len() ? produces[produces.len() - 1] : null) +
            " first_accepted=" + this.EvidenceOptionalInt(accepts.len() ? accepts[0] : null) +
            " last_accepted=" + this.EvidenceOptionalInt(accepts.len() ? accepts[accepts.len() - 1] : null));
        /* 64-byte ASCII request ID + industry ID<=63999 + two <=16 item cargo lists (0..63): <=300 bytes. */
        local response = { protocol = 1, type = "industry_cargo_result", request_id = request.request_id,
            status = "ok", industry_id = request.industry_id, produces = produces, accepts = accepts };
        if (!GSAdmin.Send(response)) return false;
        GSLog.Info("BRIDGE_RESPONSE_SENT request_id=" + request.request_id + " type=industry_cargo_result status=ok protocol=1");
        return true;
    }

    /* Four native bytes, not localized text: exact uppercase hex on the wire. */
    function CargoLabelHex(label) {
        if (typeof label != "string" || label.len() != 4) throw "invalid cargo label";
        local hex = "0123456789ABCDEF";
        local result = "";
        for (local i = 0; i < 4; i++) {
            local byte = label[i] & 255;
            result += hex.slice(byte >> 4, (byte >> 4) + 1);
            result += hex.slice(byte & 15, (byte & 15) + 1);
        }
        return result;
    }

    function CargoClasses(id) {
        /* Project mask v1: ordered named ScriptCargo constants, no assumed native bit values. */
        local classes = [GSCargo.CC_PASSENGERS, GSCargo.CC_MAIL, GSCargo.CC_EXPRESS, GSCargo.CC_ARMOURED, GSCargo.CC_BULK, GSCargo.CC_PIECE_GOODS, GSCargo.CC_LIQUID, GSCargo.CC_REFRIGERATED, GSCargo.CC_HAZARDOUS, GSCargo.CC_COVERED, GSCargo.CC_OVERSIZED, GSCargo.CC_POWDERIZED, GSCargo.CC_NON_POURABLE, GSCargo.CC_POTABLE, GSCargo.CC_NON_POTABLE];
        local mask = 0;
        for (local i = 0; i < classes.len(); i++) {
            if (GSCargo.HasCargoClass(id, classes[i])) mask = mask | (1 << i);
        }
        return mask;
    }

    function CargoPage(request) {
        if (request.len() != 5 || !("after_id" in request) || !("limit" in request)) return false;
        if (request.after_id != null && (typeof request.after_id != "integer" || request.after_id < 0 || request.after_id > 63)) return false;
        /* Worst-case record 76, empty envelope 186: four=493; five=570 (>512). */
        if (typeof request.limit != "integer" || request.limit < 1 || request.limit > 4) return false;
        GSLog.Info("BRIDGE_REQUEST_RECEIVED request_id=" + request.request_id + " type=cargo_page protocol=1");
        local source = GSCargoList();
        source.Sort(GSList.SORT_BY_ITEM, GSList.SORT_ASCENDING);
        local records = [];
        local more = false;
        local previous = null;
        for (local id = source.Begin(); !source.IsEnd(); id = source.Next()) {
            if (typeof id != "integer" || id < 0 || id > 63 || !GSCargo.IsValidCargo(id) || (previous != null && id <= previous)) return false;
            previous = id;
            if (request.after_id != null && id <= request.after_id) continue;
            if (records.len() == request.limit) { more = true; break; }
            local label = this.CargoLabelHex(GSCargo.GetCargoLabel(id));
            local freight = GSCargo.IsFreight(id);
            local effect = GSCargo.GetTownEffect(id);
            if (typeof freight != "bool" || typeof effect != "integer" || effect < 0 || effect > 5) return false;
            records.append({ id = id, label = label, freight = freight, town_effect = effect, classes = this.CargoClasses(id) });
        }
        local next = more ? records[records.len() - 1].id : null;
        GSLog.Info("CARGO_PAGE_READ request_id=" + request.request_id + " after_id=" + this.EvidenceOptionalInt(request.after_id) +
            " limit=" + this.EvidenceOptionalInt(request.limit) + " returned_count=" + this.EvidenceOptionalInt(records.len()) +
            " first_id=" + this.EvidenceOptionalInt(records.len() ? records[0].id : null) +
            " last_id=" + this.EvidenceOptionalInt(records.len() ? records[records.len() - 1].id : null) +
            " next_after_id=" + this.EvidenceOptionalInt(next) + " has_more=" + this.EvidenceBool(more));
        local response = { protocol = 1, type = "cargo_page_result", request_id = request.request_id, status = "ok",
            cargoes = records, next_after_id = next, has_more = more };
        if (!GSAdmin.Send(response)) return false;
        GSLog.Info("BRIDGE_RESPONSE_SENT request_id=" + request.request_id + " type=cargo_page_result status=ok protocol=1");
        return true;
    }

    function Start() {
        local pending_alive = [];
        GSLog.Info("BRIDGE_STARTED protocol=1 api=15");
        while (true) {
            /* Re-entered the event loop after the existing script-tick yield. */
            foreach (operation in pending_alive) {
                if (operation.type == "ping") {
                    GSLog.Info("BRIDGE_POST_ACK_ALIVE request_id=" + operation.request_id);
                } else {
                    GSLog.Info("BRIDGE_POST_RESPONSE_ALIVE request_id=" + operation.request_id);
                }
            }
            pending_alive.clear();
            /* Yield after a bounded event batch so traffic cannot starve script ticks. */
            for (local count = 0; count < 32 && GSEventController.IsEventWaiting(); count++) {
                local event = GSEventController.GetNextEvent();
                if (event.GetEventType() != GSEvent.ET_ADMIN_PORT) continue;
                local message = GSEventAdminPort.Convert(event);
                try {
                    local request = message.GetObject();
                    if (this.Handle(request)) pending_alive.append({ request_id = request.request_id, type = request.type });
                }
                catch (error) { /* Reject malformed input and remain alive. */ }
            }
            this.Sleep(1);
        }
    }
}
