/* Fake industry source, deliberately unordered before documented explicit Sort. */
::industry_ids <- [9, 2, 7, 0, 5, 3, 8];
::invalid_ids <- [];
::location_reads <- 0;
::type_reads <- 0;
class GSList { static SORT_BY_ITEM = 1; static SORT_ASCENDING = true; }
class GSIndustryList {
    ids = null;
    position = 0;
    constructor() { this.ids = clone ::industry_ids; }
    function Sort(by, ascending) {
        if (by != GSList.SORT_BY_ITEM || ascending != GSList.SORT_ASCENDING) throw "bad sort";
        this.ids.sort();
    }
    function Begin() { this.position = 0; return this.ids.len() ? this.ids[0] : 0; }
    function Next() { this.position++; return this.IsEnd() ? 0 : this.ids[this.position]; }
    function IsEnd() { return this.position >= this.ids.len(); }
}
class GSIndustry {
    static function IsValidIndustry(id) { return ::invalid_ids.find(id) == null; }
    static function GetLocation(id) { ::location_reads++; return 64 + id; }
    static function GetIndustryType(id) { ::type_reads++; return 12; }
}
class GSMap {
    static function GetMapSizeX() { return 64; }
    static function GetMapSizeY() { return 64; }
    static function IsValidTile(tile) { return tile >= 0 && tile < 4096; }
    static function GetTileX(tile) { return tile % 64; }
    static function GetTileY(tile) { return tile / 64; }
}
