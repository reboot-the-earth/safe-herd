"""Test that the merged facility database is consistent.

This test fails on main (where two separate facility files exist with
conflicting IDs) and passes after the merge.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "modules"))
sys.path.insert(0, str(ROOT / "modules" / "facilities"))

from contracts.loader import load_facilities
from facilities.facility_matcher import load_facilities as matcher_load


def test_single_facility_source():
    """Both loaders return the same list."""
    contract_facs = load_facilities()
    matcher_facs = matcher_load()
    assert len(contract_facs) == len(matcher_facs)
    contract_ids = {f["id"] for f in contract_facs}
    matcher_ids = {f["id"] for f in matcher_facs}
    assert contract_ids == matcher_ids


def test_no_duplicate_ids():
    facs = load_facilities()
    ids = [f["id"] for f in facs]
    assert len(ids) == len(set(ids)), f"Duplicate IDs: {[i for i in ids if ids.count(i) > 1]}"


def test_routing_facility_ids_exist_in_matcher():
    """Every facility ID that routing can return also exists in the matcher results."""
    facs = load_facilities()
    all_ids = {f["id"] for f in facs}
    # The old data/facilities.json IDs should all map to something in the merged set
    old_data_ids = {"del_mar_fairgrounds", "ramona_rodeo_grounds", "bonsall_community",
                    "san_luis_rey", "valley_center_staging"}
    # All old IDs (or their merged equivalents) should be present
    for old_id in old_data_ids:
        matches = [fid for fid in all_ids if old_id.replace("_grounds", "") in fid or fid in old_id]
        assert len(matches) >= 1, f"Old ID {old_id} has no match in merged facilities"


def test_all_facilities_have_required_fields():
    facs = load_facilities()
    for f in facs:
        assert "id" in f, f"Missing id in {f.get('name', '?')}"
        assert "name" in f
        assert "lat" in f
        assert "lon" in f
        assert "accepts" in f
        assert "capacity" in f
        assert len(f["accepts"]) > 0, f"No species accepted at {f['id']}"


def test_old_modules_facilities_file_removed():
    old_path = ROOT / "modules" / "facilities" / "data" / "facilities.json"
    assert not old_path.exists(), "modules/facilities/data/facilities.json should be deleted"
