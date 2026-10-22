"""Tests for the SQLite-backed capacity hold system."""

import os
import sys
import time
import threading
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "modules", "facilities"))

import capacity_manager as cm


FACILITY = {
    "id": "test_fac",
    "name": "Test Facility",
    "lat": 33.0,
    "lon": -117.0,
    "capacity": {"cattle": 100, "horses": 20},
    "accepts": ["cattle", "horses"],
}


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db = str(tmp_path / "capacity.db")
    monkeypatch.setattr(cm, "DB_PATH", db)
    yield db


def test_idempotent_retry():
    """Same request_id returns the same hold, not a duplicate."""
    h1 = cm.reserve_capacity("farm_a", "test_fac", {"cattle": 10}, request_id="req-1", facility=FACILITY)
    h2 = cm.reserve_capacity("farm_a", "test_fac", {"cattle": 10}, request_id="req-1", facility=FACILITY)
    assert h1["hold_id"] == h2["hold_id"]
    assert len(cm.get_active_holds("test_fac")) == 1


def test_hold_confirm_release_lifecycle():
    h = cm.reserve_capacity("farm_a", "test_fac", {"cattle": 5}, facility=FACILITY)
    assert h["status"] == "held"

    confirmed = cm.confirm_hold(h["hold_id"])
    assert confirmed["status"] == "confirmed"

    released = cm.release_hold(h["hold_id"])
    assert released["status"] == "released"


def test_insufficient_capacity():
    buffered = int(100 * cm.CAPACITY_BUFFER)  # 80
    with pytest.raises(ValueError, match="only"):
        cm.reserve_capacity("farm_a", "test_fac", {"cattle": buffered + 1}, facility=FACILITY)


def test_multi_species_hold():
    h = cm.reserve_capacity("farm_a", "test_fac", {"cattle": 10, "horses": 5}, facility=FACILITY)
    assert h["animals"] == {"cattle": 10, "horses": 5}
    assert h["total_count"] == 15
    assert cm.get_reserved_count("test_fac", "cattle") == 10
    assert cm.get_reserved_count("test_fac", "horses") == 5


def test_max_open_holds_per_farm():
    for i in range(cm.MAX_OPEN_HOLDS_PER_FARM):
        cm.reserve_capacity(
            "farm_a", "test_fac", {"cattle": 1},
            request_id=f"req-{i}", facility=FACILITY,
        )
    with pytest.raises(ValueError, match="open holds"):
        cm.reserve_capacity("farm_a", "test_fac", {"cattle": 1}, facility=FACILITY)


def test_expiry(monkeypatch):
    h = cm.reserve_capacity("farm_a", "test_fac", {"cattle": 10}, facility=FACILITY)
    assert cm.get_reserved_count("test_fac", "cattle") == 10

    future = time.time() + cm.HOLD_TTL_SECONDS + 1
    monkeypatch.setattr(time, "time", lambda: future)

    assert cm.get_reserved_count("test_fac", "cattle") == 0
    hold = cm.get_hold(h["hold_id"])
    assert hold["status"] == "expired"


def test_concurrent_last_slots():
    """Two threads race for the last 5 slots — exactly one wins."""
    buffered = int(100 * cm.CAPACITY_BUFFER)  # 80
    cm.reserve_capacity("farm_pre", "test_fac", {"cattle": buffered - 5}, request_id="pre", facility=FACILITY)

    results = {"wins": 0, "losses": 0}
    lock = threading.Lock()

    def try_reserve(rid):
        try:
            cm.reserve_capacity("farm_x", "test_fac", {"cattle": 5}, request_id=rid, facility=FACILITY)
            with lock:
                results["wins"] += 1
        except ValueError:
            with lock:
                results["losses"] += 1

    t1 = threading.Thread(target=try_reserve, args=("race-1",))
    t2 = threading.Thread(target=try_reserve, args=("race-2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["wins"] == 1
    assert results["losses"] == 1


def test_release_frees_capacity():
    h = cm.reserve_capacity("farm_a", "test_fac", {"cattle": 10}, facility=FACILITY)
    assert cm.get_reserved_count("test_fac", "cattle") == 10
    cm.release_hold(h["hold_id"])
    assert cm.get_reserved_count("test_fac", "cattle") == 0


def test_capacity_snapshot():
    cm.reserve_capacity("farm_a", "test_fac", {"cattle": 20}, facility=FACILITY)
    snap = cm.get_capacity_snapshot(FACILITY)
    assert snap["cattle"]["reserved"] == 20
    assert snap["cattle"]["available"] == int(100 * cm.CAPACITY_BUFFER) - 20
