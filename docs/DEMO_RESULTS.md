# ADAPTFIT Demo Scenarios Verification Results

This document records the empirical results of running the four primary Maharashtra demonstration pairs through the ADAPTFIT API under live flags (`USE_LIVE_RAINFALL=true`, `USE_LIVE_SLOPE=true`, `USE_LIVE_SOIL=true`, `USE_LIVE_OSM=true`).

Evaluated Adaptation: **Rain Garden** (`rain_garden`)  
Engine Configuration: `SUITABLE_MIN = 0.75`, `MAX_MISSING_WEIGHT = 0.30`

---

## Summary of Results

| Pair | Reference (A) | Target (B) | Live Status | Score | Primary Deciding Factor(s) | Provenance & Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | Pune City | Pimpri | **Suitable** | `1.0` | All factors met; no transfer risks | High compatibility across all dimensions. |
| **2** | Pune City | Niphad | **Conditional** | `1.0` | `annual_rainfall` transfer risk (858.3 vs 1731.3 mm/yr, >30% delta) | Live Copernicus DEM measures slope as 1.4% (met). Rainfall divergence (rain shadow) triggers transfer risk. |
| **3** | Pune City | Lonavala | **Unsuitable** | `0.66` | `soil_infiltration` critical blocker (0.3 mm/hr < 12.7 mm/hr min) & rainfall > 2500 mm/yr | Soil infiltration (0.3 mm/hr) is a **real fetch** from SoilGrids v2.0 (41% clay $\rightarrow$ Rawls table $K_s = 0.3$ mm/hr). Unlined rain gardens cannot drain without underdrains. |
| **4** | Pune City | Nashik City | **Conditional** | `0.85` | `open_space` unmet (0 vs required present) | Non-critical factor unmet in urban core; requires site spatial survey. |

---

## Detailed Scenario Breakdown (Live Mode)

### Scenario 1: Pune City $\rightarrow$ Pimpri
- **Reference Location:** Pune City (`18.5204, 73.8567`)
- **Target Location:** Pimpri (`18.6298, 73.7997`)
- **Overall Status:** `suitable`
- **Overall Compatibility Score:** `1.0` (100%)
- **Data Provenance:**
  - `annual_rainfall`: Ref = 1731.3 mm/yr, Target = 1731.3 mm/yr (`Live: NASA POWER`) $\rightarrow$ **Met** (600–2500 mm/yr)
  - `slope`: Ref = 3.0%, Target = 0.7% (`Live: Open-Meteo Copernicus DEM`) $\rightarrow$ **Met** (Max 8.0%)
  - `soil_infiltration`: Ref = 22.0 mm/hr, Target = 25.0 mm/hr (`Demo value`, SoilGrids unmeasured in urban sealed core) $\rightarrow$ **Met** (Min 12.7 mm/hr)
  - `open_space`: Ref = 1.0, Target = 1.0 (`Live (cached snapshot, 2026-10-22)`) $\rightarrow$ **Met**
  - `building_distance`: Ref = 15.0 m, Target = 18.0 m (`Live (cached snapshot, 2026-10-22)`) $\rightarrow$ **Met** (Min 3.0 m)
- **Supporting Factors:** All 5 factors met.
- **Limiting Factors:** None.
- **Actionable Checks:** None required.

---

### Scenario 2: Pune City $\rightarrow$ Niphad
- **Reference Location:** Pune City (`18.5204, 73.8567`)
- **Target Location:** Niphad (`20.0800, 74.1100`)
- **Overall Status:** `conditional`
- **Overall Compatibility Score:** `1.0` (100% on met thresholds, with transfer risk flag)
- **Data Provenance:**
  - `annual_rainfall`: Ref = 1731.3 mm/yr, Target = 858.3 mm/yr (`Live: NASA POWER`) $\rightarrow$ **Met threshold, but Transfer Risk triggered!**
    * *Transfer Tolerance:* 30% of Ref = $\pm 519.4$ mm/yr.
    * *Observed Delta:* $|858.3 - 1731.3| = 873.0$ mm/yr ($50.4\%$ difference $> 30\%$).
  - `slope`: Ref = 3.0%, Target = 1.4% (`Live: Open-Meteo Copernicus DEM`) $\rightarrow$ **Met**
  - `soil_infiltration`: Ref = 22.0 mm/hr, Target = 18.0 mm/hr (`Demo value`) $\rightarrow$ **Met**
  - `open_space`: Ref = 1.0, Target = 1.0 (`Live (cached snapshot, 2026-10-22)`) $\rightarrow$ **Met**
  - `building_distance`: Ref = 15.0 m, Target = 22.0 m (`Live (cached snapshot, 2026-10-22)`) $\rightarrow$ **Met**
- **Limiting Factors:** `annual_rainfall` (Transfer Risk).
- **Suggested Checks:** "Annual Rainfall differs from the reference site; confirm that local conditions support the adaptation."
- **Key Observation vs. Static CSV:** In the sample CSV, Niphad was assigned a 12.0% slope (an illustrative steep slope), which triggered an immediate `unsuitable` critical blocker. In live mode, actual satellite elevation data indicates flat-to-gentle agricultural terrain (1.4%), but live precipitation data uncovers a major rainfall divergence (semi-arid rain shadow region of Nashik district vs wetter Pune plateau).

---

### Scenario 3: Pune City $\rightarrow$ Lonavala
- **Reference Location:** Pune City (`18.5204, 73.8567`)
- **Target Location:** Lonavala (`18.7557, 73.4091`)
- **Overall Status:** `unsuitable`
- **Overall Compatibility Score:** `0.66` (66%)
- **Data Provenance:**
  - `soil_infiltration`: Ref = 22.0 mm/hr (`Demo value`), Target = **0.3 mm/hr** (`Live (cached snapshot, 2026-10-22)`) $\rightarrow$ **Unmet (Critical Blocker!)**
  - `annual_rainfall`: Ref = 1731.3 mm/yr, Target = 2509.3 mm/yr (`Live: NASA POWER`) $\rightarrow$ **Unmet & Transfer Risk** (>2500 mm/yr candidate limit)
  - `slope`: Ref = 3.0%, Target = 1.6% (`Live: Open-Meteo Copernicus DEM`) $\rightarrow$ **Met**
  - `open_space`: Ref = 1.0, Target = 1.0 (`Live (cached snapshot, 2026-10-22)`) $\rightarrow$ **Met**
  - `building_distance`: Ref = 15.0 m, Target = 35.0 m (`Live (cached snapshot, 2026-10-22)`) $\rightarrow$ **Met**
- **Critical Blocker Analysis (0.3 mm/hr Infiltration Rate):**
  - **Source Validation:** The 0.3 mm/hr value came from a **real live fetch** to the ISRIC SoilGrids v2.0 REST API at coordinates `(18.7557, 73.4091)`.
  - **Particle Breakdown:** SoilGrids measured soil fractions at 5-15cm depth:
    * Clay: $41.0\%$
    * Sand: $32.6\%$
    * Silt: $26.4\%$
  - **Soil Classification:** According to the USDA soil textural triangle, this fraction falls into the **Clay** texture class.
  - **Hydraulic Conductivity:** Saturated hydraulic conductivity ($K_s$) from the peer-reviewed Rawls et al. (1983) Table 1 lookup table assigns **$0.3\text{ mm/hr}$** to USDA Clay.
  - **Engineering Implication:** 0.3 mm/hr looks very low for bioretention (permeability is near-impervious). The Rain Garden critical requirement mandates at least $12.7\text{ mm/hr}$ ($0.5\text{ in/hr}$) for unlined gravity infiltration. At 0.3 mm/hr, stormwater cannot infiltrate within the mandatory 48-hour drain time and will cause persistent surface ponding and vector breeding.
  - **Decision Engine Outcome:** The engine correctly triggers the **Critical Blocker Override**, marking Lonavala `Unsuitable` despite an overall score of 0.66. It requires either an underdrain connection to the storm sewer or soil amendment with engineered sandy loam.

---

### Scenario 4: Pune City $\rightarrow$ Nashik City
- **Reference Location:** Pune City (`18.5204, 73.8567`)
- **Target Location:** Nashik City (`19.9975, 73.7898`)
- **Overall Status:** `conditional`
- **Overall Compatibility Score:** `0.85` (85%)
- **Data Provenance:**
  - `annual_rainfall`: Ref = 1731.3 mm/yr, Target = 1640.0 mm/yr (`Live: NASA POWER`) $\rightarrow$ **Met**
  - `slope`: Ref = 3.0%, Target = 3.5% (`Live: Open-Meteo Copernicus DEM`) $\rightarrow$ **Met**
  - `soil_infiltration`: Ref = 22.0 mm/hr, Target = 20.0 mm/hr (`Demo value`) $\rightarrow$ **Met**
  - `open_space`: Ref = 1.0, Target = 0.0 (`Live (cached snapshot, 2026-10-22)`) $\rightarrow$ **Unmet (Non-critical)**
  - `building_distance`: Ref = 15.0 m, Target = 8.5 m (`Live (cached snapshot, 2026-10-22)`) $\rightarrow$ **Met**
- **Limiting Factors:** `open_space`.
- **Suggested Checks:** "Verify open space at Location B; requirement is present [binary (1=present, 0=absent)]."

---

## Comparison with Static CSV vs. Live Mode

| Mode | Suitable | Conditional | Unsuitable | Insufficient Data |
| :--- | :--- | :--- | :--- | :--- |
| **Static CSV Default** | Pune $\rightarrow$ Pimpri | Pune $\rightarrow$ Nashik | Pune $\rightarrow$ Niphad (12% slope) | Pune $\rightarrow$ Lonavala (Null soil) |
| **Live External APIs** | Pune $\rightarrow$ Pimpri | Pune $\rightarrow$ Niphad (Rainfall delta) & Pune $\rightarrow$ Nashik (OSM space) | Pune $\rightarrow$ Lonavala (Soil 0.3 mm/hr & Rain >2500 mm/yr) | *Use UI override preset "Insufficient Data"* |

To enable zero-click demonstration of all 4 statuses within seconds in the UI, four preset scenario buttons are provided in the Advanced Override panel:
1. **Suitable (Pass):** All factors meet thresholds.
2. **Conditional (Survey/Risk):** Non-critical factor unmet (e.g. absent open space).
3. **Unsuitable (Blocker):** Critical slope exceeds 8% (e.g. 14.5%) or infiltration fails (<12.7 mm/hr).
4. **Insufficient Data (Missing):** Critical infiltration rate missing (null).
