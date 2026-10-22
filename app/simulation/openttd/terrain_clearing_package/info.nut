class TerrainClearingInfo extends GSInfo {
    function GetAuthor() { return "Team-Project-SIET"; }
    function GetName() { return "TerrainClearingProof"; }
    function GetDescription() { return "One authorized bounded tile clearing operation"; }
    function GetVersion() { return 1; }
    function GetDate() { return "2026-10-19"; }
    function CreateInstance() { return "TerrainClearingProof"; }
    function GetShortName() { return "TCP1"; }
    function GetAPIVersion() { return "15"; }
}
RegisterGS(TerrainClearingInfo());
