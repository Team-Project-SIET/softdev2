require("delivery.nut");
class FreightDemoProof extends FreightDeliveryProof {
    function PrepareDemo() {
        if(GSMap.GetMapSizeX()!=64||GSMap.GetMapSizeY()!=64||GSIndustry.GetIndustryCount()!=0)
            throw "DEMO_REQUIRES_EMPTY_64_MAP";
        // Default temperate coal mine/power station, verified by their native cargo lists.
        local produced=GSIndustryType.GetProducedCargo(0);local accepted=GSIndustryType.GetAcceptedCargo(1);
        if(!GSIndustryType.IsRawIndustry(0)||produced.Count()!=1||!accepted.HasItem(produced.Begin()))
            throw "DEMO_CONTENT_MISMATCH";
        if(!GSIndustryType.BuildIndustry(0,20+20*64)||!GSIndustryType.BuildIndustry(1,36+28*64))
            throw "DEMO_NATIVE_INDUSTRY_BUILD_FAILED";
        local src=-1;local dst=-1;local industries=GSIndustryList();
        for(local i=industries.Begin();!industries.IsEnd();i=industries.Next()) {
            if(GSIndustry.GetIndustryType(i)==0)src=i;if(GSIndustry.GetIndustryType(i)==1)dst=i;
        }
        if(src<0||dst<0||industries.Count()!=2)throw "DEMO_INDUSTRY_READBACK_FAILED";
        local s=GSIndustry.GetLocation(src);local d=GSIndustry.GetLocation(dst);
        local ss=s-65;local ds=d-65;local sf=ss+1;local df=ds-64;
        local a=[src,dst,produced.Begin(),-1,ss,sf,ds,df,sf-64,(ss/64)*64+df%64];
        local tiles=Tiles(a);if(tiles==null)throw "DEMO_FOOTPRINT_LIMIT";
        tiles.append(ss);tiles.append(ds);tiles.append(a[8]);
        foreach(t in tiles) {
            if(!GSMap.IsValidTile(t)||GSIndustry.IsValidIndustry(GSIndustry.GetIndustryID(t))||
                GSTile.GetSlope(t)!=0||GSTile.GetMinHeight(t)!=1||GSTile.IsWaterTile(t)||
                GSTile.GetOwner(t)!=GSCompany.COMPANY_INVALID)throw "DEMO_UNSAFE_CLEARING";
            if(!Vacant(t)&&!GSTile.DemolishTile(t))throw "DEMO_NATIVE_CLEAR_FAILED";
            if(!Vacant(t))throw "DEMO_VACANCY_READBACK_FAILED";
        }
        GSLog.Info("FREIGHT_DEMO_WORLD_READY source="+src+" destination="+dst+" cargo="+a[2]+" cleared_bound="+tiles.len());
    }
    function Start() {
        PrepareDemo();
        GSLog.Info("FREIGHT_DELIVERY_READY");
        while(true){while(GSEventController.IsEventWaiting()){local e=GSEventController.GetNextEvent();
            if(e.GetEventType()==GSEvent.ET_ADMIN_PORT)Handle(GSEventAdminPort.Convert(e).GetObject());}Sleep(1);}
    }
}
