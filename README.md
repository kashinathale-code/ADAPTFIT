# ADAPTFIT

> **"Right adaptation. Right place."**  
> A transparent, rules-based decision-support prototype evaluating whether a climate adaptation intervention proven at Location A can feasibly transfer to Location B.

---

## Overview

ADAPTFIT is a lightweight web application designed to assess the transferability of climate adaptation solutions (starting with urban **Rain Gardens**). Rather than using an opaque black-box model, ADAPTFIT uses an explicit, auditable rules engine that scores environmental factors, flags transfer risks, applies strict missing-data rules, and triggers critical-blocker overrides.

### Key Capabilities
- **4-Status Decision Engine:** Categorizes transferability into `Suitable`, `Conditional`, `Unsuitable`, or `Insufficient Data`.
- **Strict Data Missingness & Critical Blockers:** If a critical factor is unmet, the intervention is deemed `Unsuitable` regardless of other scores. If critical data is unknown or missing weight exceeds 30%, it reports `Insufficient Data`.
### Key Capabilities
- **4-Status Decision Engine:** Categorizes transferability into `Suitable`, `Conditional`, `Unsuitable`, or `Insufficient Data`.
- **Strict Data Missingness & Critical Blockers:** If a critical factor is unmet, the intervention is deemed `Unsuitable` regardless of other scores. If critical data is unknown or missing weight exceeds 30%, it reports `Insufficient Data`.
- **Interactive Leaflet Map (Self-Hosted):** Select Location A (proven reference site) and Location B (target prospective site) via self-hosted Leaflet 1.9.4 map pins, coordinates, or presets.
- **Place-Name Geocoding (FR-3):** OpenStreetMap Nominatim search with rate-limiting, custom User-Agent, and persistent SQLite caching.
- **Multi-Target Comparison (FR-11):** Compare 1 reference site against up to 5 candidate targets simultaneously, ranked primarily by status and secondarily by compatibility score.
- **PDF Report Export (FR-12):** Download publication-ready, self-contained feasibility briefs directly from the results page.
- **Assessment Audit History (FR-10):** Filterable audit log of historical assessments with pagination.
- **Verified Engineering Citations:** Rain garden thresholds backed by authoritative sources (CPHEEO 2019, US EPA, CIRIA C753).
- **Data Quality & Uncertainty Warnings:** Prominently communicates NASA POWER regional grid constraints (~50 km) and proxy soil caveats.
- **Zero Secrets & Resilient Deployment:** Free of committed secrets and engineered to auto-seed its SQLite database on container startup for cloud platforms like Render.

---

## Architecture & Tech Stack

| Layer | Technology | Role |
|---|---|---|
| **Frontend** | HTML5, Vanilla CSS3, JavaScript | Responsive UI (375px+ mobile ready), factor tables, score badges |
| **Map** | Leaflet 1.9.4 (Self-hosted) | OpenStreetMap tiles, interactive markers, location selection |
| **Backend** | Python 3.11+, Flask | REST API, input validation, geocoding proxy, PDF generation |
| **Compatibility Engine** | Pure Python | Rules-based scoring, transfer tolerances, decision trees |
| **Database** | SQLite 3 | Interventions, candidate rules, geocoding cache, assessment history |
| **PDF Generation** | ReportLab | Publication-quality vector PDF feasibility reports (FR-12) |
| **Geocoding** | Nominatim (OSM) | Place search with caching and 1 req/s rate-limiting |
| **Data Processing** | Pandas, NumPy | Data cleaning, units conversion, distance calculations |
| **Testing** | pytest (151 tests) | Unit and integration test suite across engine, API, and live adapters |
| **Deployment** | Gunicorn / Render | Production WSGI server with concurrency guards |

### Directory Structure
```
ADAPTFIT/
├── app.py                      # Flask application factory and route registration
├── config.py                   # Environment configuration & threshold constants
├── run_live.ps1                # PowerShell launcher for live environmental APIs
├── Procfile                    # Render/Heroku start command (web: gunicorn --workers 1 app:app)
├── requirements.txt            # Production pinned dependencies (Flask, ReportLab, etc.)
├── requirements-dev.txt        # Development dependencies (includes pytest)
├── .python-version             # Python 3.11.9 runtime pin for cloud platforms
├── README.md                   # Setup, usage, and architectural documentation
├── .gitignore                  # Git exclusions (.env, *.db, __pycache__, .venv)
├── docs/
│   ├── DEMO_RESULTS.md         # Live API empirical results for 4 demo pairs
│   └── SOURCES.md              # Real engineering citations and source URLs
├── backend/
│   ├── routes.py               # REST API endpoints (adaptations, assessments, comparisons, pdf)
│   ├── compatibility_engine.py # Decision rules, tolerance checking, scoring
│   ├── data_fetcher.py         # Environmental adapters (NASA POWER, Copernicus, SoilGrids, Overpass)
│   ├── data_processor.py       # Input sanitation, coordinate validation, warnings
│   ├── gis_processor.py        # GIS slope calculation & spatial utilities
│   └── pdf_exporter.py         # ReportLab PDF report generator (FR-12)
├── database/
│   ├── schema.sql              # SQLite DDL schema with geocoding_cache table
│   ├── seed.py                 # Seed script with mutex lock & busy timeout for multi-workers
│   └── adaptfit.db             # SQLite database (auto-generated)
├── datasets/
│   └── sample_environmental_data.csv # Demo environmental profiles for 5 Maharashtra sites
├── frontend/
│   ├── templates/              # Jinja2 templates (index, assessment, results, history, compare)
│   └── static/
│       ├── css/style.css       # Clean, modern stylesheet with 375px mobile responsiveness
│       ├── vendor/leaflet/     # Self-hosted Leaflet 1.9.4 CSS/JS and marker assets
│       └── js/
│           ├── assessment.js   # Leaflet map, geocoding, preset picker, API submission
│           └── results.js      # Results rendering, factor comparison, badges, PDF hook
└── tests/
    ├── conftest.py             # Shared fixtures and isolated temp database
    ├── test_compatibility.py   # Compatibility engine unit tests (43 test cases)
    ├── test_data.py            # Data fetching, distance, resolution, and validation tests
    ├── test_api.py             # Flask API endpoints, comparisons, PDF export, auto-seed tests
    ├── test_nasa_power.py      # NASA POWER rainfall API tests
    ├── test_osm.py             # OSM Overpass building and green space tests
    ├── test_slope.py           # Copernicus DEM slope calculation tests
    └── test_soilgrids.py       # SoilGrids pedotransfer function tests
```

---

## Setup & Local Installation

### Prerequisites
- **Python 3.11+** installed on your system.
- **Git** version control.

### 1. Clone the Repository
```bash
git clone <repository-url>
cd ADAPTFIT
```

### 2. Create and Activate a Virtual Environment
- **On Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  ```
- **On macOS / Linux:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Database Setup (Auto-Seeding)
The database auto-seeds automatically upon running the application if `database/adaptfit.db` is missing or uninitialized.

To manually seed or reset the database at any time:
```bash
python database/seed.py

# To force overwrite an existing database:
python database/seed.py --force
```

---

## Running the Application

### Local Development Server (Flask)
```bash
python app.py
```
Open your browser and navigate to:
```
http://localhost:5000
```

### Production Server (Gunicorn)
To run with Gunicorn locally (Linux / macOS / WSL) or in production:
```bash
gunicorn app:app
```
### Running with Live Environmental APIs (PowerShell)
To fetch live data directly from external APIs (NASA POWER rainfall, OpenTopography Copernicus 30m DEM slope, SoilGrids pedotransfer function, and OSM Overpass green spaces):
```powershell
./run_live.ps1
```
This script sets `USE_LIVE_RAINFALL=true`, `USE_LIVE_SLOPE=true`, `USE_LIVE_SOIL=true`, `USE_LIVE_OSM=true` and starts the app. If any external API fails or times out, ADAPTFIT falls back gracefully to the nearest sample location data.

### Production Server (Gunicorn)
To run with Gunicorn locally or in production:
```bash
gunicorn --workers 1 app:app
```
> **Note on Workers:** For cloud platforms using SQLite, running with `--workers 1` is recommended to prevent multi-process database file contention. ADAPTFIT also includes SQLite `PRAGMA busy_timeout = 30000` and file lock guards in `database/seed.py` for resilience across process spawns.

---

## Running Tests

ADAPTFIT includes a comprehensive test suite across the engine, API, live adapters, geocoding, multi-target comparisons, and PDF export:
```bash
# Install development dependencies (includes pytest)
pip install -r requirements-dev.txt

# Run the full test suite
python -m pytest
```
Run with verbose output:
```bash
python -m pytest -v
```

### Test Scope (151 Tests)
- `tests/test_compatibility.py`: 43 unit tests covering the compatibility engine, all 4 status outcomes, transfer tolerance checks, critical blockers, and missingness rules.
- `tests/test_data.py`: Tests Haversine distance, coordinate boundaries, CSV loading, data cleaning, numerical resolution parsing, and metadata warnings.
- `tests/test_api.py`: Integration tests for `/api/adaptations`, `/api/location-data`, `/api/assessments`, historical audit log (`/api/assessments`), Nominatim geocoding (`/api/geocode`), multi-target comparison (`/api/comparisons`), PDF report generation (`/api/assessments/<id>/pdf`), and startup database auto-seeding.
- `tests/test_nasa_power.py`: Tests for NASA POWER rainfall API fetching, aggregation, and error handling.
- `tests/test_osm.py`: Tests for OpenStreetMap Overpass building distance and open space extraction.
- `tests/test_slope.py`: Tests for Copernicus 30m DEM slope calculation in `backend/gis_processor.py`.
- `tests/test_soilgrids.py`: Tests for SoilGrids sand/silt/clay retrieval and Saxton-Rawls pedotransfer function.

---

## Deployment (Render)

This repository is pre-configured for one-click deployment on [Render](https://render.com).

### Render Configuration
1. **New Web Service:** Connect your Git repository.
2. **Environment:** `Python 3` (Render respects `.python-version` set to `3.11.9`).
3. **Build Command:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Start Command:**
   ```bash
   gunicorn --workers 1 app:app
   ```
   *(Render also detects the included `Procfile` containing `web: gunicorn --workers 1 app:app` automatically).*

### Ephemeral Filesystem & Auto-Seeding
Render's free tier spins down containers after inactivity and uses an ephemeral filesystem. On container boot, `app.py` checks for `database/adaptfit.db`. If missing or empty, it automatically executes `database/seed.py`, creating the tables and inserting the seed rules before serving requests.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `5000` | Port for the HTTP server |
| `DATABASE_PATH` | `database/adaptfit.db` | Path to the SQLite database file |
| `SUITABLE_MIN` | `0.75` | Minimum score threshold for `Suitable` status |
| `MAX_MISSING_WEIGHT` | `0.30` | Maximum missing factor weight before status becomes `insufficient_data` |
| `USE_LIVE_RAINFALL` | `false` | Enable live NASA POWER 0.5-degree annual rainfall API |
| `USE_LIVE_SLOPE` | `false` | Enable live Copernicus 30m DEM ground slope calculation |
| `USE_LIVE_SOIL` | `false` | Enable live SoilGrids sand/silt/clay pedotransfer function |
| `USE_LIVE_OSM` | `false` | Enable live OpenStreetMap Overpass building distance & green space queries |
| `FLASK_DEBUG` | `false` | Enable Flask debug mode (`true` / `false`) |
| `SECRET_KEY` | `change-me-in-production` | Secret key for session security |

*(Note: Unused legacy variables `NASA_POWER_API_KEY` and `SOILGRIDS_API_KEY` have been completely removed as both upstream APIs are public and do not require API keys).*

---

## Demonstrating the Four Assessment Statuses

ADAPTFIT comes with built-in sample locations in Western Maharashtra (`datasets/sample_environmental_data.csv`) and one-click override presets to demonstrate every engine outcome in under a minute (documented in detail in `docs/DEMO_RESULTS.md`):

1. **Suitable (Green):**
   - **Reference (A):** Pune city (`18.5204, 73.8567`)
   - **Target (B):** Pimpri (`18.6298, 73.7997`)
   - *Outcome:* Infiltration (25 mm/hr) and slope (0.7% in live Copernicus DEM) satisfy requirements, and rainfall is within transfer tolerance. Overall score `1.0`.
2. **Conditional (Amber - Non-Critical Limitation / Transfer Risk):**
   - **Reference (A):** Pune city (`18.5204, 73.8567`)
   - **Target (B):** Nashik city (`19.9975, 73.7898`)
   - *Outcome:* Open space indicator is 0 (absent from OSM query), which is a non-critical factor (weight 0.15). Status is `Conditional` (score `0.85`), requiring on-site spatial survey.
   - *Note on Niphad:* When live APIs are active, Pune $\rightarrow$ Niphad (`20.0800, 74.1100`) also produces `Conditional` (score `1.0`) because live NASA POWER rainfall differs significantly (858.3 vs 1731.3 mm/yr, $>30\%$ transfer tolerance).
3. **Unsuitable (Red - Critical Blocker):**
   - **Live API mode:** Pune $\rightarrow$ Lonavala (`18.7557, 73.4091`) where real SoilGrids fetch at 5-15cm depth measures 41% clay, translating to $K_s = 0.3\text{ mm/hr}$ via Rawls et al. (1983). Because 0.3 mm/hr is well below the critical minimum of 12.7 mm/hr, the engine triggers the Critical Blocker Override to `Unsuitable`.
   - **Static CSV mode:** Pune $\rightarrow$ Niphad where CSV slope is 12.0%, exceeding the critical maximum of 8.0%.
   - **Override panel:** Click **"Unsuitable (Blocker)"** (simulates slope = 14.5%) to demo this status on demand.
4. **Insufficient Data (Grey - Missingness Rule):**
   - **Static CSV mode:** Pune $\rightarrow$ Lonavala where soil infiltration is NULL in the sample CSV. Because infiltration is a critical factor (weight 0.35 > 0.30 threshold), status is `Insufficient Data`.
   - **Override panel:** Click **"Insufficient Data (Missing)"** to demo missing critical factor handling on demand.

---

## Architectural & TRD/PRD Alignment

1. **Slope Calculation in `gis_processor.py`:** Moved 9-point finite difference DEM slope calculation from `data_fetcher.py` into `backend/gis_processor.py` for clean separation of data retrieval and geospatial math.
2. **Pedotransfer Soil Infiltration Proxy:** SoilGrids API returns physical texture fractions (sand, silt, clay %). Saturated hydraulic conductivity ($K_{sat}$) is computed using the empirical Saxton & Rawls (2006) pedotransfer equation and labeled as "Estimated (proxy)".
3. **Geocoding via Nominatim:** Implemented on `/api/geocode` with an explicit, compliant User-Agent (`ADAPTFIT-ClimateAdaptation/1.0`), server-side 1 req/s rate-limiting, and persistent SQLite caching in the `geocoding_cache` table.
4. **Multi-Target Comparison (FR-11):** Implemented on `/api/comparisons` allowing 1 reference site and 1-5 candidate targets. Evaluates all targets and ranks them by status priority (`Suitable` $\rightarrow$ `Conditional` $\rightarrow$ `Insufficient Data` $\rightarrow$ `Unsuitable`), then score descending.
5. **Self-Hosted Leaflet Assets:** Leaflet 1.9.4 CSS, JavaScript, and marker icon assets are bundled locally in `frontend/static/vendor/leaflet/` to eliminate external CDN dependencies. System font fallbacks ensure UI readability even if Google Fonts fail.

---

## Known Limitations

1. **0.5-Degree Regional Rainfall Grid:** NASA POWER provides rainfall on a $\sim 0.5^\circ \times 0.5^\circ$ grid ($\sim 50\text{ km} \times 50\text{ km}$ at tropical latitudes). While suitable for general climatological context, it does not capture local microclimates or convective cloudburst events. This constraint is explicitly flagged in UI warnings and PDF reports.
2. **Proxy Soil Infiltration Data:** Global SoilGrids provides estimated texture at 250m resolution. Saturated hydraulic conductivity is derived via pedotransfer equations rather than direct field measurements. Prior to actual engineering construction, on-site double-ring infiltrometer testing is mandatory.
3. **OpenStreetMap Data Density:** Open space and building polygon distance calculations depend on OpenStreetMap volunteer mapping completeness in India. Unmapped buildings or parks may return default/missing values.
4. **Candidate Starter Rules:** Rain Garden starter rules are derived from municipal stormwater standards (CPHEEO 2019, US EPA, CIRIA C753). While grounded in engineering literature, local geotechnical codes, water table depths, and municipal bylaws must be verified before civil works.

---

## Compliance & Disclaimer

- **Candidate, Unverified Criteria:** All Rain Garden rules are candidate criteria based on preliminary stormwater design guidance. They are explicitly labelled as `"candidate, unverified"` in both the API and UI.
- **Preliminary Screening:** ADAPTFIT outputs are preliminary screening indicators and do **not** represent an engineering guarantee of project success.
- **Site Survey Prerequisite:** On-site infiltration tests (double-ring infiltrometer) and topographical surveys must be conducted before design or capital allocation.
- **Security:** No secrets or credentials are stored in this repository. `.env`, SQLite databases (`*.db`), and Python cache files are strictly excluded via `.gitignore`.

