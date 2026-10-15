class RoadCompanyInfo extends AIInfo {
    function GetAuthor() { return "Team-Project-SIET"; }
    function GetName() { return "RoadProofCompany"; }
    function GetDescription() { return "Disposable proof company; no commands"; }
    function GetVersion() { return 1; }
    function GetDate() { return "2026-10-11"; }
    function CreateInstance() { return "RoadProofCompany"; }
    function GetShortName() { return "RPC1"; }
    function GetAPIVersion() { return "15"; }
}
RegisterAI(RoadCompanyInfo());
