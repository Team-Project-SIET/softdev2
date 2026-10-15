// P06 executes supplied decisions only. No optimizer, pathfinder or terrain repair.
class P06Execution {
    data=null; spec=null; plan=null; stages=null; actions=null; created=null;
    fleet=null; orders=null; native_groups=null; group_ids=null; facilities=null; built=null; terminal=false;
    mutated=false; stage="PLAN_ACCEPTED"; entity="plan"; reason="UNEXPECTED_ERROR";

    constructor(payload) {
        data=payload; spec=payload.execution; plan=payload.artifact.plan;
        stages=[]; actions=[]; created=[]; fleet=[]; orders=[]; native_groups=[]; group_ids={}; facilities={}; built={};
    }
    function _json(v) {
        local t=typeof v;
        if(v==null) return "null";
        if(t=="string") {
            local s="\"";
            for(local i=0;i<v.len();i++) {
                local c=v.slice(i,i+1);
                if(c=="\"" || c=="\\") s+="\\";
                s+=c;
            }
            return s+"\"";
        }
        if(t=="integer" || t=="bool") return v.tostring();
        local items=[];
        if(t=="array") {
            foreach(x in v) items.append(_json(x));
        } else {
            local keys=[]; foreach(k,x in v) keys.append(k); keys.sort();
            foreach(k in keys) items.append(_json(k)+":"+_json(v[k]));
        }
        local s=""; foreach(x in items) { if(s!="") s+=","; s+=x; }
        return t=="array" ? "["+s+"]" : "{"+s+"}";
    }
    function _stage(s) {
        stage=s; stages.append(s);
        AILog.Info("P03_EXECUTOR_AI|P06_STAGE_V1|"+data.plan_hash+"|"+s);
    }
    function _event(kind, detail) {
        detail.kind <- kind;
        detail.plan_hash <- data.plan_hash;
        AILog.Info("P03_EXECUTOR_AI|P06_EVENT_V1|"+_json(detail));
    }
    function _require(ok, why) { if(!ok) { reason=why; throw why; } }
    function _tile(t) { return AIMap.GetTileIndex(t.x,t.y); }
    function _axis(row) { return row.axis=="x"?AIRail.RAILTRACK_NE_SW:AIRail.RAILTRACK_NW_SE; }
    function _terminal(success) {
        if(terminal) return;
        terminal=true;
        if(success) _stage("EXECUTION_RECEIPT_EMITTED");
        local receipt={schema_version=1,executor_version="1",plan_hash=data.plan_hash,
            world_fingerprint=data.world_fingerprint,runtime_world_hash=spec.runtime_world_hash,
            result=success?"success":"failed",code=success?"NONE":(mutated?"PARTIAL_EXECUTION":"PRE_EXECUTION_FAILURE"),
            failure_reason=success?null:reason,failed_stage=success?null:stage,
            failed_entity=success?null:entity,stages=stages,actions=actions,
            created_vehicles=created,fleet=fleet,orders=orders,native_groups=native_groups};
        AILog.Info("P03_EXECUTOR_AI|P06_EXECUTION_V1|"+_json(receipt));
    }
    function RejectSetup(code) {
        stage=code=="WORLD_RESOLUTION_FAILURE"?"WORLD_VALIDATED":"PLAN_ACCEPTED";
        entity="plan"; reason=code=="WORLD_RESOLUTION_FAILURE"?"WORLD_VALIDATION_FAILED":"PLAN_REJECTED";
        spec.runtime_world_hash=null; _terminal(false);
    }
    function _preflight() {
        _require(spec.version==1 && spec.executor_version=="1", "UNSUPPORTED_EXECUTION");
        local seen={};
        foreach(row in spec.actions) {
            local a=row.action; local c=row.candidate; entity=a.construction_id;
            _require(!(a.construction_id in seen),"DUPLICATE_ACTION");
            _require(a.mode==c.mode && a.kind==c.kind && a.candidate_id==c.candidate_id,"ACTION_MISMATCH");
            foreach(dep in a.depends_on) _require(dep in seen,"DEPENDENCY_FAILED");
            seen[a.construction_id] <- true;
            if(c.kind=="segment") {
                foreach(t in c.tiles) _require(AITile.GetSlope(_tile(t))==AITile.SLOPE_FLAT,"UNSUPPORTED_GEOMETRY");
            } else {
                for(local y=0;y<row.height;y++) for(local x=0;x<row.width;x++) {
                    local tile=AIMap.GetTileIndex(row.site.tile.x+x,row.site.tile.y+y);
                    _require(AITile.IsBuildable(tile) && AITile.GetSlope(tile)==AITile.SLOPE_FLAT,"UNSUPPORTED_GEOMETRY");
                }
            }
        }
        foreach(g in plan.fleet.groups) {
            entity=g.fleet_group_id;
            local binding=spec.groups[g.fleet_group_id]; local comp=g.composition;
            if(g.mode=="road") {
                local engine=spec.engines[comp.vehicle_type].engine_id;
                _require(AIRoad.GetRoadVehicleTypeForCargo(binding.cargo_id)==
                    (binding.station_kind=="truck"?AIRoad.ROADVEHTYPE_TRUCK:AIRoad.ROADVEHTYPE_BUS),"BINDING_MISMATCH");
                _require(AIEngine.CanRefitCargo(engine,binding.cargo_id) && AIEngine.CanRunOnRoad(engine,binding.road_type),"BINDING_MISMATCH");
            } else {
                local engine=spec.engines[comp.locomotive_type].engine_id;
                _require(AIEngine.CanRunOnRail(engine,binding.rail_type) && AIEngine.HasPowerOnRail(engine,binding.rail_type) && AIEngine.CanPullCargo(engine,binding.cargo_id),"BINDING_MISMATCH");
                foreach(w in comp.wagons) {
                    local wagon=spec.engines[w.wagon_type].engine_id;
                    _require(AIEngine.CanRefitCargo(wagon,binding.cargo_id) && AIEngine.CanRunOnRail(wagon,binding.rail_type),"BINDING_MISMATCH");
                }
            }
            _require(g.start_day==0 && g.route_ids.len()==1 && g.order_mode=="repeat_service","UNSUPPORTED_SERVICE");
        }
        foreach(r in plan.routes) {
            entity=r.route_id;
            _require(r.stops.len()==3 && r.stops[0].role=="pickup" &&
                r.stops[1].role=="delivery" && r.stops[2].role=="depot","UNSUPPORTED_SERVICE");
        }
        local names=[]; foreach(name,b in spec.engines) names.append(name); names.sort();
        foreach(name in names) {
            local b=spec.engines[name];
            entity=name;
            _require(AIEngine.IsBuildable(b.engine_id) && AIEngine.GetName(b.engine_id)==b.engine_name &&
                AIEngine.GetVehicleType(b.engine_id)==(b.mode=="road"?AIVehicle.VT_ROAD:AIVehicle.VT_RAIL),"BINDING_MISMATCH");
            _require(!AIEngine.IsArticulated(b.engine_id),"UNSUPPORTED_EXECUTION");
            if(b.mode=="rail") _require(AIEngine.IsWagon(b.engine_id)==b.is_wagon,"BINDING_MISMATCH");
        }
        local ids=[]; foreach(id,g in spec.groups) ids.append(id); ids.sort();
        foreach(id in ids) {
            local g=spec.groups[id];
            _require(AICargo.IsValidCargo(g.cargo_id) && AICargo.GetCargoLabel(g.cargo_id)==g.cargo_label,"BINDING_MISMATCH");
            if("road_type" in g) _require(AIRoad.IsRoadTypeAvailable(g.road_type),"BINDING_MISMATCH");
            else _require(AIRail.IsRailTypeAvailable(g.rail_type) && AIRail.GetName(g.rail_type)==g.rail_name,"BINDING_MISMATCH");
        }
    }
    function _command(api,args) { _event("command_start",{entity=entity,api=api,args=args}); }

    function _verify_action(row) {
        local c=row.candidate; local tiles=[]; local station=null; local depot=null;
        if(c.kind=="segment") {
            foreach(t in c.tiles) tiles.append(_tile(t));
            if(c.mode=="road") {
                AIRoad.SetCurrentRoadType(row.network_type);
                for(local i=1;i<tiles.len();i++) _require(AIRoad.AreRoadTilesConnected(tiles[i-1],tiles[i]),"VERIFICATION_FAILED");
            } else {
                foreach(t in tiles) _require(AIRail.IsRailTile(t) && AIRail.GetRailType(t)==row.network_type &&
                    (AIRail.GetRailTracks(t)&_axis(row))==_axis(row),"VERIFICATION_FAILED");
            }
        } else {
            local t=_tile(row.site.tile);
            for(local y=0;y<row.height;y++) for(local x=0;x<row.width;x++) tiles.append(AIMap.GetTileIndex(row.site.tile.x+x,row.site.tile.y+y));
            if(c.kind=="station") {
                station=AIStation.GetStationID(t);
                _require(AIStation.IsValidStation(station),"VERIFICATION_FAILED");
                foreach(tile in tiles) {
                    _require(AIStation.GetStationID(tile)==station && (c.mode=="road"?AIRoad.IsRoadStationTile(tile):AIRail.IsRailStationTile(tile)),"VERIFICATION_FAILED");
                    if(c.mode=="rail") _require(AIRail.GetRailType(tile)==row.network_type && (AIRail.GetRailTracks(tile)&_axis(row))==_axis(row),"VERIFICATION_FAILED");
                }
                if(c.mode=="road") _require(AIRoad.GetRoadStationFrontTile(t)==_tile(row.front),"VERIFICATION_FAILED");
            } else {
                depot=t;
                _require(c.mode=="road"?AIRoad.IsRoadDepotTile(t):AIRail.IsRailDepotTile(t),"VERIFICATION_FAILED");
                _require((c.mode=="road"?AIRoad.GetRoadDepotFrontTile(t):AIRail.GetRailDepotFrontTile(t))==_tile(row.front),"VERIFICATION_FAILED");
                if(c.mode=="rail") _require(AIRail.GetRailType(t)==row.network_type,"VERIFICATION_FAILED");
                else _require(AIRoad.AreRoadTilesConnected(t,_tile(row.front)),"VERIFICATION_FAILED");
            }
            facilities[c.site_id] <- t;
        }
        return {construction_id=row.action.construction_id,candidate_id=c.candidate_id,
            mode=c.mode,kind=c.kind,tiles=tiles,station_id=station,depot_tile=depot};
    }
    function _build(row) {
        local a=row.action; local c=row.candidate; entity=a.construction_id;
        foreach(dep in a.depends_on) _require(dep in built,"DEPENDENCY_FAILED");
        _require(!(a.construction_id in built),"DUPLICATE_ACTION");
        _event("action_start",{entity=entity,candidate_id=c.candidate_id});
        if(c.mode=="road") AIRoad.SetCurrentRoadType(row.network_type);
        else AIRail.SetCurrentRailType(row.network_type);
        if(c.kind=="segment") {
            local tiles=c.tiles;
            if(c.mode=="road") {
                for(local i=1;i<tiles.len();i++) {
                    local from=_tile(tiles[i-1]); local to=_tile(tiles[i]);
                    if(!AIRoad.AreRoadTilesConnected(from,to)) {
                        _command("BuildRoad",[from,to]); mutated=true;
                        _require(AIRoad.BuildRoad(from,to),"BUILD_COMMAND_FAILED");
                    }
                    _event("segment_step",{entity=entity,from_tile=from,to_tile=to});
                }
            } else {
                foreach(t in tiles) {
                    local tile=_tile(t);
                    if(!AIRail.IsRailTile(tile) || (AIRail.GetRailTracks(tile)&_axis(row))!=_axis(row)) {
                        _command("BuildRailTrack",[tile,_axis(row)]); mutated=true;
                        _require(AIRail.BuildRailTrack(tile,_axis(row)),"BUILD_COMMAND_FAILED");
                    }
                    _event("segment_step",{entity=entity,tile=tile});
                }
            }
        } else {
            local tile=_tile(row.site.tile); local front=_tile(row.front);
            _command(c.mode+"_"+c.kind,[tile,front]); mutated=true;
            local ok=false;
            if(c.mode=="road") {
                ok=c.kind=="station"?AIRoad.BuildRoadStation(tile,front,row.station_kind=="truck"?AIRoad.ROADVEHTYPE_TRUCK:AIRoad.ROADVEHTYPE_BUS,AIStation.STATION_NEW):AIRoad.BuildRoadDepot(tile,front);
            } else {
                ok=c.kind=="station"?AIRail.BuildRailStation(tile,_axis(row),row.num_platforms,row.platform_length,AIStation.STATION_NEW):AIRail.BuildRailDepot(tile,front);
            }
            _require(ok,"BUILD_COMMAND_FAILED");
            if(c.mode=="road" && c.kind=="depot" && !AIRoad.AreRoadTilesConnected(tile,front)) {
                _command("BuildRoad",[tile,front]);
                _require(AIRoad.BuildRoad(tile,front),"BUILD_COMMAND_FAILED");
                _event("facility_connector",{entity=entity,from_tile=tile,to_tile=front});
            }
        }
        local result=_verify_action(row); actions.append(result); built[a.construction_id] <- true;
        _event("action_success",{entity=entity,candidate_id=c.candidate_id});
    }
    function _route(id) { foreach(r in plan.routes) if(r.route_id==id) return r; throw "UNKNOWN_ROUTE"; }
    function _buy(group, name, role, depot, cargo) {
        local engine=spec.engines[name].engine_id; entity=group.fleet_group_id;
        _command("BuildVehicle",[depot,engine,cargo]); mutated=true;
        local id=role=="locomotive"?AIVehicle.BuildVehicle(depot,engine):AIVehicle.BuildVehicleWithRefit(depot,engine,cargo);
        _require(AIVehicle.IsValidVehicle(id),"PURCHASE_FAILED");
        created.append({vehicle_id=id,group_id=group.fleet_group_id,route_id=group.route_ids[0],engine_id=engine,role=role});
        _event("purchase",{entity=entity,vehicle_id=id,engine_id=engine,role=role});
        _require(AIVehicle.GetEngineType(id)==engine,"VERIFICATION_FAILED");
        return id;
    }
    function _purchase() {
        foreach(g in plan.fleet.groups) {
            local binding=spec.groups[g.fleet_group_id]; local route=_route(g.route_ids[0]);
            entity=g.fleet_group_id; _command("CreateGroup",[g.mode]); mutated=true;
            local native_id=AIGroup.CreateGroup(g.mode=="road"?AIVehicle.VT_ROAD:AIVehicle.VT_RAIL,AIGroup.GROUP_INVALID);
            _require(AIGroup.IsValidGroup(native_id),"GROUP_CREATION_FAILED");
            group_ids[g.fleet_group_id] <- native_id;
            local native_row={group_id=g.fleet_group_id,runtime_id=native_id,mode=g.mode,vehicle_count=0,verified=false};
            native_groups.append(native_row);
            _command("EnableAutoReplaceProtection",[native_id,true]);
            _require(AIGroup.EnableAutoReplaceProtection(native_id,true),"GROUP_CONFIGURATION_FAILED");
            local depot=facilities[route.stops[2].location_id];
            for(local n=0;n<g.count;n++) {
                local comp=g.composition; local id=null;
                if(g.mode=="road") id=_buy(g,comp.vehicle_type,"road",depot,binding.cargo_id);
                else {
                    id=_buy(g,comp.locomotive_type,"locomotive",depot,binding.cargo_id);
                    foreach(w in comp.wagons) for(local j=0;j<w.count;j++) {
                        local wagon=_buy(g,w.wagon_type,"wagon",depot,binding.cargo_id);
                        _command("MoveWagon",[wagon,0,id,AIVehicle.GetNumWagons(id)-1]);
                        _require(AIVehicle.MoveWagon(wagon,0,id,AIVehicle.GetNumWagons(id)-1),"CONSIST_ASSEMBLY_FAILED");
                    }
                }
                local engine_ids=[];
                if(g.mode=="road") engine_ids.append(spec.engines[comp.vehicle_type].engine_id);
                else {
                    engine_ids.append(spec.engines[comp.locomotive_type].engine_id);
                    foreach(w in comp.wagons) for(local j=0;j<w.count;j++) engine_ids.append(spec.engines[w.wagon_type].engine_id);
                    _require(AIVehicle.GetNumWagons(id)==engine_ids.len(),"VERIFICATION_FAILED");
                    foreach(i,e in engine_ids) _require(AIVehicle.GetWagonEngineType(id,i)==e,"VERIFICATION_FAILED");
                    _require(AIVehicle.GetLength(id)>0 && AIVehicle.GetLength(id)<=binding.max_length_16ths,"VERIFICATION_FAILED");
                }
                _require(AIVehicle.GetCapacity(id,binding.cargo_id)==binding.expected_capacity,"VERIFICATION_FAILED");
                _command("MoveVehicle",[native_id,id]);
                _require(AIGroup.MoveVehicle(native_id,id),"GROUP_ASSIGNMENT_FAILED");
                native_row.vehicle_count++;
                fleet.append({group_id=g.fleet_group_id,vehicle_id=id,engine_ids=engine_ids,
                    capacity=AIVehicle.GetCapacity(id,binding.cargo_id),length_16ths=AIVehicle.GetLength(id)});
            }
        }
    }
    function _assign_orders() {
        foreach(v in fleet) {
            local g=null; foreach(group in plan.fleet.groups) if(group.fleet_group_id==v.group_id) g=group;
            local route=_route(g.route_ids[0]); entity=v.vehicle_id.tostring();
            local result={group_id=g.fleet_group_id,route_id=route.route_id,vehicle_id=v.vehicle_id,targets=[],flags=[],assigned=false};
            orders.append(result);
            foreach(i,stop in route.stops) {
                local target=facilities[stop.location_id];
                local flags=i==0?AIOrder.OF_NO_UNLOAD:(i==1?(AIOrder.OF_UNLOAD|AIOrder.OF_NO_LOAD):AIOrder.OF_NONE);
                _command("AppendOrder",[v.vehicle_id,target,flags]);
                _require(AIOrder.AppendOrder(v.vehicle_id,target,flags),"ORDER_ASSIGNMENT_FAILED");
                result.targets.append(target); result.flags.append(flags);
                _event("order",{entity=entity,position=i,target=target,flags=flags});
            }
            result.assigned=true;
        }
    }
    function _verify() {
        foreach(row in spec.actions) { entity=row.action.construction_id; _verify_action(row); }
        foreach(g in plan.fleet.groups) {
            local count=0; foreach(v in fleet) if(v.group_id==g.fleet_group_id) count++;
            entity=g.fleet_group_id; local native_id=group_ids[g.fleet_group_id];
            _require(count==g.count && AIGroup.IsValidGroup(native_id) &&
                AIGroup.GetVehicleType(native_id)==(g.mode=="road"?AIVehicle.VT_ROAD:AIVehicle.VT_RAIL) &&
                AIGroup.GetNumVehicles(native_id,g.mode=="road"?AIVehicle.VT_ROAD:AIVehicle.VT_RAIL)==g.count &&
                AIGroup.GetAutoReplaceProtection(native_id),"VERIFICATION_FAILED");
            foreach(row in native_groups) if(row.group_id==g.fleet_group_id) row.verified=true;
        }
        foreach(v in fleet) {
            entity=v.vehicle_id.tostring(); local b=spec.groups[v.group_id];
            _require(AIVehicle.IsValidVehicle(v.vehicle_id) && AIVehicle.GetGroupID(v.vehicle_id)==group_ids[v.group_id] && AIVehicle.GetEngineType(v.vehicle_id)==v.engine_ids[0] &&
                AIVehicle.GetCapacity(v.vehicle_id,b.cargo_id)==v.capacity,"VERIFICATION_FAILED");
            if("rail_type" in b) {
                _require(AIVehicle.GetNumWagons(v.vehicle_id)==v.engine_ids.len() &&
                    AIVehicle.GetLength(v.vehicle_id)<=b.max_length_16ths,"VERIFICATION_FAILED");
                foreach(i,e in v.engine_ids) _require(AIVehicle.GetWagonEngineType(v.vehicle_id,i)==e,"VERIFICATION_FAILED");
            }
        }
        foreach(o in orders) {
            entity=o.vehicle_id.tostring();
            _require(AIOrder.GetOrderCount(o.vehicle_id)==3,"VERIFICATION_FAILED");
            foreach(i,t in o.targets) _require(AIOrder.GetOrderDestination(o.vehicle_id,i)==t &&
                AIOrder.GetOrderFlags(o.vehicle_id,i)==o.flags[i] &&
                (i==2?AIOrder.IsGotoDepotOrder(o.vehicle_id,i):AIOrder.IsGotoStationOrder(o.vehicle_id,i)),"VERIFICATION_FAILED");
        }
        // Keep all vehicles stopped until every route's setup has been checked.
        foreach(v in fleet) {
            entity=v.vehicle_id.tostring();
            _command("StartStopVehicle",[v.vehicle_id]);
            _require(AIVehicle.IsStoppedInDepot(v.vehicle_id) && AIVehicle.StartStopVehicle(v.vehicle_id),"ACTIVATION_FAILED");
        }
    }
    function Run() {
        if(terminal) return;
        try {
            _stage("PLAN_ACCEPTED"); _stage("WORLD_VALIDATED"); _preflight();
            _stage("INFRASTRUCTURE_STARTED"); foreach(row in spec.actions) _build(row);
            _stage("INFRASTRUCTURE_COMPLETED"); _stage("FLEET_STARTED"); _purchase();
            _stage("FLEET_COMPLETED"); _stage("ORDERS_STARTED"); _assign_orders();
            _stage("ORDERS_COMPLETED"); stage="SETUP_VERIFIED"; _verify();
            _stage("SETUP_VERIFIED"); _terminal(true);
        } catch(error) {
            if(stage=="INFRASTRUCTURE_STARTED") _event("action_failure",{entity=entity,reason=reason});
            _event("failure",{entity=entity,stage=stage,reason=reason,command_error=AIError.GetLastError()});
            _terminal(false);
        }
    }
}
