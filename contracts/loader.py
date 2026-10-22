"""Shared data loaders for contract-format files."""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_facilities() -> list[dict]:
    """Load the single merged facility list from data/facilities.json."""
    with open(DATA_DIR / "facilities.json") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data["facilities"]
    return data
