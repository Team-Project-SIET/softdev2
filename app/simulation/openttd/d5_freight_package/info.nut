class D5FreightInfo extends GSInfo {
    function GetAuthor() { return "Team-Project-SIET"; }
    function GetName() { return "D5FreightProof"; }
    function GetDescription() { return "One authorized bounded corridor freight cycle"; }
    function GetVersion() { return 1; }
    function GetDate() { return "2026-10-26"; }
    function CreateInstance() { return "D5FreightProof"; }
    function GetShortName() { return "DFP1"; }
    function GetAPIVersion() { return "15"; }
}
RegisterGS(D5FreightInfo());
