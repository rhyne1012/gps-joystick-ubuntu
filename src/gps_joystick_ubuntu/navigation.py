"""Geodesic navigation math, joystick input, and motion simulation engine."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

EARTH_RADIUS_M = 6_371_008.8
MotionState = Literal["awaiting_direction", "moving", "paused"]


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """Geographic coordinate in WGS-84 decimal degrees."""

    latitude: float
    longitude: float

    def is_valid(self) -> bool:
        return (
            math.isfinite(self.latitude)
            and math.isfinite(self.longitude)
            and -90.0 <= self.latitude <= 90.0
            and -180.0 <= self.longitude <= 180.0
        )

    def moved(self, meters: float, bearing_deg: float) -> GeoPoint:
        """Return a new point displaced by ``meters`` along ``bearing_deg`` (0° = North)."""
        if meters == 0.0:
            return self
        angular_distance = meters / EARTH_RADIUS_M
        start_lat = math.radians(self.latitude)
        start_lon = math.radians(self.longitude)
        direction = math.radians(bearing_deg)

        lat_sin = math.sin(start_lat) * math.cos(angular_distance) + (
            math.cos(start_lat) * math.sin(angular_distance) * math.cos(direction)
        )
        end_lat = math.asin(min(1.0, max(-1.0, lat_sin)))
        end_lon = start_lon + math.atan2(
            math.sin(direction) * math.sin(angular_distance) * math.cos(start_lat),
            math.cos(angular_distance) - math.sin(start_lat) * math.sin(end_lat),
        )
        lon_deg = (math.degrees(end_lon) + 540.0) % 360.0 - 180.0
        return GeoPoint(latitude=math.degrees(end_lat), longitude=lon_deg)

    def distance_to(self, other: GeoPoint) -> float:
        """Return great-circle Haversine distance in meters to ``other``."""
        lat1 = math.radians(self.latitude)
        lat2 = math.radians(other.latitude)
        dlat = lat2 - lat1
        dlon = math.radians(other.longitude - self.longitude)
        a = (
            math.sin(dlat / 2.0) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
        return EARTH_RADIUS_M * c

    def to_list(self) -> list[float]:
        return [round(self.latitude, 7), round(self.longitude, 7)]


DEFAULT_START = GeoPoint(latitude=25.03396, longitude=121.56447)


@dataclass(frozen=True, slots=True)
class StickInput:
    """Normalized 2D joystick deflection vector (east, north)."""

    east: float
    north: float

    def __init__(self, east: float, north: float) -> None:
        e = float(east) if math.isfinite(east) else 0.0
        n = float(north) if math.isfinite(north) else 0.0
        scale = max(1.0, math.hypot(e, n))
        object.__setattr__(self, "east", e / scale)
        object.__setattr__(self, "north", n / scale)

    @classmethod
    def neutral(cls) -> StickInput:
        return cls(0.0, 0.0)

    @property
    def is_deflected(self) -> bool:
        return math.hypot(self.east, self.north) > 0.12

    @property
    def bearing_deg(self) -> float:
        return (math.degrees(math.atan2(self.east, self.north)) + 360.0) % 360.0


@dataclass
class NavigationEngine:
    """Stateful GPS movement simulator driven by joystick bearing and target speed."""

    position: GeoPoint = DEFAULT_START
    bearing: float = 0.0
    distance_m: float = 0.0
    trail: list[GeoPoint] = field(default_factory=lambda: [DEFAULT_START])
    motion: MotionState = "awaiting_direction"
    target_speed_kph: float = 5.0
    stick: StickInput = field(default_factory=StickInput.neutral)

    MAX_SPEED_KPH = 120.0
    MAX_TRAIL_POINTS = 1200
    TRAIL_TRIM_COUNT = 200
    TRAIL_MIN_STEP_M = 2.0

    @property
    def current_speed_kph(self) -> float:
        return self.target_speed_kph if self.motion == "moving" else 0.0

    def set_start(self, point: GeoPoint) -> bool:
        if not point.is_valid():
            return False
        self.position = point
        self.distance_m = 0.0
        self.trail = [point]
        self.stick = StickInput.neutral()
        if self.motion == "moving":
            self.motion = "paused"
        return True

    def set_stick(self, east: float, north: float) -> None:
        new_stick = StickInput(east, north)
        self.stick = new_stick
        if new_stick.is_deflected:
            self.bearing = new_stick.bearing_deg
            if self.motion == "awaiting_direction":
                self.motion = "moving"

    def set_speed(self, speed_kph: float) -> None:
        if not math.isfinite(speed_kph):
            return
        self.target_speed_kph = min(self.MAX_SPEED_KPH, max(0.0, float(speed_kph)))

    def toggle_motion(self) -> None:
        if self.motion == "moving":
            self.motion = "paused"
        elif self.motion == "paused":
            self.motion = "moving"

    def pause(self) -> None:
        self.stick = StickInput.neutral()
        if self.motion == "moving":
            self.motion = "paused"

    def clear_trail(self) -> None:
        self.trail = [self.position]
        self.distance_m = 0.0

    def tick(self, dt: float) -> bool:
        """Advance simulated coordinate by ``dt`` seconds. Returns True if moved."""
        if self.motion != "moving" or self.target_speed_kph <= 0.0 or dt <= 0.0:
            return False
        elapsed = min(0.25, dt)
        meters = (self.target_speed_kph / 3.6) * elapsed
        if meters <= 0.0:
            return False

        self.position = self.position.moved(meters=meters, bearing_deg=self.bearing)
        self.distance_m += meters

        if not self.trail or self.trail[-1].distance_to(self.position) >= self.TRAIL_MIN_STEP_M:
            self.trail.append(self.position)
            if len(self.trail) > self.MAX_TRAIL_POINTS:
                del self.trail[: self.TRAIL_TRIM_COUNT]
        return True

    def snapshot(self) -> dict[str, object]:
        return {
            "position": {"latitude": self.position.latitude, "longitude": self.position.longitude},
            "bearing": round(self.bearing, 2),
            "distance_m": round(self.distance_m, 2),
            "trail": [p.to_list() for p in self.trail],
            "motion": self.motion,
            "target_speed_kph": round(self.target_speed_kph, 2),
            "current_speed_kph": round(self.current_speed_kph, 2),
            "stick": {"east": round(self.stick.east, 4), "north": round(self.stick.north, 4)},
        }
