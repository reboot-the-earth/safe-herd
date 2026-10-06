# Safeherd

**Wildfire livestock evacuation system for San Diego County**

During the 2017 Lilac Fire, 46 horses died at San Luis Rey Training Center because evacuation was uncoordinated. Farmers didn't know which facilities had capacity, which roads were safe, or how to prioritize loading. WildfireWizards fixes that.

## What It Does

A farmer opens the app, drops a pin on their farm (or selects from at-risk farms), enters their animals and trailer info, and gets back:

- A countdown showing when fire reaches them
- A priority-ordered loading plan (which animals first, how to handle them)
- The best facility matched to their specific animals with live capacity
- Real road-following evacuation routes via OSRM that avoid fire zones
- A species-specific prep checklist
- A multilingual emergency chat assistant (English, Spanish, Chinese, Vietnamese, Tagalog, Korean)
- Neighbor awareness — who needs help, who can help
- Proactive SMS alerts for registered farms (Twilio / Textbelt / demo outbox)

## Architecture

Five independent modules communicate through JSON contracts. No module imports another directly. The React frontend calls all backend functions through a Flask API layer and stitches results together.

```
wildfire-wizards/
├── api.py                  Flask API — wraps each module's export function
├── config.json             Shared constants (bounding box, scenario, tuning)
├── requirements.txt        Python deps (flask, shapely, networkx, pytest)
├── data/                   Cached datasets (fire, facilities, community farms)
│
├── modules/
│   ├── fire_detection/     Fire spread prediction (Rothermel model)
│   │   ├── fire_spread.py        get_fire_data — perimeters + farms at risk
│   │   ├── firms_client.py       NASA FIRMS API client
│   │   ├── weather_client.py     NOAA weather integration
│   │   ├── fuel_lookup.py        LANDFIRE fuel type lookup
│   │   └── tests/                10 tests (spread rate, footprint, schema)
│   │
│   ├── routing/            Safe route engine
│   │   ├── route_engine.py       find_safe_routes — ranked routes as GeoJSON
│   │   ├── graph_loader.py       NetworkX road graph (OSM + demo)
│   │   ├── fire_overlay.py       Fire/smoke edge risk scoring
│   │   ├── trailer_filter.py     Trailer-friendly road weighting
│   │   └── tests/                12 tests (Hwy 76 blocked, smoke, trailers)
│   │
│   ├── facilities/         Facility matching & capacity
│   │   ├── facility_matcher.py   get_evacuation_match — scored facility list
│   │   ├── capacity_manager.py   Reservation TTL + snapshots
│   │   ├── trip_calculator.py    Multi-trip scheduling from trailer capacity
│   │   ├── data/                 facilities.json + reservations.json
│   │   └── tests/                8 tests (3-farm sequential matching)
│   │
│   ├── farmer_input/       Priority engine & checklists
│   │   ├── priority_engine.py    get_evacuation_plan — ordered loading plan
│   │   ├── checklist_generator.py Species-specific prep checklists
│   │   ├── demo_profiles.json    3 pre-loaded demo farm profiles
│   │   └── tests/                12 tests (priority order, triage, checklists)
│   │
│   └── alert_system/       Proactive SMS alerts
│       ├── alert_runner.py       Poll loop — fire watch → match → send
│       ├── farm_matcher.py       SQLite farm registry + geo matching
│       ├── sms_sender.py         Twilio / Textbelt / demo outbox
│       ├── plan_generator.py     SMS-sized text evacuation plans
│       ├── seed_farms.py         CLI to bootstrap farm DB
│       ├── inbound_demo.py       Simulate inbound SMS (PLAN/STOP)
│       └── tests/                18 tests (geometry, dedupe, DB, SMS)
│
└── frontend/               Vite + React + Tailwind
    ├── vite.config.js            Dev server on port 3000
    ├── tailwind.config.js        Coal/ember palettes, animations
    └── src/
        ├── App.jsx               Shell — state, API calls, layout
        ├── components/
        │   ├── map/
        │   │   ├── EvacMap.jsx           Leaflet map composition
        │   │   ├── UserPin.jsx           Draggable farm pin + pick mode
        │   │   ├── FarmMarkers.jsx       At-risk farm markers (synced with pin)
        │   │   ├── FacilityMarkers.jsx   Destination markers (green ✓ / orange ⚠ / red)
        │   │   ├── FireLayers.jsx        Heatmap + perimeters (leaflet.heat)
        │   │   ├── RouteOverlay.jsx      Route polylines with labels
        │   │   ├── WindOverlay.jsx       Wind direction visualization
        │   │   └── NeighborAwarenessMarkers.jsx
        │   ├── farm/
        │   │   ├── FarmInput.jsx         Location (address/ZIP/coords/pin/farm-select)
        │   │   ├── AnimalSelector.jsx    Species counts + special needs
        │   │   └── TrailerConfig.jsx     Trailer count/type
        │   ├── plan/
        │   │   ├── EvacuationPlan.jsx    Plan summary with grouped trips
        │   │   ├── TripCard.jsx          Per-trip card with species theming
        │   │   ├── Checklist.jsx         Species-specific checklist UI
        │   │   └── TriageWarning.jsx     Time-shortage warning
        │   ├── layout/
        │   │   ├── LeftSidebar.jsx       Step 1 — farm input + quick-load
        │   │   ├── RightSidebar.jsx      Step 2 — evacuation plan display
        │   │   ├── CountdownBanner.jsx   Fire countdown + stats
        │   │   └── ProjectFooter.jsx     Open data credits + submission link
        │   ├── chat/
        │   │   └── ChatPanel.jsx         Multilingual emergency assistant (6 languages)
        │   └── demo/
        │       └── DemoController.jsx    Guided walkthrough controller
        ├── data/                  Mock data for offline/demo mode
        ├── hooks/                 useCountdown, useDemoMode
        └── utils/
            ├── api.js             API client + OSRM road routing
            ├── geocode.js         ZIP lookup + Nominatim + reverse geocode
            └── formatTime.js      Time formatting
```

## Shared Contract

All modules agree on these:

| Item | Value |
|------|-------|
| Coordinate system | WGS84 (lat/lon) |
| Bounding box | `north: 33.51, south: 32.53, east: -116.08, west: -117.60` (San Diego County) |
| Demo scenario | 2017 Lilac Fire, Bonsall area. Three pre-loaded farms. Fire from east, Santa Ana winds. |
| Communication | Every module exposes ONE function: JSON in, JSON out |
| Integration | Frontend calls all four modules through Flask. No module imports another. |

## Key Features

### Interactive Map
- **Pin drop** — click the map to set farm location; "YOUR FARM" marker moves with it
- **Farm quick-select** — choose from at-risk farms in the fire zone
- **Road-following routes** — real driving paths via OSRM, not straight lines
- **Fire heatmap** — density visualization with animated hotspots and pulsing perimeters
- **Neighbor awareness** — see who needs help and who's offering nearby

### Multilingual Chat Assistant
Built-in emergency assistant supporting 6 languages with keyword matching for fire status, farm risk, shelters, neighbors, routes, checklists, and contacts. All data strings (help messages, alerts) are fully translated.

### Evacuation Planning
- **Priority engine** — pregnant/injured first, sedation-needed flagged, trailer batching
- **Species checklists** — tailored prep steps for horses, cattle, goats, sheep, poultry
- **Triage warnings** — alerts when available time is insufficient for full evacuation
- **Live capacity** — facilities show available space, risk level, and trailer access

### Alert System (SMS)
Background polling job that watches fire spread, identifies at-risk registered farms, and sends evacuation plans via SMS. Works offline once the message arrives.

## Tech Stack (All Open Source)

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite, Tailwind CSS, Framer Motion |
| Maps | Leaflet + react-leaflet, CartoDB Voyager tiles, leaflet.heat |
| Routing (map) | OSRM (Open Source Routing Machine) for road-following geometry |
| Fire data | NASA FIRMS API, NOAA Weather API, LANDFIRE, USGS DEM |
| Geospatial | Shapely, NetworkX (Dijkstra on weighted road graph) |
| Road data | OpenStreetMap via OSMnx |
| Geocoding | OpenStreetMap Nominatim (forward + reverse) |
| Database | SQLite (alert farm registry) + JSON files |
| Backend | Flask + flask-cors |
| SMS | Twilio / Textbelt / demo file outbox |

## Setup

```bash
git clone <repo-url>
cd wildfire-wizards

# Backend
pip install -r requirements.txt
python api.py                          # serves http://localhost:5001

# Frontend (separate terminal)
cd frontend
npm install
npm run dev                            # serves http://localhost:3000
```

Optional — pre-download heavy GIS datasets (modules fall back to demo data when absent):

```bash
python modules/fire_detection/download_data.py
python modules/routing/download_roads.py
```

Run the test suite (60 tests across all modules):

```bash
python -m pytest modules/ -q
```

### Alert system (proactive SMS)

```bash
# 1. Bootstrap the SQLite farm registry (3 demo farms)
python modules/alert_system/seed_farms.py

# 2. Run a single alert cycle
python modules/alert_system/alert_runner.py --once --send-text-plan

# 3. Continuous mode (10-minute poll loop; Ctrl+C to stop)
python modules/alert_system/alert_runner.py --send-text-plan
```

By default no Twilio/Textbelt credentials are set, so SMS bodies are written to `modules/alert_system/outbox/*.txt` and logged to `modules/alert_system/alerts.log` (JSONL). To enable real delivery set `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` + `TWILIO_PHONE_NUMBER`, or `TEXTBELT_KEY`. See [`modules/alert_system/README.md`](modules/alert_system/README.md) for the full env var list.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/health` | Reports which modules loaded |
| `GET`  | `/api/fire?live=true` | Fire perimeters + farms at risk |
| `GET`  | `/api/facilities` | Facility database with capacity |
| `POST` | `/api/routes` | Safe routes (`{farm_lat, farm_lon}`) |
| `POST` | `/api/plan` | Facility match + trip schedule |
| `GET`  | `/api/farmer-profiles` | 3 demo farm profiles |
| `POST` | `/api/farmer-plan` | Priority loading plan + checklist |

## Open Data Sources

| Source | What we use |
|--------|------------|
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) | Active fire detections (satellite hotspots) |
| [NOAA Weather](https://www.weather.gov/documentation/services-web-api) | Wind speed, humidity, temperature |
| [OpenStreetMap](https://www.openstreetmap.org/) | Road network + geocoding (Nominatim) |
| [LANDFIRE](https://landfire.gov/) | Fuel type data for fire spread modeling |
| [OSRM](https://project-osrm.org/) | Road-following route geometry |


## License

MIT
