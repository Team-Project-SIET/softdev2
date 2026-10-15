/* Controlled list/API seam; source names and byte semantics pinned to 15.3.
   This exercises handler code in SQVM, not a real OpenTTD API binding. */
::active_ids <- [63, 0, 9];
::labels <- {}; ::effects <- {}; ::class_masks <- {};
for (local i=0; i<64; i++) { ::labels[i] <- "CARG"; ::effects[i] <- i % 6; ::class_masks[i] <- 1 << (i % 15); }
::labels[0] = "PASS"; ::labels[1] = "MAIL"; ::labels[63] = "OIL_";
class GSList {
    static SORT_BY_ITEM = 1; static SORT_ASCENDING = true;
    ids = null; position = 0;
    function Sort(by, ascending) { if (by != GSList.SORT_BY_ITEM || ascending != GSList.SORT_ASCENDING) throw "bad sort"; this.ids.sort(); }
    function Begin() { this.position=0; return this.ids.len() ? this.ids[0] : 0; }
    function IsEnd() { return this.position >= this.ids.len(); }
    function Next() { this.position++; return this.IsEnd() ? 0 : this.ids[this.position]; }
}
class GSCargoList extends GSList { constructor() { this.ids = clone ::active_ids; } }
class GSCargo {
    static CC_PASSENGERS = 1;
    static CC_MAIL = 2;
    static CC_EXPRESS = 4;
    static CC_ARMOURED = 8;
    static CC_BULK = 16;
    static CC_PIECE_GOODS = 32;
    static CC_LIQUID = 64;
    static CC_REFRIGERATED = 128;
    static CC_HAZARDOUS = 256;
    static CC_COVERED = 512;
    static CC_OVERSIZED = 1024;
    static CC_POWDERIZED = 2048;
    static CC_NON_POURABLE = 4096;
    static CC_POTABLE = 8192;
    static CC_NON_POTABLE = 16384;
    static function IsValidCargo(id) { return id >= 0 && id < 64 && ::active_ids.find(id) != null; }
    static function GetCargoLabel(id) { return ::labels[id]; }
    static function IsFreight(id) { return id % 2 != 0; }
    static function GetTownEffect(id) { return ::effects[id]; }
    static function HasCargoClass(id, kind) { return (::class_masks[id] & kind) != 0; }
}
