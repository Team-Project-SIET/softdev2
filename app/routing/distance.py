from math import asin, cos, radians, sin, sqrt
from typing import Protocol

from app.routing.schemas import Coordinates


class DistanceProvider(Protocol):
    """Distance source returning kilometers between two coordinates."""

    def distance(self, origin: Coordinates, destination: Coordinates) -> float: ...


class HaversineDistanceProvider:
    """Great-circle distance provider using a mean Earth radius of 6,371.0088 km."""

    earth_radius_km = 6371.0088

    def distance(self, origin: Coordinates, destination: Coordinates) -> float:
        latitude_delta = radians(destination.latitude - origin.latitude)
        longitude_delta = radians(destination.longitude - origin.longitude)
        origin_latitude = radians(origin.latitude)
        destination_latitude = radians(destination.latitude)

        haversine = sin(latitude_delta / 2) ** 2 + (
            cos(origin_latitude) * cos(destination_latitude) * sin(longitude_delta / 2) ** 2
        )
        return self.earth_radius_km * 2 * asin(sqrt(min(1.0, haversine)))
