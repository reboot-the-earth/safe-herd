from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "modules"))

from fire_detection import get_fire_data  # type: ignore

from alert_system.config import BOUNDING_BOX, POLL_INTERVAL_SECONDS
from alert_system.farm_matcher import (
    build_neighbor_awareness_text,
    get_at_risk_farms,
    load_community_farms,
    load_registered_farms,
    mark_alert_sent,
)
from alert_system.config import NEIGHBOR_RADIUS_KM
from alert_system.plan_generator import generate_text_plan
from alert_system.sms_sender import send_alert, send_text_plan

running = True


def _stop(_sig, _frame):
    global running
    running = False


def run_once(send_plans: bool = False) -> dict:
    farms = load_registered_farms()
    farm_locations = [{"farm_id": f["farm_id"], "lat": f["lat"], "lon": f["lon"]} for f in farms]

    fire_data = get_fire_data(BOUNDING_BOX, farm_locations)
    at_risk = get_at_risk_farms(
        danger_zones={
            "fire_id": fire_data.get("fire_id"),
            "danger_zone_6hr": fire_data.get("danger_zone") or (
                (fire_data.get("projected_perimeters")[-1] if isinstance(fire_data.get("projected_perimeters"), list) else None) and
                (fire_data.get("projected_perimeters")[-1]["geometry"])
            ),
        },
        farms=farms,
        farms_at_risk_hint=fire_data.get("farms_at_risk", []),
    )

    summary = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "fire_id": fire_data.get("fire_id"),
        "registered_farms": len(farms),
        "at_risk": len(at_risk),
        "alerts_sent": 0,
    }

    from contracts.loader import load_facilities as _load_fac
    facilities_data = {"facilities": _load_fac()}
    fire_snapshot = json.loads((ROOT / "data" / "fire_data.json").read_text())
    community = load_community_farms()
    at_risk_ids = {f["farm_id"] for f in at_risk}

    for farm in at_risk:
        hours = float(farm.get("hours_remaining") or 6.0)
        plan_url = f"https://wildfirewizards.io/plan/{farm['farm_id']}"
        neighbor_block = build_neighbor_awareness_text(
            farm,
            farms,
            at_risk_ids,
            community,
            radius_km=NEIGHBOR_RADIUS_KM,
        )
        send_alert(
            farm=farm,
            hours_remaining=hours,
            wind=fire_data.get("wind", {}),
            fire_origin=fire_data.get("origin", {}),
            plan_url=plan_url,
            neighbor_block=neighbor_block or None,
        )
        if send_plans:
            segments = generate_text_plan(
                farm,
                fire_snapshot,
                facilities_data,
                neighbor_block=neighbor_block or None,
            )
            send_text_plan(farm, segments)

        mark_alert_sent(farm["farm_id"], farm.get("fire_id", fire_data.get("fire_id", "unknown_fire")))
        summary["alerts_sent"] += 1

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="WildfireWizards alert system runner")
    parser.add_argument("--once", action="store_true", help="Run a single alert cycle and exit")
    parser.add_argument("--send-text-plan", action="store_true", help="Also send text-only plan segments")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    if args.once:
        summary = run_once(send_plans=args.send_text_plan)
        print(json.dumps(summary, indent=2))
        return 0

    print("WildfireWizards alert runner started (10-minute loop). Ctrl+C to stop.")
    while running:
        summary = run_once(send_plans=args.send_text_plan)
        print(json.dumps(summary))
        if not running:
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
