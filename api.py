"""
WildfireWizards API Server — Person 5 integration layer.

Wraps Person 1 (fire), Person 2 (routing), and Person 3 (facilities)
into a simple Flask API consumed by the React frontend.

Usage:
    pip install flask flask-cors
    python api.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS

ROOT = os.path.dirname(os.path.abspath(__file__))
MODULES = os.path.join(ROOT, "modules")
DATA = os.path.join(ROOT, "data")

sys.path.insert(0, ROOT)
sys.path.insert(0, MODULES)
sys.path.insert(0, os.path.join(MODULES, "facilities"))

from contracts.loader import load_facilities as load_contract_facilities
from facilities.capacity_manager import (
    reserve_capacity, confirm_hold, release_hold, get_hold, get_farm_holds,
)

from fire_detection import get_fire_data
from routing import find_safe_routes

try:
    from facilities.facility_matcher import get_evacuation_match, load_facilities as load_p3_facilities
except ImportError:
    from facility_matcher import get_evacuation_match, load_facilities as load_p3_facilities

try:
    from farmer_input.priority_engine import get_evacuation_plan as p4_get_evacuation_plan
except ImportError:
    sys.path.insert(0, os.path.join(MODULES, "farmer_input"))
    from priority_engine import get_evacuation_plan as p4_get_evacuation_plan

app = Flask(__name__)
CORS(app, origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:5173", "http://127.0.0.1:3000"])


def _load_config():
    with open(os.path.join(ROOT, "config.json")) as f:
        return json.load(f)


def _load_fire_data_file():
    with open(os.path.join(DATA, "fire_data.json")) as f:
        return json.load(f)


def _load_facilities_file():
    return {"facilities": load_contract_facilities()}


DEMO_FARMS = [
    {
        "farm_id": "valley_center_ranch",
        "name": "Valley Center Ranch",
        "lat": 33.22,
        "lon": -117.03,
        "animals": [
            {"species": "cattle", "count": 150},
            {"species": "horses", "count": 8},
        ],
        "trailer_capacity": {"cattle": 20, "horses": 4},
    },
    {
        "farm_id": "fallbrook_stables",
        "name": "Fallbrook Equestrian Center",
        "lat": 33.37,
        "lon": -117.25,
        "animals": [
            {"species": "horses", "count": 24},
        ],
        "trailer_capacity": {"horses": 4},
    },
    {
        "farm_id": "ramona_goat_farm",
        "name": "Ramona Heritage Goat Farm",
        "lat": 33.05,
        "lon": -116.87,
        "animals": [
            {"species": "goats", "count": 85},
            {"species": "poultry", "count": 200},
        ],
        "trailer_capacity": {"goats": 30, "poultry": 100},
    },
]


@app.route("/api/fire", methods=["GET"])
def fire_endpoint():
    """
    Get fire spread data from Person 1's module.

    Query params: ?live=true to call get_fire_data() directly,
    otherwise serves cached data/fire_data.json.
    """
    use_live = request.args.get("live", "false").lower() == "true"

    if use_live:
        try:
            config = _load_config()
            farm_locations = [
                {"farm_id": f["farm_id"], "lat": f["lat"], "lon": f["lon"]}
                for f in DEMO_FARMS
            ]
            result = get_fire_data(
                bounding_box=config["bounding_box"],
                farm_locations=farm_locations,
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e), "fallback": True, **_load_fire_data_file()}), 200

    return jsonify(_load_fire_data_file())


@app.route("/api/facilities", methods=["GET"])
def facilities_endpoint():
    """
    Get all facilities from Person 3's database.
    Returns both the data/ version and Person 3's detailed version.
    """
    try:
        p3_facilities = load_p3_facilities()
        return jsonify({"facilities": p3_facilities, "source": "person3"})
    except Exception:
        fac_data = _load_facilities_file()
        return jsonify({**fac_data, "source": "data_dir"})


@app.route("/api/routes", methods=["POST"])
def routes_endpoint():
    """
    Get safe routes from Person 2's module.

    POST body: {
        "farm_lat": 33.22,
        "farm_lon": -117.03
    }
    """
    body = request.get_json(force=True)
    farm_lat = body.get("farm_lat", 33.22)
    farm_lon = body.get("farm_lon", -117.03)

    fire_data = _load_fire_data_file()
    fac_data = _load_facilities_file()

    try:
        result = find_safe_routes(
            farm_coords=(farm_lat, farm_lon),
            facility_list=fac_data["facilities"],
            fire_polygons=fire_data,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "routes_to_facilities": []}), 200


@app.route("/api/plan", methods=["POST"])
def plan_endpoint():
    """
    Get evacuation plan from Person 3's facility matcher.

    POST body: {
        "farm_id": "valley_center_ranch",
        "animals": [{"species": "cattle", "count": 150}, ...],
        "trailer_capacity": {"cattle": 20, "horses": 4},
        "route_time_minutes": 38,
        "fire_arrival_hours": 3.7
    }
    """
    body = request.get_json(force=True)
    farm_id = body.get("farm_id", "unknown")
    animals = body.get("animals", [])
    trailer_cap = body.get("trailer_capacity", {"cattle": 20, "horses": 4})
    route_time = body.get("route_time_minutes", 38)
    fire_hours = body.get("fire_arrival_hours")

    fire_data = _load_fire_data_file()
    danger_zone = fire_data.get("projected_perimeters", {}).get("6hr")

    try:
        result = get_evacuation_match(
            farm_id=farm_id,
            animal_inventory=animals,
            trailer_capacity=trailer_cap,
            fire_danger_zone=danger_zone,
            route_time_minutes=route_time,
            fire_arrival_hours=fire_hours,
            make_reservations=False,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 200


@app.route("/api/farmer-profiles", methods=["GET"])
def farmer_profiles_endpoint():
    """Return Person 4's pre-loaded demo farm profiles."""
    profiles_path = os.path.join(MODULES, "farmer_input", "demo_profiles.json")
    try:
        with open(profiles_path) as f:
            return jsonify({"profiles": json.load(f)})
    except FileNotFoundError:
        return jsonify({"profiles": [], "error": "demo_profiles.json missing"}), 200


@app.route("/api/farmer-plan", methods=["POST"])
def farmer_plan_endpoint():
    """
    Generate Person 4's evacuation plan + species-specific checklist.

    POST body: {
        "farm": {"id": "...", "name": "...", "lat": ..., "lon": ...,
                 "smoke_within_5_miles": false},
        "animals": [{"species": "cattle", "count": 150,
                     "special_needs": ["12 calves with mothers"]}, ...],
        "transport": {"trailers": 1, "type": "stock_trailer",
                      "capacity": {"cattle": 20, "horses": 4}},
        "time_available_hours": 3.7
    }
    """
    body = request.get_json(force=True) or {}
    farm = body.get("farm") or {}
    animals = body.get("animals") or []
    transport = body.get("transport") or {"trailers": 1, "type": "stock_trailer"}
    time_hours = body.get("time_available_hours")

    if time_hours is None:
        farm_id = farm.get("id")
        try:
            fire_data = _load_fire_data_file()
            for f in fire_data.get("farms_at_risk", []):
                if f.get("farm_id") == farm_id or f.get("name") == farm.get("name"):
                    time_hours = f.get("estimated_time_to_fire_hours") or f.get("hours_to_fire")
                    break
        except Exception:
            pass
        if time_hours is None:
            time_hours = 3.7

    try:
        plan = p4_get_evacuation_plan(
            farm=farm,
            animal_inventory=animals,
            transport=transport,
            time_available_hours=float(time_hours),
        )
        return jsonify(plan)
    except Exception as e:
        return jsonify({"error": str(e)}), 200


@app.route("/api/holds", methods=["POST"])
def holds_create():
    """
    Create a capacity hold.

    POST body: {
        "farm_id": "valley_center_ranch",
        "facility_id": "del_mar_fairgrounds",
        "animals": {"cattle": 50, "horses": 8},
        "request_id": "optional-idempotency-key"
    }
    """
    body = request.get_json(force=True)
    farm_id = body.get("farm_id")
    facility_id = body.get("facility_id")
    animals = body.get("animals")
    request_id = body.get("request_id")

    if not farm_id or not facility_id or not animals:
        return jsonify({"error": "farm_id, facility_id, and animals are required"}), 400

    try:
        hold = reserve_capacity(farm_id, facility_id, animals=animals, request_id=request_id)
        return jsonify(hold), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 409


@app.route("/api/holds/<hold_id>", methods=["GET"])
def holds_get(hold_id):
    hold = get_hold(hold_id)
    if not hold:
        return jsonify({"error": "Hold not found"}), 404
    return jsonify(hold)


@app.route("/api/holds/<hold_id>/confirm", methods=["POST"])
def holds_confirm(hold_id):
    try:
        hold = confirm_hold(hold_id)
        return jsonify(hold)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409


@app.route("/api/holds/<hold_id>/release", methods=["POST"])
def holds_release(hold_id):
    try:
        hold = release_hold(hold_id)
        return jsonify(hold)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409


@app.route("/api/farms/<farm_id>/holds", methods=["GET"])
def farm_holds(farm_id):
    status = request.args.get("status")
    holds = get_farm_holds(farm_id, status=status)
    return jsonify({"farm_id": farm_id, "holds": holds})


@app.route("/api/health", methods=["GET"])
def health():
    """Health check showing which modules loaded."""
    modules = {
        "fire_detection": "get_fire_data" in dir(sys.modules.get("fire_detection", {})),
        "routing": "find_safe_routes" in dir(sys.modules.get("routing", {})),
        "facilities": True,
        "farmer_input": "p4_get_evacuation_plan" in globals(),
    }
    return jsonify({"status": "ok", "modules": modules})


if __name__ == "__main__":
    print("\n  WildfireWizards API Server")
    print("  http://localhost:5001/api/health\n")
    app.run(host="0.0.0.0", port=5001, debug=True)
