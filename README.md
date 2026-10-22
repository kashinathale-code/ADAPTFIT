# ADAPTFIT

> **"Right adaptation. Right place."**  
> A transparent, rules-based decision-support prototype evaluating whether a climate adaptation intervention proven at Location A can feasibly transfer to Location B.

---

## Overview

ADAPTFIT is a lightweight web application designed to assess the transferability of climate adaptation solutions (starting with urban **Rain Gardens**). Rather than using an opaque black-box model, ADAPTFIT uses an explicit, auditable rules engine that scores environmental factors, flags transfer risks, applies strict missing-data rules, and triggers critical-blocker overrides.

### Key Capabilities
- **4-Status Decision Engine:** Categorizes transferability into `Suitable`, `Conditional`, `Unsuitable`, or `Insufficient Data`.
- **Strict Data Missingness & Critical Blockers:** If a critical factor is unmet, the intervention is deemed `Unsuitable` regardless of other scores. If critical data is unknown or missing weight exceeds 30%, it reports `Insufficient Data`.
- **Interactive Leaflet Map:** Select Location A (proven reference site) and Location B (target prospective site) via interactive map pins, coordinates, or presets.
- **Factor Breakdown & Explanations:** Every factor displays its reference value, target value, threshold requirements, transfer risk flag, data source, resolution, and plain-language interpretation.
- **Data Quality & Uncertainty Warnings:** Prominently communicates resolution constraints and preliminary demo data caveats.
- **Zero Secrets & Resilient Deployment:** Free of committed secrets and engineered to auto-seed its SQLite database on container startup for cloud platforms like Render.

---

## Architecture & Tech Stack

| Layer | Technology | Role |
|---|---|---|
| **Frontend** | HTML5, Vanilla CSS3, JavaScript | Responsive UI, factor tables, score badges |
| **Map** | Leaflet.js | OpenStreetMap tiles, interactive markers, location selection |
| **Backend** | Python 3.11+, Flask | REST API, input validation, orchestration |
| **Compatibility Engine** | Pure Python | Rules-based scoring, transfer tolerances, decision trees |
| **Database** | SQLite 3 | Interventions, candidate rules, assessment audit history |
| **Data Processing** | Pandas, NumPy | Data cleaning, units conversion, distance calculations |
| **Testing** | pytest | Unit and integration test suite (65 tests) |
| **Deployment** | Gunicorn / Render | Production WSGI server and cloud deployment |

### Directory Structure
```
ADAPTFIT/
├── app.py                      # Flask application factory and route registration
├── config.py                   # Environment configuration & threshold constants
├── Procfile                    # Render/Heroku start command (web: gunicorn app:app)
├── requirements.txt            # Pinned project dependencies
├── README.md                   # Setup, usage, and architectural documentation
├── .gitignore                  # Git exclusions (.env, *.db, __pycache__)
├── backend/
│   ├── routes.py               # REST API endpoints (/api/adaptations, /api/assessments)
│   ├── compatibility_engine.py # Decision rules, tolerance checking, scoring
│   ├── data_fetcher.py         # CSV & external data adapter, Haversine lookup
│   ├── data_processor.py       # Input sanitation, coordinate validation, warnings
│   └── gis_processor.py        # GIS/coordinate utilities
├── database/
│   ├── schema.sql              # SQLite DDL schema
│   ├── seed.py                 # Seed script for Rain Garden rules & criteria
│   └── adaptfit.db             # SQLite database (auto-generated)
├── datasets/
│   └── sample_environmental_data.csv # Demo environmental profiles for 5 sites
├── frontend/
│   ├── templates/              # Jinja2 templates (index.html, assessment.html, results.html)
│   └── static/
│       ├── css/style.css       # Clean, modern stylesheet
│       └── js/
│           ├── assessment.js   # Leaflet map, preset picker, API submission
│           └── results.js      # Results rendering, factor comparison, badges
└── tests/
    ├── test_compatibility.py   # Compatibility engine unit tests (43 test cases)
    ├── test_data.py            # Data fetching, distance, and validation tests
    └── test_api.py             # Flask API endpoints, DB, and auto-seed tests
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
By default, Gunicorn binds to `0.0.0.0:8000` or `$PORT` if defined.

---

## Running Tests

ADAPTFIT includes comprehensive test coverage across all modules:
```bash
python -m pytest
```
Run with verbose output:
```bash
python -m pytest -v
```

### Test Scope
- `tests/test_compatibility.py`: 43 unit tests covering the compatibility engine, all status outcomes, transfer tolerance checks, critical blockers, and missingness rules.
- `tests/test_data.py`: Tests Haversine distance calculation, coordinate boundaries, CSV loading, data cleaning, and metadata warnings.
- `tests/test_api.py`: Integration tests for `/api/adaptations`, `/api/location-data`, `/api/assessments`, UI routes, and **startup database auto-seeding**.

---

## Deployment (Render)

This repository is pre-configured for one-click deployment on [Render](https://render.com).

### Render Configuration
1. **New Web Service:** Connect your Git repository.
2. **Environment:** `Python 3`
3. **Build Command:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Start Command:**
   ```bash
   gunicorn app:app
   ```
   *(Render also detects the included `Procfile` containing `web: gunicorn app:app` automatically).*

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
| `FLASK_DEBUG` | `false` | Enable Flask debug mode (`true` / `false`) |
| `SECRET_KEY` | `change-me-in-production` | Secret key for session security |

---

## Demonstrating the Four Assessment Statuses

ADAPTFIT comes with built-in sample locations in Western Maharashtra (`datasets/sample_environmental_data.csv`) and one-click override presets to demonstrate every engine outcome in under a minute (documented in detail in `docs/DEMO_RESULTS.md`):

1. **Suitable (Green):**
   - **Reference (A):** Pune city (`18.5204, 73.8567`)
   - **Target (B):** Pimpri (`18.6298, 73.7997`)
   - *Outcome:* Infiltration (25 mm/hr) and slope (2% in CSV, 0.7% in live DEM) satisfy requirements, and rainfall is within transfer tolerance. Overall score $\ge 0.75$.
2. **Unsuitable (Red - Critical Blocker):**
   - **Static CSV mode:** Pune $\rightarrow$ Niphad (`20.0800, 74.1100`) where CSV slope is 12%, exceeding the critical maximum of 8.0%. Critical blocker triggers immediate `Unsuitable` status.
   - **Override panel:** Click **"Unsuitable (Blocker)"** (simulates slope = 14.5%) to demo this status on demand.
3. **Insufficient Data (Grey - Missingness Rule):**
   - **Reference (A):** Pune city (`18.5204, 73.8567`)
   - **Target (B):** Lonavala (`18.7557, 73.4091`)
   - *Outcome:* Soil infiltration is NULL / unmeasured. Because infiltration is a critical factor (weight 0.35 > 0.30 threshold), status is immediately `Insufficient Data`.
   - **Override panel:** Click **"Insufficient Data (Missing)"** to demo missing critical factor handling.
4. **Conditional (Amber - Non-Critical Limitation / Transfer Risk):**
   - **Reference (A):** Pune city (`18.5204, 73.8567`)
   - **Target (B):** Nashik city (`19.9975, 73.7898`)
   - *Outcome:* Open space indicator is 0 (absent), which is a non-critical factor (weight 0.15). Condition requires on-site spatial survey before implementation.
   - *Note on Live APIs:* When live APIs are active (`run_live.ps1`), Pune $\rightarrow$ Niphad also produces `Conditional` because NASA POWER rainfall differs significantly (858 vs 1731 mm/yr, $>30\%$ transfer tolerance).
   - **Override panel:** Click **"Conditional (Survey/Risk)"** to demo non-critical missingness or transfer risk on demand.

---

## Compliance & Disclaimer

- **Candidate, Unverified Criteria:** All Rain Garden rules are candidate criteria based on preliminary stormwater design guidance. They are explicitly labelled as `"candidate, unverified"` in both the API and UI.
- **Preliminary Screening:** ADAPTFIT outputs are preliminary screening indicators and do **not** represent an engineering guarantee of project success.
- **Site Survey Prerequisite:** On-site infiltration tests (double-ring infiltrometer) and topographical surveys must be conducted before design or capital allocation.
- **Security:** No secrets or credentials are stored in this repository. `.env`, SQLite databases (`*.db`), and Python cache files are strictly excluded via `.gitignore`.
