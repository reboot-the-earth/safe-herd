"""
Tests for the Facility Matcher module — Person 3.

Simulates the key demo scenario:
  Farm 1: Valley Center Ranch (150 cattle, 8 horses) → Ramona Rodeo full match
  Farm 2: Fallbrook Stables  (24 horses)             → Ramona capacity drops,
                                                        routed to Del Mar instead
  Farm 3: Bonsall Goat Co    (85 goats, 20 sheep)   → finds mixed facility with space

Run from the modules/facilities/ directory:
    python -m pytest tests/test_matching.py -v
or simply:
    python tests/test_matching.py
"""

import sys
import os
import json
import time

import pytest

# Run tests from the modules/facilities/ directory so imports resolve correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import capacity_manager
from facility_matcher import get_evacuation_match, load_facilities, match_facilities
from capacity_manager import (
    get_active_reservations,
    get_available_capacity,
    cancel_farm_reservations,
)
from trip_calculator import calculate_trips, summarize_trips


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_reservations():
    """Wipe the holds database between tests."""
    capacity_manager.reset_db()


def _print_section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def _print_result(result: dict):
    top = result.get("top_recommendation", "none")
    trips = result.get("evacuation_trips", [])
    warnings = result.get("warnings", [])
    reservations = result.get("reservations_made", [])

    print(f"  Top facility:     {top}")
    print(f"  Total trips:      {len(trips)}")
    print(f"  Total hours:      {result.get('total_evacuation_hours', 0):.2f} h")
    print(f"  Reservations:     {len(reservations)}")
    for r in reservations:
        animals = r.get("animals", {})
        summary = ", ".join(f"{c} {s}" for s, c in animals.items())
        print(f"    - {summary} @ {r['facility_name']} (expires {r['expires']})")
    if warnings:
        print("  Warnings:")
        for w in warnings:
            print(f"    ⚠ {w}")


# ---------------------------------------------------------------------------
# Mocks — fire danger zone that excludes Bonsall area facilities
# ---------------------------------------------------------------------------

# Small polygon around the Lilac Fire origin (Bonsall area)
# Bonsall Community Grounds (33.2887, -117.2252) is INSIDE this zone
FIRE_DANGER_ZONE = {
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [[
            [-117.27, 33.25],
            [-117.18, 33.25],
            [-117.18, 33.33],
            [-117.27, 33.33],
            [-117.27, 33.25],
        ]]
    }
}


# ---------------------------------------------------------------------------
# Shared scenario runners. Used by both the pytest fixtures below and the
# __main__ entry point so the file works as `pytest` AND `python ...`.
# ---------------------------------------------------------------------------


def _run_farm1() -> dict:
    _print_section("Farm 1: Valley Center Ranch — 150 cattle, 8 horses")
    _reset_reservations()

    result = get_evacuation_match(
        farm_id="valley_center_ranch",
        animal_inventory=[
            {"species": "cattle", "count": 150},
            {"species": "horses", "count": 8},
        ],
        trailer_capacity={"cattle": 20, "horses": 4},
        fire_danger_zone=FIRE_DANGER_ZONE,
        route_time_minutes=38,
        fire_arrival_hours=3.7,
        make_reservations=True,
    )

    _print_result(result)
    return result


def _run_farm2() -> dict:
    _print_section("Farm 2: Fallbrook Stables — 24 horses")
    result = get_evacuation_match(
        farm_id="fallbrook_stables",
        animal_inventory=[
            {"species": "horses", "count": 24},
        ],
        trailer_capacity={"horses": 6},
        fire_danger_zone=FIRE_DANGER_ZONE,
        route_time_minutes=52,
        fire_arrival_hours=2.1,
        make_reservations=True,
    )
    _print_result(result)
    return result


def _run_farm3() -> dict:
    _print_section("Farm 3: Bonsall Goat Co — 85 goats, 20 sheep")
    result = get_evacuation_match(
        farm_id="bonsall_goat_co",
        animal_inventory=[
            {"species": "goats", "count": 85},
            {"species": "sheep", "count": 20},
        ],
        trailer_capacity={"goats": 20, "sheep": 20},
        fire_danger_zone=FIRE_DANGER_ZONE,
        route_time_minutes=42,
        fire_arrival_hours=2.8,
        make_reservations=True,
    )
    _print_result(result)
    return result


# Module-scoped so test_farm2 sees the reservations made by farm1_result.
@pytest.fixture(scope="module")
def farm1_result() -> dict:
    return _run_farm1()


# ---------------------------------------------------------------------------
# Test 1: Farm 1 — Valley Center Ranch
# ---------------------------------------------------------------------------

def test_farm1_valley_center_ranch(farm1_result: dict):
    matched = farm1_result["matched_facilities"]
    assert len(matched) > 0, "Should find at least one facility"

    # Top facility must be a full match (accepts both cattle and horses)
    top = matched[0]
    assert top["match_type"] == "full_match", (
        f"Top match should be full_match, got {top['match_type']}"
    )
    assert "cattle" in top["can_accept"], "Top facility must accept cattle"
    assert "horses" in top["can_accept"], "Top facility must accept horses"

    # Reservations should have been created
    reservations = farm1_result["reservations_made"]
    assert len(reservations) > 0, "Reservations should be made for Farm 1"

    # Bonsall Community Grounds should be excluded (inside fire zone)
    facility_ids = {m["facility_id"] for m in matched}
    assert "bonsall_community_grounds" not in facility_ids, (
        "Bonsall Community Grounds should be excluded (inside fire zone)"
    )

    print("\n  PASS: Farm 1 test passed.")


# ---------------------------------------------------------------------------
# Test 2: Farm 2 — Fallbrook Stables (after Farm 1 has reserved)
# ---------------------------------------------------------------------------

def test_farm2_fallbrook_stables(farm1_result: dict):
    # Farm 1's reservations are still active — do NOT reset
    top_farm1_id = farm1_result["top_recommendation"]

    result = _run_farm2()

    matched = result["matched_facilities"]
    assert len(matched) > 0, "Farm 2 should find at least one facility"

    # Capacity at Farm 1's top facility should be reduced
    facilities = load_facilities()
    facility_dict = {f["id"]: f for f in facilities}

    if top_farm1_id in facility_dict:
        top_facility = facility_dict[top_farm1_id]
        if "horses" in top_facility["accepts"]:
            available_horses = get_available_capacity(top_facility, "horses")
            # Farm 1 reserved 8 horses — available should be (buffered - 8)
            buffered = int(top_facility["capacity"].get("horses", 0) * 0.80)
            assert available_horses == buffered - 8, (
                f"After Farm 1 reserved 8 horses, expected {buffered - 8} available, "
                f"got {available_horses}"
            )
            print(f"\n  Capacity check @ {top_farm1_id}: "
                  f"{available_horses} horses available (was {buffered}, Farm 1 reserved 8)")

    # Del Mar Fairgrounds should appear as an option (it accepts horses, large capacity)
    top = matched[0]
    print(f"  Farm 2 routed to: {top['name']} (match_type={top['match_type']})")

    print("\n  PASS: Farm 2 test passed.")


# ---------------------------------------------------------------------------
# Test 3: Farm 3 — Bonsall Goat Co
# ---------------------------------------------------------------------------

def test_farm3_bonsall_goat_co():
    result = _run_farm3()
    matched = result["matched_facilities"]
    assert len(matched) > 0, "Farm 3 should find at least one facility"

    top = matched[0]
    assert "goats" in top["can_accept"], "Top facility must accept goats"

    print("\n  PASS: Farm 3 test passed.")


# ---------------------------------------------------------------------------
# Test 4: Capacity depletion — sequential reservation integrity
# ---------------------------------------------------------------------------

def test_capacity_depletion():
    _print_section("Sequential reservation integrity check")
    _reset_reservations()

    # Make three large reservations at Ramona Rodeo (240 cattle buffered cap)
    facilities = {f["id"]: f for f in load_facilities()}
    ramona = facilities["ramona_rodeo_grounds"]

    from capacity_manager import reserve_capacity

    r1 = reserve_capacity("farm_a", "ramona_rodeo_grounds", animals={"cattle": 100}, facility=ramona)
    available_after_1 = get_available_capacity(ramona, "cattle")
    print(f"  After 100 cattle reserved: {available_after_1} available (expected 140)")

    r2 = reserve_capacity("farm_b", "ramona_rodeo_grounds", animals={"cattle": 100}, facility=ramona)
    available_after_2 = get_available_capacity(ramona, "cattle")
    print(f"  After 200 cattle reserved: {available_after_2} available (expected 40)")

    # Third reservation of 100 should fail (only 40 left)
    try:
        reserve_capacity("farm_c", "ramona_rodeo_grounds", animals={"cattle": 100}, facility=ramona)
        assert False, "Should have raised ValueError — not enough capacity"
    except ValueError as e:
        print(f"  Correctly rejected over-booking: {e}")

    assert available_after_1 == 140, f"Expected 140 after first reservation, got {available_after_1}"
    assert available_after_2 == 40, f"Expected 40 after second reservation, got {available_after_2}"

    _reset_reservations()
    print("\n  PASS: Capacity depletion test passed.")


# ---------------------------------------------------------------------------
# Test 5: Fire zone exclusion
# ---------------------------------------------------------------------------

def test_fire_zone_exclusion():
    _print_section("Fire zone exclusion — Bonsall should be filtered out")
    _reset_reservations()

    facilities = load_facilities()
    matched = match_facilities(
        animal_inventory=[{"species": "cattle", "count": 10}],
        facilities=facilities,
        fire_danger_zone=FIRE_DANGER_ZONE,
    )

    facility_ids = {m["facility_id"] for m in matched}
    assert "bonsall_community_grounds" not in facility_ids, (
        "Bonsall Community Grounds should be excluded from results"
    )
    print(f"  Matched facilities: {', '.join(facility_ids)}")
    print("\n  PASS: Fire zone exclusion test passed.")


# ---------------------------------------------------------------------------
# Test 6: Trip calculator
# ---------------------------------------------------------------------------

def test_trip_calculator():
    _print_section("Trip calculator — 150 cattle, 8 horses, 38-min route")

    trips = calculate_trips(
        animal_inventory=[
            {"species": "horses", "count": 8},
            {"species": "cattle", "count": 150},
        ],
        trailer_capacity={"horses": 4, "cattle": 20},
        route_time_minutes=38,
        destination_name="Ramona Rodeo Grounds",
    )

    summary = summarize_trips(trips, fire_arrival_hours=3.7)

    print(f"  Total trips:  {summary['total_trips']}")
    print(f"  Total hours:  {summary['total_hours']} h")
    print(f"  First depart: {summary['first_departure']}")
    print(f"  Last return:  {summary['last_return']}")
    if summary["warnings"]:
        for w in summary["warnings"]:
            print(f"  ⚠ {w}")

    # Horses (priority) go first — trip 1 should be horses
    assert trips[0]["species"] == "horses", "First trip should be horses (highest priority)"
    assert trips[0]["count"] == 4, "First horse trip should load 4 (trailer capacity)"
    assert trips[1]["count"] == 4, "Second horse trip should load remaining 4"

    # Cattle follow
    cattle_trips = [t for t in trips if t["species"] == "cattle"]
    total_cattle = sum(t["count"] for t in cattle_trips)
    assert total_cattle == 150, f"Expected 150 cattle across trips, got {total_cattle}"

    print("\n  PASS: Trip calculator test passed.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nWildfireWizards — Facility Matcher Tests")
    print("Demo scenario: 2017 Lilac Fire, Bonsall area\n")

    test_capacity_depletion()
    test_fire_zone_exclusion()
    test_trip_calculator()

    farm1 = _run_farm1()
    test_farm1_valley_center_ranch(farm1)
    test_farm2_fallbrook_stables(farm1)
    test_farm3_bonsall_goat_co()

    _print_section("ALL TESTS PASSED")
    print()
