/* Schema-2 tile classification reads. Additive handler: the frozen v1
 * tile_facts_page behavior of RawObservationBridge/TerrainBridge is not
 * modified, so historical protocol identities and staged evidence remain
 * valid. This handler serves only the new `tile_classification_page` type
 * (explicit schema=2) and carries the full 15-predicate native mask with no
 * road-predicate packing, plus the industry pointer and native owner. */
class TerrainClassificationBridge extends RawObservationBridge {
    function Handle(request) {
        if (typeof request != "table" || !("type" in request) || request.type != "tile_classification_page")
            return RawObservationBridge.Handle.call(this, request);
        if (!("request_id" in request) || !this.ValidRequestID(request.request_id)) return false;
        try {
            return this.TileClassificationPage(request);
        } catch (error) {
            return this.TileClassificationError(request, "BRIDGE_FAILURE", null);
        }
    }

    function TileClassificationError(request, code, tile) {
        local cursor = ("cursor" in request && typeof request.cursor == "integer" && request.cursor >= 0 && request.cursor <= 255) ? request.cursor : null;
        /* Fixed safe fields; small bytes, no exception text or input reflection. */
        GSAdmin.Send({protocol=1,type="tile_classification_page_result",request_id=request.request_id,schema=2,
            status="error",error_code=code,cursor=cursor,failed_tile=tile});
        return false;
    }

    function TileClassificationPage(request) {
        if (!("protocol" in request) || typeof request.protocol != "integer" || request.protocol != 1)
            return this.TileClassificationError(request,"UNSUPPORTED_PROTOCOL",null);
        /* Exactly six request fields (protocol, type, request_id, region, cursor, schema). */
        if (request.len()!=6 || !("region" in request) || !("cursor" in request) ||
            typeof request.region!="array" || request.region.len()!=4 ||
            !("schema" in request) || typeof request.schema!="integer" || request.schema!=2)
            return this.TileClassificationError(request,"UNSUPPORTED_CLASSIFICATION_SCHEMA",null);
        local r=request.region;
        foreach(v in r) if(typeof v!="integer" || v<0 || v>4095) return this.TileClassificationError(request,"INVALID_REGION",null);
        if(r[2]<1 || r[3]<1 || r[2]*r[3]>256) return this.TileClassificationError(request,"COVERAGE_LIMIT_EXCEEDED",null);
        if(typeof request.cursor!="integer" || request.cursor<0 || request.cursor>=r[2]*r[3] || request.cursor%5!=0)
            return this.TileClassificationError(request,"CURSOR_MISMATCH",null);
        /* Exact canonical request <=159 bytes; Python enforces the raw byte gate. */
        local width=GSMap.GetMapSizeX(); local height=GSMap.GetMapSizeY();
        if(width<1 || height<1 || width>4096 || height>4096 || (width&(width-1))!=0 || (height&(height-1))!=0 ||
            r[0]+r[2]>width || r[1]+r[3]>height) return this.TileClassificationError(request,"INVALID_REGION",null);
        /* Same audited road-type selection as schema 1; script state only. */
        local ordinary=GSRoad.ROADTYPE_ROAD;
        local available=GSRoad.IsRoadTypeAvailable(ordinary);
        if(typeof available!="bool" || !available)
            return this.TileClassificationError(request,"UNSUPPORTED_ROAD_TYPE",null);
        GSRoad.SetCurrentRoadType(ordinary);
        local selected=GSRoad.GetCurrentRoadType();
        if(typeof selected!="integer" || selected!=ordinary)
            return this.TileClassificationError(request,"UNSUPPORTED_ROAD_TYPE",null);
        GSLog.Info("BRIDGE_REQUEST_RECEIVED request_id="+request.request_id+" type=tile_classification_page schema=2");
        local before=GSDate.GetCurrentDate();
        if(before<0 || before>2147483647) return this.TileClassificationError(request,"UNSUPPORTED_NATIVE_FACT",null);
        local rows=[];
        for(local ordinal=request.cursor; ordinal<r[2]*r[3] && rows.len()<5; ordinal++) {
            local x=r[0]+ordinal%r[2]; local y=r[1]+ordinal/r[2];
            local tile=GSMap.GetTileIndex(x,y);
            if(!GSMap.IsValidTile(tile)) return this.TileClassificationError(request,"INVALID_TILE",tile);
            if(GSMap.GetTileX(tile)!=x || GSMap.GetTileY(tile)!=y || tile!=y*width+x)
                return this.TileClassificationError(request,"INVALID_TILE",tile);
            local elevation=GSTile.GetMinHeight(tile); local slope=GSTile.GetSlope(tile);
            if(elevation<0 || elevation>255 || slope<0 || slope>31) return this.TileClassificationError(request,"UNSUPPORTED_NATIVE_FACT",tile);
            /* Identical predicate set to the schema-1 handler, evaluated fully
               (no short-circuit) so an incomplete read is impossible by design. */
            local buildable=GSTile.IsBuildable(tile);
            local water=GSTile.IsWaterTile(tile); local coast=GSTile.IsCoastTile(tile);
            local tree=GSTile.HasTreeOnTile(tile); local farm=GSTile.IsFarmTile(tile);
            local rock=GSTile.IsRockTile(tile); local rough=GSTile.IsRoughTile(tile);
            local road_tile=GSRoad.IsRoadTile(tile); local road_track=GSTile.HasTransportType(tile,GSTile.TRANSPORT_ROAD);
            local road0=GSRoad.HasRoadType(tile,0);
            local rail=GSTile.HasTransportType(tile,GSTile.TRANSPORT_RAIL);
            local water_transport=GSTile.HasTransportType(tile,GSTile.TRANSPORT_WATER);
            local airport=GSAirport.IsAirportTile(tile); local house=GSTile.IsHouseTile(tile); local station=GSTile.IsStationTile(tile);
            local predicates=[buildable,water,coast,tree,farm,rock,rough,road_tile,road_track,road0,rail,water_transport,airport,house,station];
            foreach(v in predicates) if(typeof v!="bool") return this.TileClassificationError(request,"UNSUPPORTED_NATIVE_FACT",tile);
            /* No packing: all fifteen native predicates take one declared bit. */
            local flags=0;
            for(local i=0;i<predicates.len();i++) if(predicates[i]) flags=flags|(1<<i);
            local industry=GSIndustry.GetIndustryID(tile);
            if(!GSIndustry.IsValidIndustry(industry)) industry=null;
            else if(industry<0 || industry>63999) return this.TileClassificationError(request,"UNSUPPORTED_NATIVE_FACT",tile);
            local owner=GSTile.GetOwner(tile);
            if(owner < -1 || owner>14) return this.TileClassificationError(request,"UNSUPPORTED_NATIVE_FACT",tile);
            rows.append([tile,elevation,slope,flags,industry,owner]);
        }
        local after=GSDate.GetCurrentDate();
        if(after<before || after>2147483647) return this.TileClassificationError(request,"UNSUPPORTED_NATIVE_FACT",null);
        local more=request.cursor+rows.len()<r[2]*r[3];
        local next=more?request.cursor+rows.len():null;
        local response={protocol=1,type="tile_classification_page_result",schema=2,request_id=request.request_id,
            status="ok",region=r,cursor=request.cursor,map=[width,height],date_before=before,date_after=after,
            tiles=rows,next_cursor=next,has_more=more};
        /* Canonical JSON matches tagged ScriptAdminMakeJSON + json.dump sort_keys;
           <=508 bytes, fail closed, never truncated. */
        local canonical="{\"cursor\":"+request.cursor+",\"date_after\":"+after+",\"date_before\":"+before+
            ",\"has_more\":"+this.EvidenceBool(more)+",\"map\":["+width+","+height+"],\"next_cursor\":"+this.EvidenceOptionalInt(next)+
            ",\"protocol\":1,\"region\":["+r[0]+","+r[1]+","+r[2]+","+r[3]+"],\"request_id\":\""+request.request_id+
            "\",\"schema\":2,\"status\":\"ok\",\"tiles\":[";
        for(local i=0;i<rows.len();i++) {
            if(i) canonical+=",";
            canonical+="[";
            for(local j=0;j<6;j++) { if(j) canonical+=","; canonical+=this.EvidenceOptionalInt(rows[i][j]); }
            canonical+="]";
        }
        canonical+="],\"type\":\"tile_classification_page_result\"}";
        if(canonical.len()>508) return this.TileClassificationError(request,"RESPONSE_LIMIT_EXCEEDED",null);
        GSLog.Info("TILE_CLASSIFICATION_READ request_id="+request.request_id+" response_json="+canonical);
        if(!GSAdmin.Send(response)) return false;
        GSLog.Info("BRIDGE_RESPONSE_SENT request_id="+request.request_id+" type=tile_classification_page_result status=ok schema=2");
        return true;
    }
}
class NoMutationBridge extends TerrainClassificationBridge {}
