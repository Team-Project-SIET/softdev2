from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Coordinates(BaseModel):
    model_config = ConfigDict(frozen=True)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RoutingShipment(BaseModel):
    model_config = ConfigDict(frozen=True)

    shipment_id: int = Field(gt=0)
    customer_id: int = Field(gt=0)
    location: Coordinates
    demand_kg: Decimal = Field(ge=0, decimal_places=4)


class RoutingVehicle(BaseModel):
    model_config = ConfigDict(frozen=True)

    vehicle_id: int = Field(gt=0)
    capacity_kg: Decimal = Field(gt=0, decimal_places=4)


class RoutingProblem(BaseModel):
    model_config = ConfigDict(frozen=True)

    depot: Coordinates
    shipments: list[RoutingShipment] = Field(min_length=1)
    vehicles: list[RoutingVehicle] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def ids_are_unique(self) -> RoutingProblem:
        shipment_ids = [shipment.shipment_id for shipment in self.shipments]
        vehicle_ids = [vehicle.vehicle_id for vehicle in self.vehicles]
        if len(shipment_ids) != len(set(shipment_ids)):
            raise ValueError("shipment IDs must be unique")
        if len(vehicle_ids) != len(set(vehicle_ids)):
            raise ValueError("vehicle IDs must be unique")
        return self


class RouteStopPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    shipment_id: int | None = None
    customer_id: int | None = None
    stop_order: int = Field(ge=0)
    distance_from_previous: Decimal = Field(ge=0, decimal_places=3, description="Kilometers")
    is_depot: bool = False

    @model_validator(mode="after")
    def depot_or_delivery_fields_are_consistent(self) -> RouteStopPlan:
        if self.is_depot and (self.shipment_id is not None or self.customer_id is not None):
            raise ValueError("depot stops cannot reference a shipment or customer")
        if not self.is_depot and (self.shipment_id is None or self.customer_id is None):
            raise ValueError("delivery stops require shipment_id and customer_id")
        return self


class VehicleRoutePlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    vehicle_id: int
    stops: list[RouteStopPlan] = Field(min_length=2)
    total_distance: Decimal = Field(ge=0, decimal_places=3, description="Kilometers")
    total_weight: Decimal = Field(ge=0, description="Kilograms")


class RoutingPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    depot: Coordinates
    routes: list[VehicleRoutePlan] = Field(min_length=1)
    total_distance: Decimal = Field(ge=0, decimal_places=3, description="Kilometers")
    # The inputs used for the preview are checked again in the save transaction.
    source_problem: RoutingProblem | None = None


class ShipmentCandidate(BaseModel):
    id: int
    customer_name: str
    delivery_date: date
    demand_kg: Decimal


class VehicleCandidate(BaseModel):
    id: int
    name: str
    capacity_kg: Decimal


class RoutingCandidates(BaseModel):
    shipments: list[ShipmentCandidate]
    vehicles: list[VehicleCandidate]


class SavedRoutingPlan(BaseModel):
    route_ids: list[int]
    shipment_count: int
