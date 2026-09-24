"""Import every ORM model into the shared declarative registry.

Import this module at application ORM boundaries before SQLAlchemy configures
mappers.  Model modules use string-resolved annotations to avoid importing one
another at runtime.
"""

from app.customer.model import Customer
from app.driver.model import Driver
from app.experiments.model import (
    ExperimentMetricRecord,
    ExperimentRunRecord,
    ExperimentScenario,
    PlanningStrategyRecord,
    SimulationRunRecord,
)
from app.packing.model import LoadingPlan, PackagePlacement
from app.routing.model import Route, RouteStop
from app.shipment.model import Package, Shipment
from app.vehicle.model import Vehicle

__all__ = [
    "Customer",
    "Driver",
    "ExperimentMetricRecord",
    "ExperimentRunRecord",
    "ExperimentScenario",
    "LoadingPlan",
    "Package",
    "PackagePlacement",
    "PlanningStrategyRecord",
    "Route",
    "RouteStop",
    "Shipment",
    "SimulationRunRecord",
    "Vehicle",
]
