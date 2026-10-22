class D4CorridorInfo extends GSInfo {
    function GetAuthor() { return "Team-Project-SIET"; }
    function GetName() { return "D4CorridorProof"; }
    function GetDescription() { return "One authorized bounded road/station/depot corridor construction"; }
    function GetVersion() { return 1; }
    function GetDate() { return "2026-10-22"; }
    function CreateInstance() { return "D4CorridorProof"; }
    function GetShortName() { return "DCP1"; }
    function GetAPIVersion() { return "15"; }
}
RegisterGS(D4CorridorInfo());
