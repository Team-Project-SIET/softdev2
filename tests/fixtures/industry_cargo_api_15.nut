/* Controlled fake slots; names/constructors and sorting contract verified from 15.3 source. */
::produced_ids <- [63, 2, 17];
::accepted_ids <- [8, 0];
::valid_industries <- [3, 17];
class GSIndustry {
    static function IsValidIndustry(id) { return ::valid_industries.find(id) != null; }
}
class GSCargo { static function IsValidCargo(id) { return id >= 0 && id < 64; } }
class GSList {
    static SORT_BY_ITEM = 1;
    static SORT_ASCENDING = true;
    ids = null;
    position = 0;
    function Sort(by, ascending) {
        if (by != GSList.SORT_BY_ITEM || ascending != GSList.SORT_ASCENDING) throw "bad sort";
        this.ids.sort();
    }
    function Begin() { this.position = 0; return this.ids.len() ? this.ids[0] : 0; }
    function Next() { this.position++; return this.IsEnd() ? 0 : this.ids[this.position]; }
    function IsEnd() { return this.position >= this.ids.len(); }
}
class GSCargoList_IndustryProducing extends GSList {
    constructor(id) { if (!GSIndustry.IsValidIndustry(id)) throw "invalid industry"; this.ids = clone ::produced_ids; }
}
class GSCargoList_IndustryAccepting extends GSList {
    constructor(id) { if (!GSIndustry.IsValidIndustry(id)) throw "invalid industry"; this.ids = clone ::accepted_ids; }
}
