from pydantic import BaseModel, ConfigDict, Field


class DriverBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=1, max_length=32)
    line_user_id: str | None = Field(default=None, min_length=1, max_length=64)
    vehicle_id: int | None = Field(default=None, gt=0)


class DriverCreate(DriverBase):
    pass


class DriverRead(DriverBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
