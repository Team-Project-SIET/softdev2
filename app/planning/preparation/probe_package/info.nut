class P08PreparationInfo extends GSInfo {
    function GetAuthor() { return "Team-Project-SIET"; }
    function GetName() { return "P08Preparation"; }
    function GetDescription() { return "Read-only P08 extraction of pinned preparation worlds"; }
    function GetVersion() { return 1; }
    function GetDate() { return "2026-10-04"; }
    function CreateInstance() { return "P08Preparation"; }
    function GetShortName() { return "P08P"; }
    function GetAPIVersion() { return "13"; }
}
RegisterGS(P08PreparationInfo());
