"""
Safe Route Engine — main module for WildfireWizards routing.

Exposes one function: find_safe_routes()
  Input:  farm coordinates, facility list, fire polygons
  Output: ranked routes as GeoJSON with safety scores

This module does NOT import any other WildfireWizards module directly.
It reads JSON from data/ and returns JSON.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone

import networkx as nx

from .graph_loader import load_road_graph, build_demo_graph, _DEMO_NODES
from .fire_overlay import (
    tag_edges_with_fire_risk,
    calc_min_fire_distance,
    get_segment_status,
)
from .trailer_filter import apply_trailer_weights, check_trailer_friendly

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


def _nearest_node(graph, lon, lat):
    """
    Find the nearest graph node to (lat, lon).

    Works with both OSMnx integer node ids (with 'x'/'y' attrs)
    and our demo string node ids.
    """
    best_node = None
    best_dist = float("inf")
    for node_id, nd in graph.nodes(data=True):
        nx_ = nd.get("x", 0)
        ny_ = nd.get("y", 0)
        d = (nx_ - lon) ** 2 + (ny_ - lat) ** 2
        if d < best_dist:
            best_dist = d
            best_node = node_id
    return best_node


def _nodes_to_geojson(graph, path):
    """Convert a list of node ids to a GeoJSON LineString."""
    coords = []
    for node_id in path:
        nd = graph.nodes[node_id]
        coords.append([nd.get("x", 0), nd.get("y", 0)])
    return {"type": "LineString", "coordinates": coords}


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _build_segments(graph, path, fire_polygons):
    """
    Break a route into road-name segments with status and time.

    Consecutive edges on the same named road are merged into one segment.
    """
    if len(path) < 2:
        return []

    segments = []
    current_road = None
    current_status = None
    current_time = 0.0

    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        edge_data = graph.get_edge_data(u, v)
        if edge_data is None:
            continue

        road_name = edge_data.get("name", "Unknown Rd")
        status = edge_data.get("fire_status", "safe")
        base_time = edge_data.get("base_time", edge_data.get("travel_time", 60))

        if road_name == current_road and status == current_status:
            current_time += base_time
        else:
            if current_road is not None:
                segments.append({
                    "road": current_road,
                    "status": current_status,
                    "time_min": max(1, round(current_time / 60)),
                })
            current_road = road_name
            current_status = status
            current_time = base_time

    if current_road is not None:
        segments.append({
            "road": current_road,
            "status": current_status,
            "time_min": max(1, round(current_time / 60)),
        })

    return segments


def _total_distance_km(graph, path):
    """Sum the length of all edges in a path, in km."""
    total = 0.0
    for i in range(len(path) - 1):
        edge_data = graph.get_edge_data(path[i], path[i + 1])
        if edge_data:
            total += edge_data.get("length", 0) / 1000.0
    return round(total, 1)


def _safety_score(min_fire_dist_km, has_risky_segments):
    """
    Compute a 0-100 safety score.

    100 = completely safe, 0 = route goes through fire.
    """
    dist_score = min(min_fire_dist_km / 10.0, 1.0) * 80
    risk_penalty = 20 if has_risky_segments else 0
    return max(0, round(dist_score + (20 - risk_penalty)))


def _generate_warnings(segments, min_fire_dist_km, trailer_friendly):
    """Generate human-readable warnings for a route."""
    warnings = []
    for seg in segments:
        if seg["status"] in ("at_risk_in_2hr", "at_risk_in_4hr", "near_fire"):
            warnings.append(
                f"Passes within {min_fire_dist_km}km of projected fire line on {seg['road']}"
            )
    if not trailer_friendly:
        warnings.append("Route includes roads not suitable for livestock trailers")
    return warnings


def find_safe_routes(farm_coords, facility_list, fire_polygons):
    """
    Find safe evacuation routes from a farm to candidate facilities.

    Parameters
    ----------
    farm_coords : tuple
        (lat, lon) of the farm.
    facility_list : list[dict]
        Each dict has at minimum: facility_id, name, lat, lon.
    fire_polygons : dict
        Person 1's output with current_perimeter, projected_perimeters, wind.

    Returns
    -------
    dict
        Ranked routes with safety scores, GeoJSON geometries, and segments.
    """
    graph = load_road_graph()
    tag_edges_with_fire_risk(graph, fire_polygons)
    apply_trailer_weights(graph)

    farm_lat, farm_lon = farm_coords
    farm_node = _nearest_node(graph, farm_lon, farm_lat)

    routes = []
    for facility in facility_list:
        fac_lat = facility["lat"]
        fac_lon = facility["lon"]
        fac_node = _nearest_node(graph, fac_lon, fac_lat)

        try:
            path = nx.dijkstra_path(graph, farm_node, fac_node, weight="weight")
            total_weight = nx.dijkstra_path_length(graph, farm_node, fac_node, weight="weight")

            if total_weight >= 1e15:
                routes.append({
                    "rank": None,
                    "facility_id": facility["facility_id"],
                    "facility_name": facility.get("name", facility["facility_id"]),
                    "status": "no_safe_route",
                    "reason": "All access roads intersect current fire perimeter",
                })
                continue

            min_fire_dist = calc_min_fire_distance(graph, path, fire_polygons)
            segments = _build_segments(graph, path, fire_polygons)
            trailer_ok = check_trailer_friendly(graph, path)
            total_dist = _total_distance_km(graph, path)

            base_time_sec = sum(
                graph.get_edge_data(path[i], path[i + 1]).get(
                    "base_time", graph.get_edge_data(path[i], path[i + 1]).get("travel_time", 60)
                )
                for i in range(len(path) - 1)
                if graph.get_edge_data(path[i], path[i + 1]) is not None
            )
            total_time_min = max(1, round(base_time_sec / 60))

            has_risky = any(
                s["status"] in ("at_risk_in_2hr", "at_risk_in_4hr", "near_fire")
                for s in segments
            )
            score = _safety_score(min_fire_dist, has_risky)
            warnings = _generate_warnings(segments, min_fire_dist, trailer_ok)

            routes.append({
                "rank": None,  # assigned after sorting
                "facility_id": facility["facility_id"],
                "facility_name": facility.get("name", facility["facility_id"]),
                "facility_lat": fac_lat,
                "facility_lon": fac_lon,
                "total_time_min": total_time_min,
                "total_distance_km": total_dist,
                "safety_score": score,
                "min_fire_distance_km": min_fire_dist,
                "trailer_friendly": trailer_ok,
                "route_geometry": _nodes_to_geojson(graph, path),
                "segments": segments,
                "warnings": warnings,
                "status": "safe" if min_fire_dist > 2 else "risky",
            })

        except nx.NetworkXNoPath:
            routes.append({
                "rank": None,
                "facility_id": facility["facility_id"],
                "facility_name": facility.get("name", facility["facility_id"]),
                "status": "no_safe_route",
                "reason": "All access roads intersect current fire perimeter",
            })

    routable = [r for r in routes if r.get("total_time_min") is not None]
    unroutable = [r for r in routes if r.get("total_time_min") is None]

    routable.sort(key=lambda r: (-r["safety_score"], r["total_time_min"]))
    for i, r in enumerate(routable, 1):
        r["rank"] = i

    now = datetime.now(timezone.utc)
    return {
        "farm": {
            "lat": farm_lat,
            "lon": farm_lon,
        },
        "routes_to_facilities": routable + unroutable,
        "timestamp": now.isoformat(),
        "next_recalculation": (now + timedelta(minutes=30)).isoformat(),
    }


# ---------------------------------------------------------------------------
# Convenience: run from command line with demo data
# ---------------------------------------------------------------------------

def run_demo():
    """Run routing with the Lilac Fire demo data and print results."""
    fire_path = os.path.join(DATA_DIR, "fire_data.json")
    fac_path = os.path.join(DATA_DIR, "facilities.json")

    with open(fire_path) as f:
        fire_data = json.load(f)
    with open(fac_path) as f:
        fac_data = json.load(f)

    farm_coords = (33.22, -117.03)  # Valley Center Ranch
    facility_list = fac_data["facilities"]

    result = find_safe_routes(farm_coords, facility_list, fire_data)
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run_demo()
