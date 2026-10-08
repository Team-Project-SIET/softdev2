# OpenTTD 15.3 complete raw production — economy-window authority

This is current preparation authority, not a rewritten historical audit. Exact
`15.3` source files were downloaded and hashed in
`tests/reference/economy_clock_15_3/manifest.json`. No OpenTTD process or Admin
connection was used to inspect them. The production V1 response and GameScript
handler remain unchanged.

## V1 fields and binding

| Transported field | C++ Script API | Generated GameScript binding | Type / domain | Meaning |
| --- | --- | --- | --- | --- |
| economy_date_before | ScriptDate::GetCurrentDate | GSDate.GetCurrentDate | C++ ScriptDate::Date enum; exported Squirrel integer; underlying engine signed int32 day ordinal | Current economy date immediately before reading the three historical metrics |
| economy_date_after | ScriptDate::GetCurrentDate | GSDate.GetCurrentDate | Same; V1 accepts integers 0 through 2147483647 | Current economy date immediately after those reads |

[script_date.cpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_date.cpp)
returns `TimerGameEconomy::date.base()` cast to ScriptDate::Date. The
[declaration](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_date.hpp)
exposes the enum and static method. The tagged
[API build](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/CMakeLists.txt)
selects the game/GS export; the
[generator](https://github.com/OpenTTD/OpenTTD/blob/15.3/cmake/scripts/SquirrelExport.cmake)
replaces the Script class prefix with GS and registers static methods with their
original names. No inferred binding or new GameScript date API is introduced.

The fields are neither calendar dates in general, month indexes, nor start/end
boundaries of the last production month. They bracket capture of historical
counters using **current-state** economy-clock metadata. Both can legitimately be
equal when no economy day advances between calls. V1 requires before <= after;
the combined owner additionally requires both to belong to its initial month.
No equality to Attempt 2's observed date is required.

The [engine date type](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/timer/timer_game_common.h)
is signed int32 with a zero-based epoch at year zero, including native leap-year
zero. `IsValidDate` accepts nonnegative dates; conversion APIs reject negative
input with DATE_INVALID. GetCurrentDate itself has no separate unavailable
result or industry/cargo error branch: it reads the initialized global economy
clock. The bridge executes only in the live GameScript; V1 rejects negative,
non-integer, reversed or out-of-range brackets.

## Frozen clock and initial month without another request

The proof explicitly freezes `[economy] timekeeping_units = 0` (TKU_CALENDAR),
a newly generated world (`-g` with no save argument), and starting_year = 1950.
It authorizes no save/load, RCON clock changes or clock-setting commands.

[Economy conversion](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/timer/timer_game_economy.cpp)
delegates to the common Gregorian conversion in calendar mode. Wallclock mode
instead has twelve thirty-day economy months, and is excluded by this proof.
The exact setting enum/range is retained in settings_type.h and
[economy_settings.ini](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/table/settings/economy_settings.ini).

[World generation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/genworld.cpp)
calls InitializeGame with reset_date=true. Its
[initialization](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/misc.cpp)
sets calendar to January 1 of the starting year, then sets economy to the same
ordinal in calendar mode. This is distinct from wallclock's year-one economy
initialization. The
[encrypted WELCOME](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/network_admin.cpp)
contains the world's configured calendar **start date**, not its current date.
Under this restricted generated profile it therefore identifies the initial
calendar/economy month without another application request.

The Python owner uses the source-equivalent DateAtStartOfYear, leap rule and
month lengths from
[timer_game_common.h](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/timer/timer_game_common.h)
and [timer_game_common.cpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/timer/timer_game_common.cpp).
It does not use Python datetime, wall-clock time, historical response dates, or
an invented native getter. This yields the same month/boundary identity as
ScriptDate::GetYear/GetMonth/GetDate for the frozen calendar clock, without
calling those APIs. The initial window has an inclusive start and exclusive
next-month start. The owner records this policy in economy-authority.json.

This policy is deliberately restrictive: WELCOME is not treated as a current
clock reading. All Phase-E response brackets must still fall in the identified
initial month. If structural collection or production crosses its boundary, the
combined observation fails; no polling, warm-up, fallback window or rollover
wait is performed. The native values need not equal the start date. Equal
capture dates later in that month remain valid. Zero targets require no
production query and retain the initial unqualified window identity.

## Fresh worlds, persistence and qualification

The unchanged production APIs read native previous-month counters. A new world
may seed them before any elapsed economy month. Date bracketing does not certify
that the counters represent a fully elapsed historical window. The existing
[production audit](industry-production-native-api-audit.md) remains authority for
that ambiguity and for station-allocation/percentage semantics.

Calendar and economy date/fraction are separate saved fields in
[misc_sl.cpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/saveload/misc_sl.cpp).
A loaded save can therefore require a different clock/provenance policy; it
cannot use this new-world initialization argument. No load is authorized here.
There is no session history in GameScript and no qualification decision there.

Raw complete coverage means exactly one validated record per same-run produced
pair. It does not mean valid elapsed-month planning history. Qualification
remains Python-side with **zero observed rollovers** and
**qualified_for_planning=false**. Later qualification needs two separately
observed adjacent economy-month rollovers under the existing model. No change
in values, positive production, equal brackets or complete transport coverage
can substitute for that future requirement. No P08 adaptation is included.
