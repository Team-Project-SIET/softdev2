/* Qualification-specific thin native reads. No polling/history/qualification state. */
class QualificationBridge extends RawObservationBridge {
    function Handle(request) {
        if (typeof request != "table" || !("type" in request) ||
            (request.type != "economy_clock" && request.type != "industry_lifetime")) return RawObservationBridge.Handle.call(this, request);
        if (!("protocol" in request) || typeof request.protocol != "integer" || request.protocol != 1 ||
            !("request_id" in request) || !this.ValidRequestID(request.request_id)) return false;
        if (request.type == "economy_clock") return this.EconomyClock(request);
        return this.IndustryLifetime(request);
    }

    function EconomyClock(request) {
        if (request.len() != 3) return false;
        GSLog.Info("BRIDGE_REQUEST_RECEIVED request_id=" + request.request_id + " type=economy_clock protocol=1");
        local date = GSDate.GetCurrentDate();
        if (typeof date != "integer" || date < 0 || date > 2147483647) return false;
        local year = GSDate.GetYear(date);
        local month = GSDate.GetMonth(date);
        local day = GSDate.GetDayOfMonth(date);
        if (year < 0 || year > 5000000 || month < 1 || month > 12 || day < 1 || day > 31) return false;
        local start = GSDate.GetDate(year, month, 1);
        local end = GSDate.GetDate(month == 12 ? year + 1 : year, month == 12 ? 1 : month + 1, 1);
        if (start < 0 || end < 0 || date < start || date >= end || date != start + day - 1) return false;
        GSLog.Info("ECONOMY_CLOCK_READ request_id=" + request.request_id + " economy_date=" + date +
            " economy_year=" + year + " economy_month=" + month + " economy_day=" + day +
            " month_start=" + start + " month_end=" + end);
        if (!GSAdmin.Send({protocol=1, type="economy_clock_result", request_id=request.request_id, status="ok",
            economy_date=date, economy_year=year, economy_month=month, economy_day=day, month_start=start, month_end=end})) return false;
        GSLog.Info("BRIDGE_RESPONSE_SENT request_id=" + request.request_id + " type=economy_clock_result status=ok protocol=1");
        return true;
    }

    function IndustryLifetime(request) {
        if (request.len() != 4 || !("industry_id" in request) || typeof request.industry_id != "integer" ||
            request.industry_id < 0 || request.industry_id >= 64000 || !GSIndustry.IsValidIndustry(request.industry_id)) return false;
        GSLog.Info("BRIDGE_REQUEST_RECEIVED request_id=" + request.request_id + " type=industry_lifetime protocol=1");
        local before = GSDate.GetCurrentDate();
        /* GetConstructionDate is a CALENDAR identity, not economy qualification evidence. */
        local construction = GSIndustry.GetConstructionDate(request.industry_id);
        local after = GSDate.GetCurrentDate();
        if (typeof construction != "integer" || construction < 0 || construction > 2147483647 ||
            before < 0 || after < before || after > 2147483647) return false;
        GSLog.Info("INDUSTRY_LIFETIME_READ request_id=" + request.request_id + " industry_id=" + request.industry_id +
            " construction_date=" + construction + " economy_before=" + before + " economy_after=" + after);
        if (!GSAdmin.Send({protocol=1,type="industry_lifetime_result",request_id=request.request_id,status="ok",
            industry_id=request.industry_id,construction_date=construction,economy_before=before,economy_after=after})) return false;
        GSLog.Info("BRIDGE_RESPONSE_SENT request_id=" + request.request_id + " type=industry_lifetime_result status=ok protocol=1");
        return true;
    }
}
class NoMutationBridge extends QualificationBridge {}
