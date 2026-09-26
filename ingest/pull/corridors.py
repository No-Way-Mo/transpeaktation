"""Road corridors we poll for live speed/congestion (Mapbox driving-traffic).

End points are intersections looked up in DataSF's street network (streets.json),
as (lon, lat). Budget: Mapbox's free tier is 100,000 Directions requests/month;
17 requests every 10 minutes is ~73k/month. Adding corridors means polling less
often (see poll.py's budget guard).
"""
from __future__ import annotations

from dataclasses import dataclass

LonLat = tuple[float, float]


@dataclass(frozen=True)
class Corridor:
    key: str
    name: str
    a: LonLat
    b: LonLat
    both_directions: bool = True  # False for one-way streets (poll a -> b only)
    why: str = ""

    def legs(self) -> list[tuple[str, LonLat, LonLat]]:
        legs = [("ab", self.a, self.b)]
        if self.both_directions:
            legs.append(("ba", self.b, self.a))
        return legs


CORRIDORS: list[Corridor] = [
    # Marina / July 4 demo area
    Corridor("lombard", "Lombard St: Richardson Ave <-> Van Ness Ave",
             (-122.444828, 37.79884), (-122.424538, 37.801304), why="US-101 surface route to the Golden Gate Bridge"),
    Corridor("marina_bay", "Marina Blvd @ Baker St <-> Bay St @ Powell St",
             (-122.447287, 37.80516), (-122.41195, 37.805825), why="Marina Green / Fort Mason / Fisherman's Wharf"),
    Corridor("embarcadero", "The Embarcadero: Bay St <-> King St",
             (-122.405659, 37.806674), (-122.388306, 37.781798), why="Waterfront: Pier 39, Ferry Building, Oracle Park"),
    # Venues
    Corridor("third_st", "3rd St: King St <-> 16th St",
             (-122.391841, 37.778126), (-122.389099, 37.766903), why="Oracle Park <-> Chase Center"),
    Corridor("howard", "Howard St: 3rd St -> 6th St (one-way westbound)",
             (-122.400468, 37.78503), (-122.407159, 37.779739), both_directions=False, why="Moscone Center"),
    Corridor("van_ness", "Van Ness Ave: Lombard St <-> Market St",
             (-122.424538, 37.801304), (-122.419256, 37.775147), why="US-101 through the city; Civic Center venues"),
    Corridor("geary", "Geary Blvd: Van Ness Ave <-> Arguello Blvd",
             (-122.421393, 37.785686), (-122.458859, 37.781257), why="Main east-west arterial (Fillmore venues)"),
    Corridor("park_presidio", "Park Presidio Blvd: California St <-> Fulton St",
             (-122.472586, 37.784449), (-122.471762, 37.773139), why="CA-1 into Golden Gate Park (Outside Lands)"),
    Corridor("fulton", "Fulton St: Stanyan St <-> Park Presidio Blvd",
             (-122.454683, 37.774755), (-122.471762, 37.773139), why="Golden Gate Park north edge"),
]


def requests_per_poll(corridors: list[Corridor] = CORRIDORS) -> int:
    return sum(len(c.legs()) for c in corridors)
