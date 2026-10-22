# Contributing to Safeherd

Thanks for your interest in contributing! This guide covers the basics.

## Setup

```bash
# Clone and install
git clone https://github.com/reboot-the-earth/wildfire-wizards.git
cd wildfire-wizards
pip install -r requirements.txt

# Frontend
cd frontend
npm ci
```

## Branch naming

Use `<type>/<short-description>`, for example:

- `fix/hold-expiry-race`
- `feat/multi-species-holds`
- `docs/update-contributing`

## Running tests

```bash
# All backend tests
python -m pytest contracts/tests/ modules/facilities/tests/ -v

# Frontend build check
cd frontend && npm run build
```

## Pull request guidelines

1. One logical change per PR.
2. Include tests for new behavior.
3. Keep the PR description concise: what changed and why.
4. All CI checks must pass before merging.

## Code style

- Python: follow PEP 8, use type hints for public functions.
- JavaScript/React: follow the existing ESLint config in `frontend/`.
- No trailing whitespace; files end with a single newline.

## File ownership (GSoC Phase 0)

During Phase 0, files are split between contributors:

- **Person A**: `contracts/`, `modules/facilities/`, `data/facilities.json`, `.github/workflows/`, policy files
- **Person B**: `agents/`, `frontend/`, `modules/routing/`, `modules/fire_detection/`, `modules/farmer_input/`, `modules/alert_system/`

Coordinate before touching files outside your area.
