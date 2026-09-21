from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Orientation(StrEnum):
    """Original package dimensions assigned to the vehicle's x, y, z axes."""

    WLH = "WLH"
    WHL = "WHL"
    LWH = "LWH"
    LHW = "LHW"
    HWL = "HWL"
    HLW = "HLW"


class LoadingStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INFEASIBLE = "infeasible"


class PackingVehicle(BaseModel):
    model_config = ConfigDict(frozen=True)

    vehicle_id: int = Field(gt=0)
    width: Decimal = Field(gt=0, description="Centimeters, x axis")
    length: Decimal = Field(gt=0, description="Centimeters, y axis from rear door inward")
    height: Decimal = Field(gt=0, description="Centimeters, z axis from floor upward")
    max_weight: Decimal = Field(gt=0, description="Kilograms")

    @property
    def volume(self) -> Decimal:
        return self.width * self.length * self.height


class PackingPackage(BaseModel):
    model_config = ConfigDict(frozen=True)

    package_id: int = Field(gt=0)
    shipment_id: int = Field(gt=0)
    width: Decimal = Field(gt=0)
    length: Decimal = Field(gt=0)
    height: Decimal = Field(gt=0)
    weight: Decimal = Field(ge=0)
    stackable: bool = True

    @property
    def volume(self) -> Decimal:
        return self.width * self.length * self.height

    def dimensions(self, orientation: Orientation) -> tuple[Decimal, Decimal, Decimal]:
        sizes = {"W": self.width, "L": self.length, "H": self.height}
        x, y, z = orientation.value
        return sizes[x], sizes[y], sizes[z]


class DeliveryStop(BaseModel):
    model_config = ConfigDict(frozen=True)

    shipment_id: int = Field(gt=0)
    stop_order: int = Field(ge=0)


class PackingProblem(BaseModel):
    model_config = ConfigDict(frozen=True)

    vehicle: PackingVehicle
    packages: list[PackingPackage]
    delivery_sequence: list[DeliveryStop]

    @model_validator(mode="after")
    def validate_sequence(self) -> PackingProblem:
        package_ids = [package.package_id for package in self.packages]
        shipment_ids = [stop.shipment_id for stop in self.delivery_sequence]
        stop_orders = [stop.stop_order for stop in self.delivery_sequence]
        if len(package_ids) != len(set(package_ids)):
            raise ValueError("package IDs must be unique")
        if len(shipment_ids) != len(set(shipment_ids)):
            raise ValueError("each shipment must occur once in the delivery sequence")
        if len(stop_orders) != len(set(stop_orders)):
            raise ValueError("stop orders must be unique")
        if any(package.shipment_id not in shipment_ids for package in self.packages):
            raise ValueError("every package must belong to a delivery stop")
        return self


class Placement(BaseModel):
    model_config = ConfigDict(frozen=True)

    package_id: int
    vehicle_id: int
    x: Decimal = Field(ge=0)
    y: Decimal = Field(ge=0)
    z: Decimal = Field(ge=0)
    orientation: Orientation
    width: Decimal = Field(gt=0, description="Oriented x extent in cm")
    length: Decimal = Field(gt=0, description="Oriented y extent in cm")
    height: Decimal = Field(gt=0, description="Oriented z extent in cm")
    loading_order: int = Field(ge=1)
    unloading_order: int = Field(ge=1)
    stop_order: int = Field(ge=0)


class UnplacedPackage(BaseModel):
    package_id: int
    stop_order: int
    reason: str


class PackingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    vehicle_id: int
    placements: list[Placement]
    unplaced_packages: list[UnplacedPackage]
    total_package_volume: Decimal = Field(ge=0, description="All requested packages, cm³")
    used_cargo_volume: Decimal = Field(
        ge=0, description="Placed package volume, cm³; excludes gaps"
    )
    cargo_volume: Decimal = Field(gt=0, description="Vehicle capacity, cm³")
    volume_utilization_percentage: Decimal = Field(ge=0, le=100)
    total_loaded_weight: Decimal = Field(ge=0, description="Kilograms")
    payload_utilization_percentage: Decimal = Field(ge=0, le=100)
    status: LoadingStatus


class LoadingPlanDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    route_id: int
    problem: PackingProblem
    result: PackingResult


class SavedRouteCandidate(BaseModel):
    route_id: int
    vehicle_id: int
    vehicle_name: str
    stop_count: int
    package_count: int


class SavedLoadingPlan(BaseModel):
    loading_plan_id: int
    route_id: int
    placement_count: int
    status: LoadingStatus
