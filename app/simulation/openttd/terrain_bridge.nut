/* Thin 15.3 terrain reads. No construction, company switch, graph or qualification. */
class TerrainBridge extends RawObservationBridge {
    function Handle(request) {
        if (typeof request != "table" || !("type" in request) || request.type != "tile_facts_page")
            return RawObservationBridge.Handle.call(this, request);
        if (!("request_id" in request) || !this.ValidRequestID(request.request_id)) return false;
        try {
            return this.TileFactsPage(request);
        } catch (error) {
            return this.TileError(request, "BRIDGE_FAILURE", null);
        }
    }

    function TileError(request, code, tile) {
        local cursor = ("cursor" in request && typeof request.cursor == "integer" && request.cursor >= 0 && request.cursor <= 255) ? request.cursor : null;
        /* Fixed safe fields; <=227 bytes, no exception text or unknown input reflection. */
        GSAdmin.Send({protocol=1,type="tile_facts_page_result",request_id=request.request_id,
            status="error",error_code=code,cursor=cursor,failed_tile=tile});
        return false;
    }

    function TileFactsPage(request) {
        if (!("protocol" in request) || typeof request.protocol != "integer" || request.protocol != 1)
            return this.TileError(request,"UNSUPPORTED_PROTOCOL",null);
        if (request.len()!=5 || !("region" in request) || !("cursor" in request) ||
            typeof request.region!="array" || request.region.len()!=4)
            return this.TileError(request,"INVALID_REGION",null);
        local r=request.region;
        foreach(v in r) if(typeof v!="integer" || v<0 || v>4095) return this.TileError(request,"INVALID_REGION",null);
        if(r[2]<1 || r[3]<1 || r[2]*r[3]>256) return this.TileError(request,"COVERAGE_LIMIT_EXCEEDED",null);
        if(typeof request.cursor!="integer" || request.cursor<0 || request.cursor>=r[2]*r[3] || request.cursor%5!=0)
            return this.TileError(request,"CURSOR_MISMATCH",null);
        /* Exact canonical request <=159 bytes. GetObject does not expose original raw
           whitespace/duplicate keys: Python must enforce the raw outbound byte gate. */
        local width=GSMap.GetMapSizeX(); local height=GSMap.GetMapSizeY();
        if(width<1 || height<1 || width>4096 || height>4096 || (width&(width-1))!=0 || (height&(height-1))!=0 ||
            r[0]+r[2]>width || r[1]+r[3]>height) return this.TileError(request,"INVALID_REGION",null);
        /* ScriptStorage starts at internal INVALID_ROADTYPE=63. Select only the
           audited ordinary road; this changes script state, never the map. */
        local ordinary=GSRoad.ROADTYPE_ROAD;
        local available=GSRoad.IsRoadTypeAvailable(ordinary);
        if(typeof available!="bool" || !available)
            return this.TileError(request,"UNSUPPORTED_ROAD_TYPE",null);
        GSRoad.SetCurrentRoadType(ordinary);
        local selected=GSRoad.GetCurrentRoadType();
        if(typeof selected!="integer" || selected!=ordinary)
            return this.TileError(request,"UNSUPPORTED_ROAD_TYPE",null);
        GSLog.Info("BRIDGE_REQUEST_RECEIVED request_id="+request.request_id+" type=tile_facts_page protocol=1");
        local before=GSDate.GetCurrentDate();
        if(before<0 || before>2147483647) return this.TileError(request,"UNSUPPORTED_NATIVE_FACT",null);
        local rows=[];
        for(local ordinal=request.cursor; ordinal<r[2]*r[3] && rows.len()<5; ordinal++) {
            local x=r[0]+ordinal%r[2]; local y=r[1]+ordinal/r[2];
            local tile=GSMap.GetTileIndex(x,y);
            if(!GSMap.IsValidTile(tile)) return this.TileError(request,"INVALID_TILE",tile);
            if(GSMap.GetTileX(tile)!=x || GSMap.GetTileY(tile)!=y || tile!=y*width+x)
                return this.TileError(request,"INVALID_TILE",tile);
            local elevation=GSTile.GetMinHeight(tile); local slope=GSTile.GetSlope(tile);
            if(elevation<0 || elevation>255 || slope<0 || slope>31) return this.TileError(request,"UNSUPPORTED_NATIVE_FACT",tile);
            local buildable=GSTile.IsBuildable(tile);
            local water=GSTile.IsWaterTile(tile); local coast=GSTile.IsCoastTile(tile);
            local tree=GSTile.HasTreeOnTile(tile); local farm=GSTile.IsFarmTile(tile);
            local rock=GSTile.IsRockTile(tile); local rough=GSTile.IsRoughTile(tile);
            /* Evaluate all three predicates; short-circuit would hide incomplete diagnostics. */
            local road_tile=GSRoad.IsRoadTile(tile); local road_track=GSTile.HasTransportType(tile,GSTile.TRANSPORT_ROAD);
            local road0=GSRoad.HasRoadType(tile,0);
            local rail=GSTile.HasTransportType(tile,GSTile.TRANSPORT_RAIL);
            local water_transport=GSTile.HasTransportType(tile,GSTile.TRANSPORT_WATER);
            local airport=GSAirport.IsAirportTile(tile); local house=GSTile.IsHouseTile(tile); local station=GSTile.IsStationTile(tile);
            local predicates=[buildable,water,coast,tree,farm,rock,rough,road_tile,road_track,road0,rail,water_transport,airport,house,station];
            foreach(v in predicates) if(typeof v!="bool") return this.TileError(request,"UNSUPPORTED_NATIVE_FACT",tile);
            local flags=0;
            local values=[buildable,water,coast,tree,farm,rock,rough,road_tile||road_track||road0,rail,water_transport,airport,house,station];
            for(local i=0;i<values.len();i++) if(values[i]) flags=flags|(1<<i);
            local industry=GSIndustry.GetIndustryID(tile);
            if(!GSIndustry.IsValidIndustry(industry)) industry=null;
            else if(industry<0 || industry>63999) return this.TileError(request,"UNSUPPORTED_NATIVE_FACT",tile);
            local owner=GSTile.GetOwner(tile);
            if(owner < -1 || owner>14) return this.TileError(request,"UNSUPPORTED_NATIVE_FACT",tile);
            local out=0; local incoming=0; local assessed=0;
            local steps=[[0,-1],[1,0],[0,1],[-1,0]];
            for(local i=0;i<4;i++) {
                local nx=x+steps[i][0]; local ny=y+steps[i][1];
                if(nx<r[0] || nx>=r[0]+r[2] || ny<r[1] || ny>=r[1]+r[3]) continue;
                local neighbor=GSMap.GetTileIndex(nx,ny);
                if(!GSMap.IsValidTile(neighbor)) return this.TileError(request,"INVALID_TILE",neighbor);
                assessed=assessed|(1<<i);
                local has_road=GSRoad.HasRoadType(neighbor,0);
                if(road0 && has_road) {
                    if(GSRoad.AreRoadTilesConnected(tile,neighbor)) out=out|(1<<i);
                    if(GSRoad.AreRoadTilesConnected(neighbor,tile)) incoming=incoming|(1<<i);
                }
            }
            rows.append([tile,elevation,slope,flags,industry,owner,road0?1:0,out,incoming,assessed]);
        }
        local after=GSDate.GetCurrentDate();
        if(after<before || after>2147483647) return this.TileError(request,"UNSUPPORTED_NATIVE_FACT",null);
        local more=request.cursor+rows.len()<r[2]*r[3];
        local next=more?request.cursor+rows.len():null;
        local response={protocol=1,type="tile_facts_page_result",status="ok",request_id=request.request_id,
            region=r,cursor=request.cursor,map=[width,height],date_before=before,date_after=after,
            tiles=rows,next_cursor=next,has_more=more};
        /* Safe ASCII strings and validated integers/null/bools only. Canonical JSON
           matches tagged ScriptAdminMakeJSON+json.dump; ≤508, fail closed never truncate. */
        local canonical="{\"cursor\":"+request.cursor+",\"date_after\":"+after+",\"date_before\":"+before+
            ",\"has_more\":"+this.EvidenceBool(more)+",\"map\":["+width+","+height+"],\"next_cursor\":"+this.EvidenceOptionalInt(next)+
            ",\"protocol\":1,\"region\":["+r[0]+","+r[1]+","+r[2]+","+r[3]+"],\"request_id\":\""+request.request_id+
            "\",\"status\":\"ok\",\"tiles\":[";
        for(local i=0;i<rows.len();i++) {
            if(i) canonical+=",";
            canonical+="[";
            for(local j=0;j<10;j++) { if(j) canonical+=","; canonical+=this.EvidenceOptionalInt(rows[i][j]); }
            canonical+="]";
        }
        canonical+="],\"type\":\"tile_facts_page_result\"}";
        if(canonical.len()>508) return this.TileError(request,"RESPONSE_LIMIT_EXCEEDED",null);
        /* No SHA API exists here. Independently logged canonical bytes bind region,
           cursor, rows and continuation; Python derives and checks the SHA-256. */
        GSLog.Info("TILE_FACTS_READ request_id="+request.request_id+" response_json="+canonical);
        if(!GSAdmin.Send(response)) return false;
        GSLog.Info("BRIDGE_RESPONSE_SENT request_id="+request.request_id+" type=tile_facts_page_result status=ok protocol=1");
        return true;
    }
}
class NoMutationBridge extends TerrainBridge {}
