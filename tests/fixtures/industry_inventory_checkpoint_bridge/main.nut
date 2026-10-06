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
        if (typeof request != "table" || (request.len() != 3 && request.len() != 5)) return false;
        if (!("protocol" in request) || !("type" in request) || !("request_id" in request)) return false;
        if (typeof request.protocol != "integer" || request.protocol != 1) return false;
        if (typeof request.type != "string" || (request.type != "ping" && request.type != "world_info" && request.type != "industry_page")) return false;
        if (!this.ValidRequestID(request.request_id)) return false;
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
