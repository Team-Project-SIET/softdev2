class RoadFreightInfo extends GSInfo {
    function GetAuthor() { return "Team-Project-SIET"; }
    function GetName() { return "RoadFreightProof"; }
    function GetDescription() { return "One company truck stop, access road and depot proof"; }
    function GetVersion() { return 1; }
    function GetDate() { return "2026-10-11"; }
    function CreateInstance() { return "RoadFreightProof"; }
    function GetShortName() { return "RFP1"; }
    function GetAPIVersion() { return "15"; }
}
RegisterGS(RoadFreightInfo());
