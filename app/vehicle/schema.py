from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.vehicle.model import VehicleStatus


class VehicleBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    width: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    length: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    height: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    max_weight: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    status: VehicleStatus = VehicleStatus.AVAILABLE


class VehicleCreate(VehicleBase):
    pass


class VehicleRead(VehicleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
