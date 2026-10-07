/* Controlled stand-ins for source-verified15.3 signatures, not a native binding proof. */
::production_metrics <- [120, 7, 5];
::production_date <- 60;
class GSIndustry {
    static function IsValidIndustry(id) { return id == 3; }
    static function GetLastMonthProduction(id, cargo) { return (id == 3 && cargo == 1) ? ::production_metrics[0] : -1; }
    static function GetLastMonthTransported(id, cargo) { return (id == 3 && cargo == 1) ? ::production_metrics[1] : -1; }
    static function GetLastMonthTransportedPercentage(id, cargo) { return (id == 3 && cargo == 1) ? ::production_metrics[2] : -1; }
}
class GSCargo { static function IsValidCargo(id) { return id >= 0 && id < 64; } }
class GSDate { static function GetCurrentDate() { return ::production_date; } }
