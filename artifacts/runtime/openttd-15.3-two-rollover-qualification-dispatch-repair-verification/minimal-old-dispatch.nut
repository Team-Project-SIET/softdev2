class RawObservationBridge { function Handle(request) { if(request.type != "industry_page") throw "wrong type"; return true; } }
class QualificationBridge extends RawObservationBridge {
 function Handle(request) { if(request.type == "economy_clock") return true; return base.Handle(request); }
}
class NoMutationBridge extends QualificationBridge {}
local b=NoMutationBridge();
for(local i=0;i<61;i++) if(!b.Handle({type="economy_clock"})) throw "clock failed";
if(!b.Handle({type="industry_page"})) throw "anchor failed";
