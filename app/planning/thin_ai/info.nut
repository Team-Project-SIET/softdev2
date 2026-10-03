class P03ExecutorInfo extends AIInfo {
    function GetAuthor() { return "Team-Project-SIET"; }
    function GetName() { return "P03ThinExecutor"; }
    function GetDescription() { return "P03 data transport and setup acknowledgement only"; }
    function GetVersion() { return 1; }
    function GetDate() { return "2026-09-28"; }
    function CreateInstance() { return "P03Executor"; }
    function GetShortName() { return "P03E"; }
    function GetAPIVersion() { return "12"; }
}

RegisterAI(P03ExecutorInfo());
