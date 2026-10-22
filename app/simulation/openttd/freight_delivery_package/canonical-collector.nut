/* Read-only 15.3 native enumeration. Each page stays below GSAdmin payload limit. */
function CanonicalCollect(self,q) {
    if(q.len()!=5||q.protocol!=1||q.type!="canonical-page"||typeof q.request_id!="string"||
        typeof q.offset!="integer"||q.offset<0||q.offset>=4096||!GSGame.IsPaused()||
        self.services==null||self.services.len()!=3)throw "CANONICAL_COLLECT_PREREQUISITE";
    local mode=GSCompanyMode(0);if(!GSCompanyMode.IsValid())throw "CANONICAL_COMPANY";
    local rows=[];local total=0;local start=q.offset;
    local plans=[];foreach(c in self.services) {
        if(c.dstage!=10||c.dfailed||typeof c.dplan!="string")throw "CANONICAL_SERVICE_STAGE";
        plans.append(c.dplan);
    }
    if(q.section=="header") {
        total=1;
        if(start==0)rows.append({economy_date=GSDate.GetCurrentDate(),economy_date_fraction=null,
            calendar_date=null,calendar_date_fraction=null,
            timekeeping=GSGameSettings.GetValue("economy.timekeeping_units"),paused=GSGame.IsPaused(),
            auto_renew=GSCompany.GetAutoRenewStatus(0),company=0,cash=GSCompany.GetBankBalance(0),
            loan=GSCompany.GetLoanAmount(),delivered=[GSCompany.GetQuarterlyCargoDelivered(0,0),GSCompany.GetQuarterlyCargoDelivered(0,0),GSCompany.GetQuarterlyCargoDelivered(0,0)],vehicle_count=GSVehicleList().Count(),
            width=GSMap.GetMapSizeX(),height=GSMap.GetMapSizeY(),service_plans=plans});
        foreach(c in self.services)if(c.obs_stage!=0||c.monitors||c.monitor_delivery!=0)
            throw "CANONICAL_PREVIOUS_OPERATION";
    } else if(q.section=="vehicles") {
        total=3;
        for(local i=start;i<total&&i<start+1;i++) {
            local c=self.services[i];local v=c.dvehicle;local a=c.choice.a;
            if(!GSVehicle.IsValidVehicle(v)||GSOrder.GetOrderCount(v)!=2)throw "CANONICAL_VEHICLE";
            local orders=[];for(local n=0;n<2;n++)orders.append({destination=GSOrder.GetOrderDestination(v,n),
                flags=GSOrder.GetOrderFlags(v,n),goto_station=GSOrder.IsGotoStationOrder(v,n)});
            rows.append({service=i,vehicle=v,owner=GSVehicle.GetOwner(v),engine=GSVehicle.GetEngineType(v),
                cargo=a[2],capacity=GSVehicle.GetCapacity(v,a[2]),tile=GSVehicle.GetLocation(v),
                stopped=GSVehicle.IsStoppedInDepot(v),in_depot=GSVehicle.IsInDepot(v),
                speed=GSVehicle.GetCurrentSpeed(v),load=GSVehicle.GetCargoLoad(v,a[2]),orders=orders});
        }
    } else if(q.section=="map") {
        total=GSMap.GetMapSize();if(total>4096)throw "CANONICAL_MAP_BUDGET";
        for(local t=start;t<total&&t<start+4;t++) {local edges=[];
            foreach(other in [t-1,t+1,t-GSMap.GetMapSizeX(),t+GSMap.GetMapSizeX()])
                if(other>=0&&other<total&&GSMap.DistanceManhattan(t,other)==1&&GSRoad.AreRoadTilesConnected(t,other))edges.append(other);
            rows.append({tile=t,owner=GSTile.GetOwner(t),
            road=GSRoad.IsRoadTile(t),depot=GSRoad.IsRoadDepotTile(t),station=GSStation.GetStationID(t),
            industry=GSIndustry.GetIndustryID(t),slope=GSTile.GetSlope(t),height=GSTile.GetMinHeight(t),edges=edges});}
    } else if(q.section=="industries") {
        local list=GSIndustryList();total=list.Count();local index=0;
        foreach(id,_ in list) {
            if(index>=start&&index<start+1) {
                local cargo=[];foreach(c,_ in GSCargoList())cargo.append([c,
                    GSIndustry.GetLastMonthProduction(id,c),GSIndustry.IsCargoAccepted(id,c)]);
                rows.append({industry=id,type=GSIndustry.GetIndustryType(id),tile=GSIndustry.GetLocation(id),cargo=cargo});
            }
            index++;
        }
    } else if(q.section=="stations") {
        local list=GSStationList(GSStation.STATION_ANY);total=list.Count();local index=0;
        foreach(id,_ in list) {
            if(index>=start&&index<start+1) {
                local cargo=[];foreach(c,_ in GSCargoList())cargo.append([c,GSStation.GetCargoWaiting(id,c)]);
                local tile=GSStation.GetLocation(id);
                rows.append({station=id,tile=tile,owner=GSTile.GetOwner(tile),cargo=cargo});
            }
            index++;
        }
    } else throw "CANONICAL_SECTION";
    if(!GSAdmin.Send({protocol=1,type="canonical-page-result",request_id=q.request_id,section=q.section,
        offset=q.offset,status="ok",total=total,records=rows,tick=self.GetTick(),
        economy_date=GSDate.GetCurrentDate(),paused=GSGame.IsPaused(),restored=self.restored_fleet}))
        throw "CANONICAL_COLLECT_SEND";
    mode=null;
}
