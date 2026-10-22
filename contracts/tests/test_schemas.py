"""Tests for contract schemas — one valid and one invalid example per schema."""

import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

CONTRACTS_ROOT = Path(__file__).resolve().parents[1]

# Add the repo root to the path so `from contracts import validate` works
import sys
sys.path.insert(0, str(CONTRACTS_ROOT.parent))

from contracts import validate

EXAMPLES_DIR = CONTRACTS_ROOT / "examples"

SCHEMAS = [
    "facility_card",
    "farm_profile",
    "fire_snapshot",
    "capacity_update",
    "capacity_hold_request",
    "capacity_hold_reply",
    "route_reply",
    "help_request",
]


@pytest.mark.parametrize("schema_name", SCHEMAS)
def test_valid_example_passes(schema_name):
    path = EXAMPLES_DIR / f"{schema_name}_valid.json"
    assert path.exists(), f"Missing valid example: {path}"
    with open(path) as f:
        obj = json.load(f)
    validate(schema_name, obj)


@pytest.mark.parametrize("schema_name", SCHEMAS)
def test_invalid_example_fails(schema_name):
    path = EXAMPLES_DIR / f"{schema_name}_invalid.json"
    assert path.exists(), f"Missing invalid example: {path}"
    with open(path) as f:
        obj = json.load(f)
    with pytest.raises(ValidationError):
        validate(schema_name, obj)
