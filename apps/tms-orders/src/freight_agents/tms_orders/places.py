"""The cities the made-up network serves, with the time zone each stop's times are in."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

# Planning assumptions, not law: road miles run about 1.2 times the straight line, and one
# driver covers about 500 road miles a day.
ROAD_FACTOR = 1.2
MILES_PER_DAY = 500


@dataclass(frozen=True)
class Place:
    code: str
    city: str
    state: str
    zip: str
    time_zone: str
    lat: float
    lon: float


PLACES = [
    Place("CHI", "Chicago", "IL", "60632", "America/Chicago", 41.88, -87.63),
    Place("DAL", "Dallas", "TX", "75212", "America/Chicago", 32.78, -96.80),
    Place("MEM", "Memphis", "TN", "38118", "America/Chicago", 35.15, -90.05),
    Place("ATL", "Atlanta", "GA", "30336", "America/New_York", 33.75, -84.39),
    Place("MIA", "Miami", "FL", "33166", "America/New_York", 25.76, -80.19),
    Place("NWK", "Newark", "NJ", "07114", "America/New_York", 40.74, -74.17),
    Place("BOS", "Boston", "MA", "02118", "America/New_York", 42.36, -71.06),
    Place("CLT", "Charlotte", "NC", "28208", "America/New_York", 35.23, -80.84),
    Place("DEN", "Denver", "CO", "80216", "America/Denver", 39.74, -104.99),
    Place("SLC", "Salt Lake City", "UT", "84104", "America/Denver", 40.76, -111.89),
    # Arizona keeps standard time all year, so its offset to the other zones changes.
    Place("PHX", "Phoenix", "AZ", "85043", "America/Phoenix", 33.45, -112.07),
    Place("LAX", "Los Angeles", "CA", "90021", "America/Los_Angeles", 34.05, -118.24),
]


def zone_for(city: str, state: str) -> str | None:
    """A city's time zone by city and state; states such as Texas span more than one."""
    for place in PLACES:
        if place.city.lower() == city.strip().lower() and place.state == state.strip().upper():
            return place.time_zone
    return None


class Located(Protocol):
    @property
    def city(self) -> str: ...

    @property
    def state(self) -> str: ...


def zone_place(where: Located) -> Place:
    """The place a party is in, by city and state."""
    for place in PLACES:
        if place.city == where.city and place.state == where.state:
            return place
    raise KeyError(f"{where.city}, {where.state} is not in the network")


def miles(a: Place, b: Place) -> float:
    """Estimated road miles: great-circle distance times the road factor."""
    la1, lo1, la2, lo2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = (
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    )
    return 3958.8 * 2 * math.asin(math.sqrt(h)) * ROAD_FACTOR


def transit_days(a: Place, b: Place) -> int:
    return max(1, math.ceil(miles(a, b) / MILES_PER_DAY))
