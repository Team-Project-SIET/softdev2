class RoadVehicleInfo extends GSInfo {
    function GetAuthor() { return "Team-Project-SIET"; }
    function GetName() { return "RoadFreightProof"; }
    function GetDescription() { return "One default-cargo vehicle purchase, order and start"; }
    function GetVersion() { return 1; }
    function GetDate() { return "2026-10-11"; }
    function CreateInstance() { return "RoadVehicleProof"; }
    function GetShortName() { return "RFP1"; }
    function GetAPIVersion() { return "15"; }
}
RegisterGS(RoadVehicleInfo());
