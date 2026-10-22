"""
Facility Matcher — Person 3's main module.

Public entry point:
    get_evacuation_match(farm_id, animal_inventory, trailer_capacity,
                         fire_danger_zone, route_time_minutes) -> dict

The function:
  1. Loads the facility database.
  2. Filters out any facility inside the fire danger zone.
  3. Scores and ranks facilities against the farmer's animal inventory
     using live capacity (buffered + reservation-aware).
  4. Builds a multi-trip evacuation schedule for the best full-match facility.
  5. Creates reservations for all matched species.
  6. Returns a complete JSON payload consumed by Person 4 and Person 5.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Optional

from capacity_manager import (
    get_active_reservations,
    get_available_capacity,
    reserve_capacity,
    get_capacity_snapshot,
)
from trip_calculator import calculate_trips, summarize_trips

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from contracts.loader import load_facilities as _contract_load_facilities

# Facilities in neighbouring counties are deprioritised
OUT_OF_COUNTY_PENALTY = 10


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_facilities() -> list[dict]:
    return _contract_load_facilities()


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS-84 points, in kilometres."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _point_in_polygon(lat: float, lon: float, polygon: dict) -> bool:
    """
    Ray-casting test for GeoJSON polygon (first ring only).

    Accepts either a GeoJSON Feature with geometry or a bare GeoJSON geometry.
    Returns False if the polygon is None or malformed so the facility is not
    wrongly excluded.
    """
    if not polygon:
        return False
    try:
        geom = polygon.get("geometry", polygon)
        coords = geom["coordinates"][0]  # outer ring of first polygon
        x, y = lon, lat
        inside = False
        n = len(coords)
        j = n - 1
        for i in range(n):
            xi, yi = coords[i][0], coords[i][1]
            xj, yj = coords[j][0], coords[j][1]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside
    except (KeyError, TypeError, IndexError, ZeroDivisionError):
        return False


# ---------------------------------------------------------------------------
# Core matching
# ---------------------------------------------------------------------------

def _score_facility(
    facility: dict,
    animal_inventory: list[dict],
) -> Optional[dict]:
    """
    Evaluate a single facility against the animal inventory.

    Returns a scored dict, or None if the facility can accept nothing.
    """
    can_accept = []
    cannot_accept = []
    capacity_status = {}

    for animal in animal_inventory:
        species = animal["species"]
        count = animal["count"]

        if species not in facility["accepts"]:
            cannot_accept.append(species)
            continue

        available = get_available_capacity(facility, species)
        raw_cap = facility["capacity"].get(species, 0)
        buffered_cap = int(raw_cap * 0.80)
        reserved = buffered_cap - available

        capacity_status[species] = {
            "total": raw_cap,
            "buffered": buffered_cap,
            "reserved": reserved,
            "available": available,
            "you_need": count,
            "fits": available >= count,
        }

        if available >= count:
            can_accept.append(species)
        else:
            cannot_accept.append(
                f"{species} (need {count}, only {available} available)"
            )

    if not can_accept:
        return None

    if len(cannot_accept) == 0:
        match_type = "full_match"
        base_priority = 1
    else:
        match_type = "partial_match"
        base_priority = 2

    # Tie-break: prefer facilities with own feed, in-county, verified, non-volunteer
    score = base_priority * 100
    if facility.get("county", "San Diego") != "San Diego":
        score += OUT_OF_COUNTY_PENALTY
    if not facility.get("verified", True):
        score += 5
    if facility.get("volunteer_run", False):
        score += 3
    if facility.get("has_own_feed", False):
        score -= 2

    return {
        "facility_id": facility["id"],
        "name": facility["name"],
        "lat": facility["lat"],
        "lon": facility["lon"],
        "match_type": match_type,
        "priority_score": score,
        "can_accept": can_accept,
        "cannot_accept": cannot_accept,
        "capacity_status": capacity_status,
        "infrastructure": facility.get("infrastructure", []),
        "contact": facility.get("contact", ""),
        "hours": facility.get("hours", ""),
        "has_own_feed": facility.get("has_own_feed", False),
        "volunteer_run": facility.get("volunteer_run", False),
        "verified": facility.get("verified", True),
        "in_fire_zone": False,  # already filtered before calling this
        "notes": facility.get("notes", ""),
    }


def match_facilities(
    animal_inventory: list[dict],
    facilities: list[dict],
    fire_danger_zone: Optional[dict],
) -> list[dict]:
    """
    Filter, score, and rank all facilities.

    Returns a list of matched facility dicts sorted by priority_score ascending
    (lower = better).
    """
    results = []
    for facility in facilities:
        in_fire = _point_in_polygon(facility["lat"], facility["lon"], fire_danger_zone)
        if in_fire:
            continue  # skip — facility is in the fire path

        scored = _score_facility(facility, animal_inventory)
        if scored is None:
            continue

        results.append(scored)

    return sorted(results, key=lambda m: m["priority_score"])


# ---------------------------------------------------------------------------
# Public export — called by Person 5 (frontend)
# ---------------------------------------------------------------------------

def get_evacuation_match(
    farm_id: str,
    animal_inventory: list[dict],
    trailer_capacity: dict,
    fire_danger_zone: Optional[dict],
    route_time_minutes: int,
    fire_arrival_hours: Optional[float] = None,
    make_reservations: bool = True,
    requires_isolation: Optional[list[str]] = None,
    start_time: Optional[datetime] = None,
) -> dict:
    """
    Main entry point. Returns the complete evacuation match payload.

    Args:
        farm_id:             Unique farm identifier (e.g. "valley_center_ranch").
        animal_inventory:    [{"species": "cattle", "count": 150}, ...]
        trailer_capacity:    {"cattle": 20, "horses": 4}
        fire_danger_zone:    GeoJSON polygon from Person 1 (or None for mock).
        route_time_minutes:  One-way drive time from Person 2.
        fire_arrival_hours:  Hours until fire reaches the farm (from Person 1).
        make_reservations:   If True, auto-reserve capacity at the top facility.
        requires_isolation:  Species needing isolated trips (bulls, stallions…).
        start_time:          When loading starts (defaults to now).

    Returns:
        JSON-serialisable dict matching the output schema in the README.
    """
    facilities = load_facilities()
    matched = match_facilities(animal_inventory, facilities, fire_danger_zone)

    reservations_made = []
    evacuation_trips = []
    trip_summary = {}
    warnings = []

    # Build trip schedule for top full-match facility (or best partial)
    top_facility = matched[0] if matched else None

    if top_facility and make_reservations:
        animals_to_hold = {
            a["species"]: a["count"]
            for a in animal_inventory
            if a["species"] in top_facility["can_accept"]
        }
        if animals_to_hold:
            try:
                raw_facility = next(
                    (f for f in facilities if f["id"] == top_facility["facility_id"]), None
                )
                record = reserve_capacity(
                    farm_id, top_facility["facility_id"],
                    animals=animals_to_hold, facility=raw_facility,
                )
                reservations_made.append({
                    "hold_id": record["hold_id"],
                    "facility_id": record["facility_id"],
                    "facility_name": top_facility["name"],
                    "animals": animals_to_hold,
                    "expires": record["expires"],
                })
            except ValueError as e:
                warnings.append(str(e))

    if top_facility:
        evacuation_trips = calculate_trips(
            animal_inventory=[a for a in animal_inventory if a["species"] in top_facility["can_accept"]],
            trailer_capacity=trailer_capacity,
            route_time_minutes=route_time_minutes,
            destination_name=top_facility["name"],
            start_time=start_time or datetime.now(),
            requires_isolation=requires_isolation,
        )
        trip_summary = summarize_trips(evacuation_trips, fire_arrival_hours)
        warnings.extend(trip_summary.get("warnings", []))

        if top_facility.get("volunteer_run"):
            warnings.append(
                f"UNVERIFIED AVAILABILITY: {top_facility['name']} is volunteer-run. "
                "Call ahead to confirm space before departing."
            )

    # Surface any species that could not be placed anywhere
    all_species = {a["species"] for a in animal_inventory}
    placed_species = {a["species"] for a in animal_inventory if any(a["species"] in m["can_accept"] for m in matched)}
    unplaced = all_species - placed_species
    for sp in unplaced:
        warnings.append(
            f"NO FACILITY FOUND for {sp}. Contact SD County Animal Services: 619-767-2675."
        )

    return {
        "farm_id": farm_id,
        "animal_inventory": animal_inventory,
        "matched_facilities": matched,
        "top_recommendation": top_facility["facility_id"] if top_facility else None,
        "evacuation_trips": evacuation_trips,
        "trip_summary": trip_summary,
        "total_evacuation_hours": trip_summary.get("total_hours", 0),
        "reservations_made": reservations_made,
        "warnings": warnings,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# CLI quick-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = get_evacuation_match(
        farm_id="valley_center_ranch",
        animal_inventory=[
            {"species": "cattle", "count": 150},
            {"species": "horses", "count": 8},
        ],
        trailer_capacity={"cattle": 20, "horses": 4},
        fire_danger_zone=None,
        route_time_minutes=38,
        fire_arrival_hours=3.7,
        make_reservations=False,
    )
    print(json.dumps(result, indent=2, default=str))
