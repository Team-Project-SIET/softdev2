class RoadMutationInfo extends GSInfo {
    function GetAuthor() { return "Team-Project-SIET"; }
    function GetName() { return "RoadMutationProof"; }
    function GetDescription() { return "One authorized adjacent company road segment"; }
    function GetVersion() { return 1; }
    function GetDate() { return "2026-10-11"; }
    function CreateInstance() { return "RoadMutationProof"; }
    function GetShortName() { return "RMP1"; }
    function GetAPIVersion() { return "15"; }
}
RegisterGS(RoadMutationInfo());
