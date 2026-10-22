"""
Capacity Manager — SQLite-backed hold system with retry-safe idempotency.

Holds go through a lifecycle:  held → confirmed | released | expired
Each hold is keyed by request_id for safe retries.
"""

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "capacity.db")
HOLD_TTL_SECONDS = 7200  # 120 minutes
MAX_OPEN_HOLDS_PER_FARM = 3
CAPACITY_BUFFER = 0.80


def _ensure_dir():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def _init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS holds (
            hold_id       TEXT PRIMARY KEY,
            request_id    TEXT NOT NULL UNIQUE,
            farm_id       TEXT NOT NULL,
            facility_id   TEXT NOT NULL,
            animals_json  TEXT NOT NULL,
            total_count   INTEGER NOT NULL,
            status        TEXT NOT NULL DEFAULT 'held',
            created_at    REAL NOT NULL,
            expires_at    REAL NOT NULL,
            confirmed_at  REAL,
            released_at   REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_holds_request ON holds(request_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_holds_fac ON holds(facility_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_holds_farm ON holds(farm_id, status)")


@contextmanager
def _connect():
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


def _expire_stale(conn: sqlite3.Connection):
    conn.execute(
        "UPDATE holds SET status = 'expired' WHERE status = 'held' AND expires_at <= ?",
        (time.time(),),
    )


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["animals"] = json.loads(d.pop("animals_json"))
    d["expires"] = datetime.fromtimestamp(d["expires_at"], tz=timezone.utc).isoformat()
    d["created"] = datetime.fromtimestamp(d["created_at"], tz=timezone.utc).isoformat()
    return d


def _species_reserved(conn: sqlite3.Connection, facility_id: str, species: str) -> int:
    """Sum of held counts for one species at one facility (call inside a txn)."""
    total = 0
    rows = conn.execute(
        "SELECT animals_json FROM holds WHERE facility_id = ? AND status = 'held'",
        (facility_id,),
    ).fetchall()
    for row in rows:
        animals = json.loads(row["animals_json"])
        total += animals.get(species, 0)
    return total


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_active_holds(facility_id: Optional[str] = None) -> list[dict]:
    with _connect() as conn:
        _expire_stale(conn)
        conn.commit()
        if facility_id:
            rows = conn.execute(
                "SELECT * FROM holds WHERE facility_id = ? AND status = 'held'",
                (facility_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM holds WHERE status = 'held'"
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_reserved_count(facility_id: str, species: str) -> int:
    with _connect() as conn:
        _expire_stale(conn)
        conn.commit()
        return _species_reserved(conn, facility_id, species)


def get_available_capacity(facility: dict, species: str) -> int:
    raw_cap = facility.get("capacity", {}).get(species, 0)
    buffered_cap = int(raw_cap * CAPACITY_BUFFER)
    reserved = get_reserved_count(facility["id"], species)
    return max(0, buffered_cap - reserved)


def get_capacity_snapshot(facility: dict) -> dict:
    snapshot = {}
    for species, raw_cap in facility.get("capacity", {}).items():
        buffered = int(raw_cap * CAPACITY_BUFFER)
        reserved = get_reserved_count(facility["id"], species)
        available = max(0, buffered - reserved)
        pct_full = round((reserved / buffered * 100) if buffered > 0 else 100, 1)
        snapshot[species] = {
            "total_listed": raw_cap,
            "buffered_total": buffered,
            "reserved": reserved,
            "available": available,
            "pct_full": pct_full,
        }
    return snapshot


# ---------------------------------------------------------------------------
# Hold lifecycle
# ---------------------------------------------------------------------------

def reserve_capacity(
    farm_id: str,
    facility_id: str,
    animals: dict[str, int],
    request_id: Optional[str] = None,
    facility: Optional[dict] = None,
) -> dict:
    """
    Create a hold for one or more species at a facility.

    If request_id was already used, returns the existing hold (idempotent retry).
    Raises ValueError on insufficient capacity or too many open holds.
    """
    if request_id is None:
        request_id = uuid.uuid4().hex

    if facility is None:
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from contracts.loader import load_facilities as _load_fac
        all_facilities = {fac["id"]: fac for fac in _load_fac()}
        facility = all_facilities.get(facility_id)

    if facility is None:
        raise ValueError(f"Unknown facility: {facility_id}")

    with _connect() as conn:
        _expire_stale(conn)

        existing = conn.execute(
            "SELECT * FROM holds WHERE request_id = ?", (request_id,)
        ).fetchone()
        if existing:
            conn.commit()
            return _row_to_dict(existing)

        open_count = conn.execute(
            "SELECT COUNT(*) AS c FROM holds WHERE farm_id = ? AND status = 'held'",
            (farm_id,),
        ).fetchone()["c"]
        if open_count >= MAX_OPEN_HOLDS_PER_FARM:
            conn.commit()
            raise ValueError(
                f"Farm {farm_id} already has {open_count} open holds "
                f"(max {MAX_OPEN_HOLDS_PER_FARM}). Confirm or release existing holds first."
            )

        for species, count in animals.items():
            raw_cap = facility.get("capacity", {}).get(species, 0)
            buffered_cap = int(raw_cap * CAPACITY_BUFFER)
            reserved = _species_reserved(conn, facility_id, species)
            available = max(0, buffered_cap - reserved)
            if count > available:
                conn.commit()
                raise ValueError(
                    f"Cannot reserve {count} {species} at {facility_id}: "
                    f"only {available} slots available."
                )

        now = time.time()
        hold_id = uuid.uuid4().hex

        conn.execute(
            "INSERT INTO holds (hold_id, request_id, farm_id, facility_id, "
            "animals_json, total_count, status, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'held', ?, ?)",
            (hold_id, request_id, farm_id, facility_id,
             json.dumps(animals), sum(animals.values()),
             now, now + HOLD_TTL_SECONDS),
        )
        conn.commit()

        return {
            "hold_id": hold_id,
            "request_id": request_id,
            "farm_id": farm_id,
            "facility_id": facility_id,
            "animals": animals,
            "total_count": sum(animals.values()),
            "status": "held",
            "created": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "expires": datetime.fromtimestamp(now + HOLD_TTL_SECONDS, tz=timezone.utc).isoformat(),
        }


def confirm_hold(hold_id: str) -> dict:
    with _connect() as conn:
        _expire_stale(conn)
        row = conn.execute("SELECT * FROM holds WHERE hold_id = ?", (hold_id,)).fetchone()
        if not row:
            conn.commit()
            raise ValueError(f"Hold {hold_id} not found")
        if row["status"] != "held":
            conn.commit()
            raise ValueError(f"Hold {hold_id} is '{row['status']}', cannot confirm")
        now = time.time()
        conn.execute(
            "UPDATE holds SET status = 'confirmed', confirmed_at = ? WHERE hold_id = ?",
            (now, hold_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM holds WHERE hold_id = ?", (hold_id,)).fetchone()
        return _row_to_dict(updated)


def release_hold(hold_id: str) -> dict:
    with _connect() as conn:
        _expire_stale(conn)
        row = conn.execute("SELECT * FROM holds WHERE hold_id = ?", (hold_id,)).fetchone()
        if not row:
            conn.commit()
            raise ValueError(f"Hold {hold_id} not found")
        if row["status"] in ("released", "expired"):
            conn.commit()
            raise ValueError(f"Hold {hold_id} is already '{row['status']}'")
        now = time.time()
        conn.execute(
            "UPDATE holds SET status = 'released', released_at = ? WHERE hold_id = ?",
            (now, hold_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM holds WHERE hold_id = ?", (hold_id,)).fetchone()
        return _row_to_dict(updated)


def get_hold(hold_id: str) -> Optional[dict]:
    with _connect() as conn:
        _expire_stale(conn)
        conn.commit()
        row = conn.execute("SELECT * FROM holds WHERE hold_id = ?", (hold_id,)).fetchone()
        return _row_to_dict(row) if row else None


def get_farm_holds(farm_id: str, status: Optional[str] = None) -> list[dict]:
    with _connect() as conn:
        _expire_stale(conn)
        conn.commit()
        if status:
            rows = conn.execute(
                "SELECT * FROM holds WHERE farm_id = ? AND status = ?",
                (farm_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM holds WHERE farm_id = ?", (farm_id,)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Backwards compat for facility_matcher.py
# ---------------------------------------------------------------------------

def get_active_reservations() -> list[dict]:
    return get_active_holds()


def release_reservation(reservation_id: str) -> bool:
    try:
        release_hold(reservation_id)
        return True
    except ValueError:
        return False


def reset_db():
    """Drop all holds. For tests only."""
    with _connect() as conn:
        conn.execute("DELETE FROM holds")
        conn.commit()


def cancel_farm_reservations(farm_id: str) -> int:
    holds = get_farm_holds(farm_id, status="held")
    released = 0
    for h in holds:
        try:
            release_hold(h["hold_id"])
            released += 1
        except ValueError:
            pass
    return released
