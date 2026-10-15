require("vehicle.nut");
class FreightDeliveryProof extends RoadVehicleProof {
    choice=null; dplan=null; dstage=0; dvehicle=-1; dused=null; drequests=0; dfailed=false;
    dcost=0; dstations=null; monitors=false; monitor_pickup=0; monitor_delivery=0;
    period=null; closed=null; baseline=null; obs_stage=0; diagnostic=null; first_rejection=0;
    function Reject(gate) {
        diagnostic[gate]++;if(first_rejection==0)first_rejection=gate+1;
    }
    function CargoAt(t,c) {
        local n=0;local found=-1;local radius=GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP);
        for(local y=t/64-radius;y<=t/64+radius;y++) for(local x=t%64-radius;x<=t%64+radius;x++) {
            if(x<0||y<0||x>=64||y>=64) continue;
            local i=GSIndustry.GetIndustryID(y*64+x);
            if(GSIndustry.IsValidIndustry(i) && GSIndustry.GetLastMonthProduction(i,c)>0 && found!=i) {
                if(found!=-1) return -2;found=i;n++;
            }
        }
        return found;
    }
    function Tiles(a) {
        local out=[];local t=a[5];local end=a[9];local step=end>t ? 1 : -1;
        for(local i=0;i<49;i++) {out.append(t);if(t==end) break;t+=step;}
        if(t!=end) return null;
        t=end;end=a[7];step=end>t ? 64 : -64;
        for(local i=0;i<49;i++) {if(t!=a[9]) out.append(t);if(t==end) break;t+=step;}
        if(t!=end || out.len()>47) return null;
        return out;
    }
    function Execute(i) {
        local a=choice.a;
        if(i==0) return GSRoad.BuildRoadFull(a[5],a[9]);
        if(i==1) return GSRoad.BuildRoadFull(a[9],a[7]);
        // Add the perpendicular depot entrance; full road endpoints alone lack this bit.
        if(i==2) return GSRoad.BuildRoad(a[5],a[8]);
        if(i==3||i==4) return GSRoad.BuildRoadStation(a[i==3?4:6],a[i==3?5:7],GSRoad.ROADVEHTYPE_TRUCK,GSStation.STATION_NEW);
        if(i==5) return GSRoad.BuildRoadDepot(a[8],a[5]);
        if(i==6) return GSVehicle.BuildVehicle(a[8],a[3]);
        if(i==7||i==8) return GSOrder.AppendOrder(dvehicle,a[i==7?4:6],i==7?GSOrder.OF_FULL_LOAD:GSOrder.OF_NO_LOAD);
        return GSVehicle.StartStopVehicle(dvehicle);
    }
    function RecordConstruction(i,result,quoted,cost,funds) {}
    function Quote(i) {
        local account=GSAccounting();local test=GSTestMode();local result=Execute(i);local cost=account.GetCosts();
        test=null;account=null;return [i==6?result==0:result,cost];
    }
    function Route(a) {
        local tiles=Tiles(a);if(tiles==null) return false;
        foreach(t in tiles) if(GSTile.GetOwner(t)!=0 || !GSRoad.IsRoadTile(t)) return false;
        for(local i=1;i<tiles.len();i++) if(!Linked(tiles[i-1],tiles[i])) return false;
        if(!GSRoad.IsRoadStationTile(a[4])||!GSRoad.IsRoadStationTile(a[6])||
            GSRoad.GetRoadStationFrontTile(a[4])!=a[5]||GSRoad.GetRoadStationFrontTile(a[6])!=a[7]||
            !GSRoad.IsRoadDepotTile(a[8])||GSRoad.GetRoadDepotFrontTile(a[8])!=a[5]) return false;
        foreach(t in [a[4],a[6],a[8]]) if(GSTile.GetOwner(t)!=0) return false;
        return Linked(a[4],a[5])&&Linked(a[6],a[7])&&Linked(a[8],a[5])&&
            GSStation.GetStationID(a[4])!=GSStation.GetStationID(a[6]);
    }
    function Select() {
        diagnostic=[];for(local i=0;i<18;i++)diagnostic.append(0);first_rejection=0;
        if(GSVehicleList().Count()!=0 || GSGame.IsPaused()) return "INVALID_WORLD";
        local list=GSEngineList(GSVehicle.VT_ROAD);local engines=[];local count=0;
        for(local e=list.Begin();!list.IsEnd();e=list.Next()) {count++;diagnostic[0]++;if(count>32)return "ENGINE_LIMIT";if(Compatible(e)){diagnostic[1]++;engines.append(e);}}
        engines.sort();local layouts=0;
        foreach(e in engines) {
            local cargo=GSEngine.GetCargoType(e);local srcs=GSIndustryList_CargoProducing(cargo);local dsts=GSIndustryList_CargoAccepting(cargo);
            if(srcs.Count()>32||dsts.Count()>32) return "INDUSTRY_LIMIT";
            for(local src=srcs.Begin();!srcs.IsEnd();src=srcs.Next()) for(local dst=dsts.Begin();!dsts.IsEnd();dst=dsts.Next()) {
                diagnostic[2]++;
                if(src==dst){Reject(3);continue;}
                if(GSIndustry.GetLastMonthProduction(src,cargo)<=0){Reject(4);continue;}
                if(GSIndustry.IsCargoAccepted(dst,cargo)!=GSIndustry.CAS_ACCEPTED){Reject(5);continue;}
                local s=GSIndustry.GetLocation(src);local d=GSIndustry.GetLocation(dst);
                for(local sy=1;sy<=3;sy++) for(local dx=1;dx<=3;dx++) {
                    if(layouts==64)return "SITE_SEARCH_EXHAUSTED";layouts++;diagnostic[6]++;
                    local ss=s-64*sy-1;local ds=d-64-dx;
                    local sf=ss+1;local df=ds-64;local bend=(ss/64)*64+df%64;local depot=sf-64;
                    local a=[src,dst,cargo,e,ss,sf,ds,df,depot,bend];local tiles=Tiles(a);
                    if(tiles==null||sf==bend||bend==df||ss%64<1||ds%64<1||sf/64!=ss/64||df/64!=ds/64-1){Reject(7);continue;}
                    local all=clone tiles;all.append(ss);all.append(ds);all.append(depot);
                    local seen={};local ok=true;local height=-1;
                    foreach(t in all) {
                        if(!GSMap.IsValidTile(t)||t<65||t>4030||t in seen||!Vacant(t)) {Reject(8);ok=false;break;}
                        seen[t]<-true;local h=GSTile.GetMinHeight(t);if(height==-1)height=h;if(h!=height){Reject(9);ok=false;break;}
                    }
                    if(!ok)continue;
                    local radius=GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP);
                    if(radius<1||radius>4){Reject(10);continue;}
                    if(CargoAt(ss,cargo)!=src){Reject(11);continue;}
                    if(GSTile.GetCargoProduction(ss,cargo,1,1,radius)!=1){Reject(12);continue;}
                    if(GSTile.GetCargoAcceptance(ds,cargo,1,1,radius)<8){Reject(13);continue;}
                    // The intended acceptor must actually have a tile in this catchment.
                    local covered=false;for(local y=ds/64-radius;y<=ds/64+radius;y++)for(local x=ds%64-radius;x<=ds%64+radius;x++)
                        if(x>=0&&y>=0&&x<64&&y<64&&GSIndustry.GetIndustryID(y*64+x)==dst)covered=true;
                    if(!covered){Reject(14);continue;}
                    choice={a=a,f=[GSIndustry.GetIndustryType(src),GSIndustry.GetIndustryType(dst),s,d,
                        GSIndustry.GetLastMonthProduction(src,cargo),GSEngine.GetCapacity(e),GSEngine.GetPrice(e),radius],ceiling=0};
                    local total=choice.f[6];ok=total>0;
                    // Vehicle test requires the real owned depot; reserve native engine price now.
                    for(local i=0;i<6;i++) {local q=Quote(i);if(!q[0]||q[1]<=0)ok=false;total+=q[1];}
                    if(!ok)Reject(15);
                    else if(total>100000)Reject(16);
                    else if(total>GSCompany.GetBankBalance(0))Reject(17);
                    else {choice.ceiling=total;return "READY";}
                    choice=null;
                }
            }
        }
        return "NO_NATIVE_FEASIBLE_OD";
    }
    function Snapshot() {
        local s=[GetTick(),GSDate.GetCurrentDate(),GSGame.IsPaused()?1:0,GSCompany.GetBankBalance(0),
            dvehicle,-1,-1,0,-1,-1,0,0,0,-1,-1,0,-1,-1,
            GSCompany.GetQuarterlyCargoDelivered(0,GSCompany.CURRENT_QUARTER),GSCompany.GetQuarterlyIncome(0,GSCompany.CURRENT_QUARTER),
            0,-1,dstage,dcost,monitor_pickup,monitor_delivery,GetTick(),1,0,0];
        if(choice==null)return s;local a=choice.a;
        if(dstage>=5) {
            s[16]=GSStation.GetStationID(a[4]);s[17]=GSStation.GetStationID(a[6]);
            s[15]=GSStation.GetCargoWaiting(s[16],a[2]);s[21]=GSIndustry.GetCargoLastAcceptedDate(a[1],a[2]);
        }
        if(dstage>=6)s[28]=Route(a)?1:0;
        if(dvehicle>=0&&GSVehicle.IsValidVehicle(dvehicle)) {
            s[5]=GSVehicle.GetOwner(dvehicle);s[6]=GSVehicle.GetEngineType(dvehicle);s[7]=GSVehicle.GetCapacity(dvehicle,a[2]);
            s[8]=GSVehicle.GetLocation(dvehicle);s[9]=GSVehicle.GetState(dvehicle);s[10]=GSVehicle.GetCurrentSpeed(dvehicle);
            s[11]=GSVehicle.GetCargoLoad(dvehicle,a[2]);s[12]=GSOrder.GetOrderCount(dvehicle);
            if(s[12]>0)s[13]=GSOrder.GetOrderDestination(dvehicle,0);if(s[12]>1)s[14]=GSOrder.GetOrderDestination(dvehicle,1);
            s[20]=GSVehicle.GetProfitThisYear(dvehicle);
            if(s[12]==2)s[29]=GSOrder.IsGotoStationOrder(dvehicle,0)&&GSOrder.IsGotoStationOrder(dvehicle,1)&&
                GSOrder.GetOrderFlags(dvehicle,0)==GSOrder.OF_FULL_LOAD&&GSOrder.GetOrderFlags(dvehicle,1)==GSOrder.OF_NO_LOAD?1:0;
        }
        return s;
    }
    function Quarter(date) {return GSDate.GetYear(date)*4+(GSDate.GetMonth(date)-1)/3;}
    function ObservationBudget() {
        local a=choice.a;local distance=GSMap.DistanceManhattan(a[4],a[6])+2;
        local budget=2048+128*distance;return budget>4440?4440:budget;
    }
    function Period(s) {
        local q=Quarter(s[1]);
        if(period==null){period=q;closed=[];}
        if(q!=period) {
            if(q!=period+1||closed.len()!=0)throw "PERIOD_LINEAGE_BROKEN";
            closed=[s[0],s[1],period,GSCompany.GetQuarterlyCargoDelivered(0,1),GSCompany.GetQuarterlyIncome(0,1)];
            period=q;
        }
        local e=[q];e.extend(closed);return e;
    }
    function Observe(phase,r) {
        local first=GetTick();local prev=first;local date=GSDate.GetCurrentDate();local polls=0;local budget=ObservationBudget();
        local last_tile=-1;local last_move=first;
        for(local i=0;i<=budget;i++) {
            local s=Snapshot();polls++;r.s=s;s[26]=first;s[27]=polls;
            if(s[1]<baseline[1]||s[1]-baseline[1]>60||GSDate.GetYear(s[1])!=GSDate.GetYear(baseline[1])){r.status="WINDOW_EXHAUSTED";break;}
            r.e<-Period(s);
            if(s[2]!=0){r.status="PAUSED";break;}
            if(i>0&&s[0]<=prev){r.status="CLOCK_STALLED";break;}
            if(s[0]-first>budget||s[1]-date>60){r.status="WINDOW_EXHAUSTED";break;}
            if(!Route(choice.a)||GSVehicleList().Count()!=1||s[5]!=0||s[6]!=choice.a[3]||s[7]!=choice.f[5]||s[12]!=2||
                s[13]!=choice.a[4]||s[14]!=choice.a[6]||GSOrder.GetOrderFlags(dvehicle,0)!=GSOrder.OF_FULL_LOAD||
                GSOrder.GetOrderFlags(dvehicle,1)!=GSOrder.OF_NO_LOAD||!GSOrder.IsGotoStationOrder(dvehicle,0)||!GSOrder.IsGotoStationOrder(dvehicle,1))
                {r.status="READBACK_MISMATCH";break;}
            if(!GSIndustry.IsValidIndustry(choice.a[1])||GSIndustry.IsCargoAccepted(choice.a[1],choice.a[2])!=GSIndustry.CAS_ACCEPTED){r.status="DESTINATION_LOST";break;}
            if(s[9]!=GSVehicle.VS_RUNNING&&s[9]!=GSVehicle.VS_AT_STATION&&s[9]!=GSVehicle.VS_BROKEN){r.status="INVALID_VEHICLE_STATE";break;}
            if(phase==2&&s[8]!=choice.a[6]&&s[11]!=choice.f[5]){r.status="LOST_CARGO";break;}
            if(s[8]!=last_tile){last_tile=s[8];last_move=s[0];}
            if(phase==2&&s[0]-last_move>2048){r.status="MOVEMENT_STALLED";break;}
            local cargo=s[18]+(closed.len()==0?0:closed[3]);
            local income=s[19]+(closed.len()==0?0:closed[4]);
            local ok=phase==0?s[15]>0:(phase==1?s[8]==choice.a[4]&&s[11]==choice.f[5]:
                (phase==2?s[8]==choice.a[6]&&s[9]==GSVehicle.VS_AT_STATION&&s[11]>0:
                 s[11]==0&&cargo>baseline[18]&&income>baseline[19]&&s[20]>baseline[20]));
            if(ok){r.status="OBSERVED";obs_stage++;break;}
            if(s[0]-first>=budget||i==budget){r.status="WINDOW_EXHAUSTED";break;}
            prev=s[0];Sleep(1);
        }
    }
    function Handle(q) {
        if(typeof q!="table"||q.len()!=6)return;
        foreach(k in ["protocol","op","request_id","plan","arg","max_cost"])if(!(k in q))return;
        if(q.protocol!=1||typeof q.op!="string"||typeof q.request_id!="string"||q.request_id.len()>32||
            typeof q.plan!="string"||q.plan.len()!=64||typeof q.arg!="integer"||q.arg<0||q.arg>9||q.max_cost!=100000)return;
        if(dused==null)dused={};if(q.request_id in dused||drequests>=26)return;dused[q.request_id]<-true;drequests++;
        local r={protocol=1,op=q.op,request_id=q.request_id,plan=q.plan,arg=q.arg,max_cost=q.max_cost,status="REJECTED",
            a=[-1,-1,-1,-1,-1,-1,-1,-1,-1,-1],f=[0,0,0,0,0,0,0,0],s=[]};
        local company=GSCompanyMode(0);dcost=0;
        if(!GSCompanyMode.IsValid()||GSCompany.ResolveCompanyID(0)!=0)r.status="INVALID_COMPANY";
        else {
            GSRoad.SetCurrentRoadType(GSRoad.ROADTYPE_ROAD);
            if(GSRoad.GetCurrentRoadType()!=0||!GSRoad.IsRoadTypeAvailable(0))r.status="UNSUPPORTED_ROAD_TYPE";
            else if(q.op=="inspect"&&choice==null&&!dfailed&&dstage==0)r.status=Select();
            else if(choice==null||(dfailed&&q.op!="read")||(dplan!=null&&q.plan!=dplan))r.status="OUT_OF_ORDER";
            else if(q.op=="read")r.status="READ";
            else if(q.op=="build"&&q.arg==dstage&&dstage<10) {
                if(GSGame.IsPaused()||!Compatible(choice.a[3])||GSIndustry.GetLastMonthProduction(choice.a[0],choice.a[2])<=0||
                    GSIndustry.IsCargoAccepted(choice.a[1],choice.a[2])!=GSIndustry.CAS_ACCEPTED)r.status="PREREQUISITE_FAILED";
                else if(dstage>=6&&!Route(choice.a))r.status="INVALID_ROUTE";
                else if(dstage>=7&&(GSVehicleList().Count()!=1||!GSVehicle.IsInDepot(dvehicle)||GSVehicle.GetLocation(dvehicle)!=choice.a[8]||
                    GSVehicle.GetOwner(dvehicle)!=0||GSVehicle.GetCargoLoad(dvehicle,choice.a[2])!=0||GSOrder.GetOrderCount(dvehicle)!=dstage-7))r.status="READBACK_MISMATCH";
                else {
                    local test=Quote(dstage);local funds=GSCompany.GetBankBalance(0);
                    if(!test[0]||test[1]<0||test[1]>choice.ceiling||test[1]>funds||
                        (dstage==6&&test[1]!=choice.f[6]))r.status="ADMISSION_FAILED";
                    else {
                        dplan=q.plan;dfailed=true;
                        if(dstage==9) {
                            baseline=Snapshot();monitor_pickup=GSCargoMonitor.GetIndustryPickupAmount(0,choice.a[2],choice.a[0],true);
                            monitor_delivery=GSCargoMonitor.GetIndustryDeliveryAmount(0,choice.a[2],choice.a[1],true);monitors=true;
                            if(monitor_pickup!=0||monitor_delivery!=0)throw "NONZERO_MONITOR_BASELINE";
                        }
                        local accounting=GSAccounting();local result=Execute(dstage);dcost=accounting.GetCosts();accounting=null;
                        RecordConstruction(dstage,result,test[1],dcost,funds);
                        if(dstage==6&&GSVehicle.IsValidVehicle(result))dvehicle=result;
                        if((dstage==6&&dvehicle<0)||(dstage!=6&&!result)||dcost!=test[1]||
                            (dstage<9&&funds-GSCompany.GetBankBalance(0)!=dcost))r.status="CONSTRUCTION_FAILED";
                        else {dstage++;dfailed=false;r.status="BUILT";}
                    }
                }
            } else if(q.op=="observe"&&dstage==10&&q.arg==obs_stage&&obs_stage<4)Observe(q.arg,r);
            else if(q.op=="finish"&&dstage==10&&obs_stage==4&&monitors) {
                monitor_pickup=GSCargoMonitor.GetIndustryPickupAmount(0,choice.a[2],choice.a[0],false);
                monitor_delivery=GSCargoMonitor.GetIndustryDeliveryAmount(0,choice.a[2],choice.a[1],false);monitors=false;r.status="DELIVERED";
            }
        }
        if(choice!=null){r.a=choice.a;r.f=choice.f;}
        if(r.s.len()==0)r.s=Snapshot();
        if(dstage>=9&&!("e" in r))r.e<-Period(r.s);if(q.op=="inspect"&&choice!=null)r.s[23]=choice.ceiling;
        // Failure-only versioned overlay: no extra JSON fields or response growth.
        if(q.op=="inspect"&&choice==null&&diagnostic!=null) {
            for(local i=0;i<10;i++)r.a[i]=diagnostic[i];
            for(local i=0;i<8;i++)r.f[i]=diagnostic[i+10];
            r.s[28]=first_rejection;r.s[29]=2;
        }
        foreach(v in r.s)if(v < -2147483648||v>2147483647)throw "DELIVERY_RESPONSE_OUT_OF_BOUNDS";
        if(r.status!="READY"&&r.status!="READ"&&r.status!="BUILT"&&r.status!="OBSERVED"&&r.status!="DELIVERED")dfailed=true;
        if(!GSAdmin.Send(r))throw "DELIVERY_RESPONSE_SEND_FAILED";GSLog.Info("DELIVERY_RESPONSE "+q.request_id+" "+r.status);
        company=null;
    }
    function Start() {
        GSLog.Info("FREIGHT_DELIVERY_READY");
        while(true){while(GSEventController.IsEventWaiting()){local e=GSEventController.GetNextEvent();
            if(e.GetEventType()==GSEvent.ET_ADMIN_PORT)Handle(GSEventAdminPort.Convert(e).GetObject());}Sleep(1);}
    }
}
