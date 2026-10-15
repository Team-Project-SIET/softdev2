class NoMutationBridgeInfo extends GSInfo {
    function GetAuthor() { return "Team-Project-SIET"; }
    function GetName() { return "NoMutationBridge"; }
    function GetDescription() { return "Protocol-one AdminPort ping/ACK and read-only world_info"; }
    function GetVersion() { return 2; }
    function GetDate() { return "2026-10-05"; }
    function CreateInstance() { return "NoMutationBridge"; }
    function GetShortName() { return "NMBA"; }
    function GetAPIVersion() { return "15"; }
}
RegisterGS(NoMutationBridgeInfo());
