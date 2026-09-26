"""Validated, immutable OpenTTD 13.4 telemetry values."""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

CompanyID = Annotated[int, Field(strict=True, ge=0, le=14)]
SignedMoney = Annotated[int, Field(strict=True, ge=-(2**63), le=2**63 - 1)]
Unsigned16 = Annotated[int, Field(strict=True, ge=0, le=65535)]
Unsigned8 = Annotated[int, Field(strict=True, ge=0, le=255)]
Unsigned32 = Annotated[int, Field(strict=True, ge=0, le=2**32 - 1)]

FIRST_SUPPORTED_DAY = 366  # Year zero is leap; year 1 begins at day 366.
LAST_SUPPORTED_DAY = date.max.toordinal() + 365


def supported_game_day_to_date(game_day: int) -> date:
    """Convert OpenTTD's year-zero day counter to supported ISO years 1–9999."""
    if type(game_day) is not int or not FIRST_SUPPORTED_DAY <= game_day <= LAST_SUPPORTED_DAY:
        raise ValueError("game day is outside the supported years 1–9999")
    return date.fromordinal(game_day - 365)


class GameDateObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    game_day: Unsigned32

    @field_validator("game_day")
    @classmethod
    def require_supported_day(cls, value: int) -> int:
        supported_game_day_to_date(value)
        return value

    @property
    def calendar_date(self) -> date:
        return supported_game_day_to_date(self.game_day)


class CompanyInfoObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: CompanyID
    name: str
    manager: str
    colour: Unsigned8
    password_protected: StrictBool
    inaugurated_year: Unsigned32
    is_ai: StrictBool
    bankruptcy_quarters: Unsigned8
    share_owners: tuple[Unsigned8, Unsigned8, Unsigned8, Unsigned8]


class PrimaryVehicleCounts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    train: Unsigned16
    lorry: Unsigned16
    bus: Unsigned16
    plane: Unsigned16
    ship: Unsigned16


class StationFacilityCounts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    train_station: Unsigned16
    lorry_station: Unsigned16
    bus_stop: Unsigned16
    airport_or_heliport: Unsigned16
    harbour: Unsigned16


class CompanyStatsObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: CompanyID
    primary_vehicles: PrimaryVehicleCounts
    station_facilities: StationFacilityCounts


class CompletedQuarter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    history_offset: Annotated[int, Field(strict=True, ge=1, le=2)]
    company_value_gbp: SignedMoney
    performance_score: Unsigned16
    delivered_cargo_capped: Unsigned16

    @property
    def cargo_may_be_saturated(self) -> bool:
        return self.delivered_cargo_capped == 65535


class CompanyEconomyObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: CompanyID
    cash_balance_gbp: SignedMoney
    loan_balance_gbp: SignedMoney
    admin_year_to_date_net_income_gbp: SignedMoney
    current_quarter_delivered_cargo_capped: Unsigned16
    completed_quarters: tuple[CompletedQuarter, CompletedQuarter]

    @model_validator(mode="after")
    def require_history_order(self) -> CompanyEconomyObservation:
        if tuple(q.history_offset for q in self.completed_quarters) != (1, 2):
            raise ValueError("completed quarters must have history offsets 1 and 2")
        return self

    @property
    def current_quarter_cargo_may_be_saturated(self) -> bool:
        return self.current_quarter_delivered_cargo_capped == 65535


class ObservationSource(StrEnum):
    OPENTTD_ADMIN = "openttd_admin"
    LIVE_RUNTIME = "live_runtime"


class ObservationKind(StrEnum):
    DATE = "date"
    COMPANY_INFO = "company_info"
    COMPANY_ECONOMY = "company_economy"
    COMPANY_STATS = "company_stats"
    DIAGNOSTIC = "diagnostic"


class DateQuality(StrEnum):
    PACKET_DATE = "packet_date"
    PRECEDING_DATE = "preceding_date"
    UNKNOWN = "unknown"


class DiagnosticCode(StrEnum):
    CONNECTION_OPENED = "connection_opened"
    MISSING_DATE = "missing_date_context"
    PERSISTENCE_RETRY = "persistence_retry"
    UNKNOWN_PACKET = "unknown_packet"
    UNSUPPORTED_DATA = "unsupported_data"
    COMPANY_NEW = "company_new"
    COMPANY_UPDATE = "company_update"
    COMPANY_REMOVE = "company_remove"
    WORLD_RESET = "world_reset"
    SERVER_SHUTDOWN = "server_shutdown"
    CONNECTION_GAP = "connection_gap"
    PROTOCOL_ERROR = "protocol_error"
    PERSISTENCE_FAILURE = "persistence_failure"


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticSummary(StrEnum):
    """Allowlisted context only; runtime exception text must never enter telemetry."""

    CONNECTION_OPENED = "observer transport established"
    MISSING_DATE = "no preceding Date on this connection"
    PERSISTENCE_RETRY = "retrying identical telemetry batch"
    UNKNOWN_PACKET_IGNORED = "unknown packet ignored"
    UNSUPPORTED_DATA = "unsupported protocol data"
    COMPANY_CREATED = "company created"
    COMPANY_CHANGED = "company changed"
    COMPANY_REMOVED = "company removed"
    WORLD_RESET = "world reset"
    SERVER_SHUTDOWN = "server shutdown"
    CONNECTION_GAP = "observer connection gap"
    PROTOCOL_ERROR = "Admin protocol error"
    PERSISTENCE_FAILURE = "telemetry persistence failure"


class TelemetryDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: DiagnosticCode
    severity: DiagnosticSeverity
    connection_epoch: Annotated[int, Field(strict=True, ge=0)]
    occurred_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    last_known_day: Unsigned32 | None = None
    summary: DiagnosticSummary | None = None

    @model_validator(mode="after")
    def validate_context(self) -> TelemetryDiagnostic:
        if self.occurred_at.utcoffset() != timedelta(0):
            raise ValueError("diagnostic time must be UTC")
        if self.ended_at is not None:
            if self.ended_at.utcoffset() != timedelta(0) or self.ended_at < self.occurred_at:
                raise ValueError("diagnostic end must be UTC and after start")
        if self.last_known_day is not None:
            supported_game_day_to_date(self.last_known_day)
        return self


ObservationPayload = (
    GameDateObservation
    | CompanyInfoObservation
    | CompanyEconomyObservation
    | CompanyStatsObservation
    | TelemetryDiagnostic
)


@dataclass(frozen=True)
class InferredEconomyPeriods:
    """Calendar labels from preceding Date only, not proof of history-slot validity."""

    admin_year_to_date: str
    current_quarter: str
    completed_quarters: tuple[str | None, str | None]
    inferred: bool = True


class TelemetryObservation(BaseModel):
    """A validated envelope; sequence and date context are supplied by T08."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_run_id: Annotated[int, Field(strict=True, gt=0)]
    sequence: Annotated[int, Field(strict=True, gt=0)]
    connection_epoch: Annotated[int, Field(strict=True, ge=0)]
    received_at: AwareDatetime
    schema_version: Annotated[int, Field(strict=True, gt=0)]
    source: ObservationSource
    protocol_version: Annotated[int, Field(strict=True, ge=0, le=255)] | None
    kind: ObservationKind
    company_id: CompanyID | None
    game_day: Unsigned32 | None
    date_context_sequence: Annotated[int, Field(strict=True, gt=0)] | None
    date_quality: DateQuality
    payload: ObservationPayload

    @property
    def inferred_economy_periods(self) -> InferredEconomyPeriods | None:
        if self.kind is not ObservationKind.COMPANY_ECONOMY or self.game_day is None:
            return None
        calendar = supported_game_day_to_date(self.game_day)
        index = (calendar.year - 1) * 4 + (calendar.month - 1) // 3

        def label(offset: int) -> str | None:
            previous = index - offset
            if previous < 0:
                return None  # Outside supported years; this is not an invalid-history flag.
            return f"{previous // 4 + 1:04d}-Q{previous % 4 + 1}"

        return InferredEconomyPeriods(
            admin_year_to_date=f"{calendar.year:04d}",
            current_quarter=f"{calendar.year:04d}-Q{(calendar.month - 1) // 3 + 1}",
            completed_quarters=(label(1), label(2)),
        )

    @model_validator(mode="after")
    def validate_semantics(self) -> TelemetryObservation:
        if self.received_at.utcoffset() != timedelta(0):
            raise ValueError("received_at must be UTC")
        if self.game_day is not None:
            supported_game_day_to_date(self.game_day)
        payload = self.payload
        if self.kind is ObservationKind.DIAGNOSTIC:
            if not isinstance(payload, TelemetryDiagnostic):
                raise ValueError("observation kind does not match typed payload")
            if payload.connection_epoch != self.connection_epoch:
                raise ValueError("diagnostic connection epoch differs from envelope")
        else:
            if self.source is not ObservationSource.OPENTTD_ADMIN:
                raise ValueError("measurements must come from the Admin source")
            if self.connection_epoch == 0 or self.protocol_version is None:
                raise ValueError("measurements require an authenticated connection")
            if self.kind is ObservationKind.DATE:
                if not isinstance(payload, GameDateObservation):
                    raise ValueError("observation kind does not match typed payload")
                if (
                    self.company_id is not None
                    or self.game_day != payload.game_day
                    or self.date_quality is not DateQuality.PACKET_DATE
                    or self.date_context_sequence is not None
                ):
                    raise ValueError("Date must carry its own game day and no company")
            else:
                company_types = (
                    (CompanyInfoObservation, ObservationKind.COMPANY_INFO),
                    (CompanyEconomyObservation, ObservationKind.COMPANY_ECONOMY),
                    (CompanyStatsObservation, ObservationKind.COMPANY_STATS),
                )
                for payload_type, expected_kind in company_types:
                    if isinstance(payload, payload_type) and self.kind is expected_kind:
                        if self.company_id != payload.company_id:
                            raise ValueError("company ID differs from typed payload")
                        break
                else:
                    raise ValueError("observation kind does not match typed payload")
        if self.date_quality is DateQuality.UNKNOWN:
            if self.game_day is not None or self.date_context_sequence is not None:
                raise ValueError("unknown date quality cannot claim date context")
        elif self.date_quality is DateQuality.PRECEDING_DATE:
            if (
                self.game_day is None
                or self.date_context_sequence is None
                or self.date_context_sequence >= self.sequence
            ):
                raise ValueError("preceding Date context must precede observation")
        elif self.kind is not ObservationKind.DATE:
            raise ValueError("only Date packets have packet-date quality")
        return self


class MetricSource(StrEnum):
    OPENTTD_ADMIN = "openttd_admin"
    FINAL_SAVEGAME = "final_savegame"


class MeasurementKind(StrEnum):
    BALANCE = "balance"
    NET_INCOME = "net_income"
    INCOME = "income"
    EXPENSE = "expense"
    CARGO_QUANTITY = "cargo_quantity"
    COMPANY_VALUE = "company_value"
    PERFORMANCE_SCORE = "performance_score"
    VEHICLE_COUNT = "vehicle_count"
    STATION_FACILITY_COUNT = "station_facility_count"


class MeasurementPeriod(StrEnum):
    CURRENT = "current"
    CALENDAR_YEAR_TO_DATE = "calendar_year_to_date"
    CURRENT_QUARTER_TO_DATE = "current_quarter_to_date"
    COMPLETED_QUARTER = "completed_quarter"


class SignConvention(StrEnum):
    SOURCE_SIGNED = "source_signed"
    NONNEGATIVE = "nonnegative"
    SATURATING_UINT16 = "saturating_uint16"


class MetricSemantics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    source: MetricSource
    measurement_kind: MeasurementKind
    period: MeasurementPeriod
    sign_convention: SignConvention
    unit: str
    meaning: str
    saturates_at: int | None = None


_METRIC_SEMANTICS: tuple[MetricSemantics, ...] = (
    MetricSemantics(
        name="cash_balance_gbp",
        source=MetricSource.OPENTTD_ADMIN,
        measurement_kind=MeasurementKind.BALANCE,
        period=MeasurementPeriod.CURRENT,
        sign_convention=SignConvention.SOURCE_SIGNED,
        unit="GBP",
        meaning="Current company cash balance",
    ),
    MetricSemantics(
        name="loan_balance_gbp",
        source=MetricSource.OPENTTD_ADMIN,
        measurement_kind=MeasurementKind.BALANCE,
        period=MeasurementPeriod.CURRENT,
        sign_convention=SignConvention.SOURCE_SIGNED,
        unit="GBP",
        meaning="Current company loan balance",
    ),
    MetricSemantics(
        name="admin_year_to_date_net_income_gbp",
        source=MetricSource.OPENTTD_ADMIN,
        measurement_kind=MeasurementKind.NET_INCOME,
        period=MeasurementPeriod.CALENDAR_YEAR_TO_DATE,
        sign_convention=SignConvention.SOURCE_SIGNED,
        unit="GBP",
        meaning="Negative sum of yearly expenses, including construction and purchases",
    ),
    MetricSemantics(
        name="current_quarter_delivered_cargo_capped",
        source=MetricSource.OPENTTD_ADMIN,
        measurement_kind=MeasurementKind.CARGO_QUANTITY,
        period=MeasurementPeriod.CURRENT_QUARTER_TO_DATE,
        sign_convention=SignConvention.SATURATING_UINT16,
        unit="cargo_units",
        meaning="Current-quarter delivered cargo, capped at 65535",
        saturates_at=65535,
    ),
    MetricSemantics(
        name="company_value_gbp",
        source=MetricSource.OPENTTD_ADMIN,
        measurement_kind=MeasurementKind.COMPANY_VALUE,
        period=MeasurementPeriod.COMPLETED_QUARTER,
        sign_convention=SignConvention.SOURCE_SIGNED,
        unit="GBP",
        meaning="Company valuation at completed-quarter snapshot",
    ),
    MetricSemantics(
        name="performance_score",
        source=MetricSource.OPENTTD_ADMIN,
        measurement_kind=MeasurementKind.PERFORMANCE_SCORE,
        period=MeasurementPeriod.COMPLETED_QUARTER,
        sign_convention=SignConvention.NONNEGATIVE,
        unit="score",
        meaning="Completed-quarter performance score",
    ),
    MetricSemantics(
        name="delivered_cargo_capped",
        source=MetricSource.OPENTTD_ADMIN,
        measurement_kind=MeasurementKind.CARGO_QUANTITY,
        period=MeasurementPeriod.COMPLETED_QUARTER,
        sign_convention=SignConvention.SATURATING_UINT16,
        unit="cargo_units",
        meaning="Completed-quarter delivered cargo, capped at 65535",
        saturates_at=65535,
    ),
    MetricSemantics(
        name="primary_vehicle_count",
        source=MetricSource.OPENTTD_ADMIN,
        measurement_kind=MeasurementKind.VEHICLE_COUNT,
        period=MeasurementPeriod.CURRENT,
        sign_convention=SignConvention.NONNEGATIVE,
        unit="count",
        meaning="Primary vehicles by type; excludes wagons and capacity",
    ),
    MetricSemantics(
        name="station_facility_count",
        source=MetricSource.OPENTTD_ADMIN,
        measurement_kind=MeasurementKind.STATION_FACILITY_COUNT,
        period=MeasurementPeriod.CURRENT,
        sign_convention=SignConvention.NONNEGATIVE,
        unit="count",
        meaning="Facilities by type; one station can count in multiple categories",
    ),
    MetricSemantics(
        name="company_money",
        source=MetricSource.FINAL_SAVEGAME,
        measurement_kind=MeasurementKind.BALANCE,
        period=MeasurementPeriod.CURRENT,
        sign_convention=SignConvention.SOURCE_SIGNED,
        unit="GBP",
        meaning="Company cash balance in the final save",
    ),
    MetricSemantics(
        name="company_loan",
        source=MetricSource.FINAL_SAVEGAME,
        measurement_kind=MeasurementKind.BALANCE,
        period=MeasurementPeriod.CURRENT,
        sign_convention=SignConvention.SOURCE_SIGNED,
        unit="GBP",
        meaning="Company loan balance in the final save",
    ),
    MetricSemantics(
        name="current_period_income",
        source=MetricSource.FINAL_SAVEGAME,
        measurement_kind=MeasurementKind.INCOME,
        period=MeasurementPeriod.CURRENT_QUARTER_TO_DATE,
        sign_convention=SignConvention.SOURCE_SIGNED,
        unit="GBP",
        meaning="Source-signed current-quarter income in the final save",
    ),
    MetricSemantics(
        name="current_period_expenses",
        source=MetricSource.FINAL_SAVEGAME,
        measurement_kind=MeasurementKind.EXPENSE,
        period=MeasurementPeriod.CURRENT_QUARTER_TO_DATE,
        sign_convention=SignConvention.SOURCE_SIGNED,
        unit="GBP",
        meaning="Source-signed current-quarter expenses in the final save",
    ),
    MetricSemantics(
        name="current_period_cargo_delivered",
        source=MetricSource.FINAL_SAVEGAME,
        measurement_kind=MeasurementKind.CARGO_QUANTITY,
        period=MeasurementPeriod.CURRENT_QUARTER_TO_DATE,
        sign_convention=SignConvention.NONNEGATIVE,
        unit="cargo_units",
        meaning="Current-quarter delivered cargo from final-save categories",
    ),
)


def metric_semantics(source: MetricSource, name: str) -> MetricSemantics:
    """Return the pinned meaning of a metric without changing final metric IDs."""
    for metadata in _METRIC_SEMANTICS:
        if metadata.source is source and metadata.name == name:
            return metadata
    raise KeyError((source, name))
