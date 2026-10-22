from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "modules"))
sys.path.insert(0, str(ROOT / "modules" / "facilities"))
sys.path.insert(0, str(ROOT / "modules" / "farmer_input"))

from facilities.facility_matcher import get_evacuation_match  # type: ignore
from farmer_input.priority_engine import get_evacuation_plan  # type: ignore
from routing import find_safe_routes  # type: ignore


def _chunk_text(message: str, limit: int = 160) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in message.split("\n"):
        cand = f"{current}\n{line}" if current else line
        if len(cand) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = cand
    if current:
        chunks.append(current)
    return chunks


def _best_route(routes: dict[str, Any]) -> dict[str, Any] | None:
    for r in routes.get("routes_to_facilities", []):
        if r.get("status") != "no_safe_route":
            return r
    return None


def generate_text_plan(
    farm: dict[str, Any],
    fire_data: dict[str, Any],
    facilities_data: dict[str, Any],
    neighbor_block: str | None = None,
) -> list[str]:
    animals = farm["animals"]
    transport = farm["transport"]
    farm_coords = (farm["lat"], farm["lon"])

    routes = find_safe_routes(farm_coords, facilities_data["facilities"], fire_data)
    best = _best_route(routes)
    route_time = int(best.get("total_time_min", 40)) if best else 40
    eta = 3.5
    for f in fire_data.get("farms_at_risk", []):
        if f.get("farm_id") == farm["farm_id"]:
            eta = f.get("hours_to_fire") or f.get("estimated_time_to_fire_hours") or eta
            break

    farmer_plan = get_evacuation_plan(
        farm={"id": farm["farm_id"], "name": farm["name"], "lat": farm["lat"], "lon": farm["lon"]},
        animal_inventory=animals,
        transport=transport,
        time_available_hours=float(eta),
    )

    perimeters = fire_data.get("projected_perimeters")
    if isinstance(perimeters, dict):
        fire_danger_zone = perimeters.get("6hr")
    elif isinstance(perimeters, list):
        fire_danger_zone = next((p.get("geometry") for p in sorted(perimeters, key=lambda x: x.get("hours", 0), reverse=True) if p.get("hours")), None)
    else:
        fire_danger_zone = None

    facility_match = get_evacuation_match(
        farm_id=farm["farm_id"],
        animal_inventory=animals,
        trailer_capacity=transport.get("capacity", {"cattle": 20, "horses": 4}),
        fire_danger_zone=fire_danger_zone,
        route_time_minutes=route_time,
        fire_arrival_hours=float(eta),
        make_reservations=False,
    )

    destination = "Unknown"
    contact = "Unknown"
    if facility_match.get("matched_facilities"):
        first = facility_match["matched_facilities"][0]
        destination = first.get("name", destination)
        contact = first.get("contact", contact)

    lines = [
        "WILDFIREWIZARDS EVACUATION PLAN",
        f"{farm['name']} — {datetime.now().strftime('%b %d, %Y %I:%M %p')}",
        "",
        f"TIME REMAINING: ~{eta:.1f} hours",
        "",
    ]
    if neighbor_block and neighbor_block.strip():
        lines.extend([neighbor_block.strip(), ""])
    lines.append("PRIORITY ORDER:")
    for step in farmer_plan.get("priority_plan", [])[:8]:
        if not step.get("can_transport", True):
            continue
        lines.append(
            f"{step['order']}. {step['animals']} | Load: {step['load_time_est_min']} min"
        )

    lines.extend([
        "",
        "DESTINATION:",
        destination,
        f"Contact: {contact}",
    ])

    if best:
        roads = " → ".join(seg.get("road", "Road") for seg in best.get("segments", [])[:3])
        lines.extend([
            "",
            f"ROUTE: {roads}",
            f"Status: {best.get('status', 'safe').upper()}",
        ])

    warning = farmer_plan.get("triage_warning")
    if warning:
        lines.extend(["", f"WARNING: {warning}"])

    return _chunk_text("\n".join(lines), 320)
