"""Pinned 15.3 economy clock, restricted to the generated calendar-time profile.

WELCOME carries the world's calendar START date, not its current economy date.
Under the frozen new-world calendar profile it identifies the initial month;
every production bracket must still validate inside that month. No clock polling,
new GameScript API calls, calendar guess, or history qualification is performed.
"""

import hashlib
import json

from app.simulation.openttd.production_observation import EconomyMonth


def _year_start(year: int) -> int:
    # TimerGame<T>::DateAtStartOfYear, including the native leap year zero.
    leaps = 0 if year == 0 else (year - 1) // 4 - (year - 1) // 100 + (year - 1) // 400 + 1
    return 365 * year + leaps


def calendar_economy_month(date: int) -> EconomyMonth:
    """Source-equivalent calendar clock conversion; accepts a native day ordinal."""
    if type(date) is not int or not 0 <= date < _year_start(5000001):
        raise ValueError("Invalid/unavailable native economy date")
    low, high = 0, 5000001
    while high - low > 1:
        middle = (low + high) // 2
        if _year_start(middle) <= date:
            low = middle
        else:
            high = middle
    leap = low % 4 == 0 and (low % 100 != 0 or low % 400 == 0)
    lengths = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    start = _year_start(low)
    for month, length in enumerate(lengths, 1):
        end = start + length
        if date < end:
            return EconomyMonth(low, month, start, end)
        start = end
    raise ValueError("Native month conversion failed")


def initial_month(welcome) -> EconomyMonth:
    month = calendar_economy_month(welcome.start_day)
    if (month.year, month.month, month.start_date) != (1950, 1, welcome.start_day):
        raise ValueError("Frozen generated-world initial month identity required")
    return month


def economy_clock_contract() -> dict:
    return dict(
        source_version="15.3",
        cpp_api="ScriptDate::GetCurrentDate",
        gamescript_binding="GSDate.GetCurrentDate",
        fields=["economy_date_before", "economy_date_after"],
        native_storage="TimerGameEconomy::Date, signed int32_t",
        script_return="ScriptDate::Date enum, exported as GameScript integer",
        unit="economy days, zero-based ordinal from year 0",
        role="current-state read bracket around last-month metrics, not historical boundaries",
        valid_v1_range=[0, 2147483647],
        equal_brackets_valid=True,
        ordering="before <= after; both inside the initial economy month",
        timekeeping_units=0,
        timekeeping_authority="TKU_CALENDAR; economy/calendar identical Gregorian conversion",
        starting_year=1950,
        initial_month_authority="native WELCOME start_day + pinned new-world calendar conversion",
        welcome_is_current_date=False,
        load_save_authorized=False,
        seeded_history_allowed=True,
        rollovers_observed=0,
        qualified_for_planning=False,
        additional_application_requests=0,
        additional_gamescript_calls=0,
    )


def economy_authority() -> dict:
    from .harness import PROJECT, sha256

    path = PROJECT / "tests/reference/economy_clock_15_3/manifest.json"
    manifest = json.loads(path.read_text())
    if manifest["version"] != "15.3":
        raise ValueError("Exact native economy source version required")
    files = {str(path): sha256(path)}
    for name, entry in manifest["files"].items():
        source = PROJECT / name
        if sha256(source) != entry["sha256"]:
            raise ValueError("Pinned native economy source changed")
        files[str(source)] = entry["sha256"]
    value: dict = dict(contract=economy_clock_contract(), files=files)
    value["sha256"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value
