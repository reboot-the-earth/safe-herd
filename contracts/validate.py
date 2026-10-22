"""Schema validation against contracts/schemas/*.json."""

import json
from pathlib import Path

import jsonschema

SCHEMAS_DIR = Path(__file__).parent / "schemas"

_cache: dict[str, dict] = {}


def _load_schema(kind: str) -> dict:
    if kind not in _cache:
        path = SCHEMAS_DIR / f"{kind}.json"
        if not path.exists():
            raise ValueError(f"Unknown schema kind: {kind!r}. Available: {[p.stem for p in SCHEMAS_DIR.glob('*.json')]}")
        with open(path) as f:
            _cache[kind] = json.load(f)
    return _cache[kind]


def validate(kind: str, obj: dict) -> None:
    """Validate *obj* against the named schema. Raises jsonschema.ValidationError on failure."""
    schema = _load_schema(kind)
    jsonschema.validate(instance=obj, schema=schema)
