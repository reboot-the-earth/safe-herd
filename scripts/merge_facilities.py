#!/usr/bin/env python3
"""
One-off script: merge data/facilities.json (5 entries, facility_id key)
with modules/facilities/data/facilities.json (18 entries, id key)
into one unified file in the contract's facility_card format.

Prints every conflict for human review.
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE_A = ROOT / "data" / "facilities.json"                      # 5 entries
FILE_B = ROOT / "modules" / "facilities" / "data" / "facilities.json"  # 18 entries


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def normalize_name(name):
    return name.lower().replace("—", " ").replace("-", " ").replace("&", "and").strip()


def main():
    with open(FILE_A) as f:
        data_a = json.load(f)
    entries_a = data_a["facilities"] if isinstance(data_a, dict) else data_a

    with open(FILE_B) as f:
        entries_b = json.load(f)

    # Index B by id
    b_by_id = {e["id"]: e for e in entries_b}

    # Try to match A entries to B entries by name similarity + distance
    matched = {}  # a_id -> b_id
    for a in entries_a:
        a_id = a.get("facility_id") or a.get("id")
        a_name = normalize_name(a["name"])
        best = None
        best_dist = 999
        for b in entries_b:
            b_name = normalize_name(b["name"])
            dist = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            # Match if names share a keyword and within 1 km, OR ids overlap
            a_words = set(a_name.split())
            b_words = set(b_name.split())
            name_overlap = len(a_words & b_words) >= 2
            id_overlap = (a_id.replace("_", "") in b["id"].replace("_", "") or
                          b["id"].replace("_", "") in a_id.replace("_", ""))
            if (name_overlap or id_overlap) and dist < 5:
                if dist < best_dist:
                    best = b
                    best_dist = dist
        if best:
            matched[a_id] = best["id"]
            print(f"MATCH: {a_id} <-> {best['id']} (distance: {best_dist:.2f} km)")

    # Report conflicts for matched pairs
    for a in entries_a:
        a_id = a.get("facility_id") or a.get("id")
        if a_id not in matched:
            continue
        b = b_by_id[matched[a_id]]
        # Compare capacities
        a_cap = a.get("capacity", {})
        b_cap = b.get("capacity", {})
        for species in set(list(a_cap.keys()) + list(b_cap.keys())):
            ac = a_cap.get(species, "absent")
            bc = b_cap.get(species, "absent")
            if ac != bc:
                print(f"  CONFLICT [{b['name']}] {species}: data/={ac} vs modules/={bc}"
                      f"  -> using modules/ (source: {b.get('source', 'unknown')})")

    # Build merged list: start with all B entries (they're more complete),
    # add any A-only entries converted to contract format
    merged = list(entries_b)  # B is already in contract format
    a_only = [a for a in entries_a if (a.get("facility_id") or a.get("id")) not in matched]
    for a in a_only:
        a_id = a.get("facility_id") or a.get("id")
        # Convert A format to contract format
        accepts = [sp for sp, cap in a.get("capacity", {}).items() if cap > 0]
        converted = {
            "id": a_id,
            "name": a["name"],
            "lat": a["lat"],
            "lon": a["lon"],
            "accepts": accepts,
            "capacity": a.get("capacity", {}),
            "infrastructure": a.get("amenities", []),
            "access_road": " / ".join(a.get("access_roads", [])),
            "trailer_access": True,
            "hours": "",
            "contact": a.get("contact", ""),
            "county": "San Diego",
            "verified": True,
            "volunteer_run": False,
            "has_own_feed": False,
            "notes": "",
            "source": "data/facilities.json (hackathon)",
        }
        print(f"A-ONLY (no match in B): {a_id} -> converting to contract format")
        merged.append(converted)

    # Validate all entries against the schema
    sys.path.insert(0, str(ROOT))
    from contracts import validate
    from jsonschema import ValidationError

    errors = 0
    for entry in merged:
        try:
            validate("facility_card", entry)
        except ValidationError as e:
            print(f"  SCHEMA ERROR [{entry['id']}]: {e.message}")
            errors += 1

    output = ROOT / "data" / "facilities.json"
    with open(output, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\nMerged {len(merged)} facilities -> {output}")
    print(f"Schema errors: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
