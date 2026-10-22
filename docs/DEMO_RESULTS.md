# ADAPTFIT Demo Scenarios Verification Results

This document records the empirical results of running the four primary Maharashtra demonstration pairs through the ADAPTFIT API under live flags (`USE_LIVE_RAINFALL=true`, `USE_LIVE_SLOPE=true`, `USE_LIVE_SOIL=true`, `USE_LIVE_OSM=true`).

Evaluated Adaptation: **Rain Garden** (`rain_garden`)  
Engine Configuration: `SUITABLE_MIN = 0.75`, `MAX_MISSING_WEIGHT = 0.30`

---

## Summary of Results

| Pair | Reference (A) | Target (B) | Live Status | Score | Primary Deciding Factor(s) | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | Pune City | Pimpri | **Suitable** | `1.0` | All factors met; no transfer risks | High compatibility across all dimensions |
| **2** | Pune City | Niphad | **Conditional** | `1.0` | `annual_rainfall` transfer risk (858 vs 1731 mm/yr, >30% delta) | Live Copernicus DEM measures slope as 1.4% (met), unlike static CSV (12%). Rainfall divergence triggers transfer risk. |
| **3** | Pune City | Lonavala | **Insufficient Data** | `None` | `soil_infiltration` missing (critical factor weight 35% > 30%) | Unmeasured critical infiltration prevents classification |
| **4** | Pune City | Nashik City | **Conditional** | `0.85` | `open_space` unmet (0 vs required present) | Non-critical factor unmet; requires site spatial survey |

---

## Detailed Scenario Breakdown (Live Mode)

### Scenario 1: Pune City $\rightarrow$ Pimpri
- **Reference Location:** Pune City (`18.5204, 73.8567`)
- **Target Location:** Pimpri (`18.6298, 73.7997`)
- **Overall Status:** `suitable`
- **Overall Compatibility Score:** `1.0` (100%)
- **Live Flags Active:** Rainfall (`NASA POWER`), Slope (`Open-Meteo Copernicus DEM`)
- **Factor Evaluation:**
  - `soil_infiltration`: Ref = 22.0 mm/hr, Target = 25.0 mm/hr $\rightarrow$ **Met** (Min 12.7 mm/hr)
  - `slope`: Ref = 3.0%, Target = 0.7% (Live Open-Meteo) $\rightarrow$ **Met** (Max 8.0%)
  - `annual_rainfall`: Ref = 1731.3 mm/yr, Target = 1731.3 mm/yr (Live NASA POWER regional grid) $\rightarrow$ **Met** (600–2500 mm/yr)
  - `open_space`: Ref = 1.0, Target = 1.0 $\rightarrow$ **Met**
  - `building_distance`: Ref = 6.0 m, Target = 8.0 m $\rightarrow$ **Met** (Min 3.0 m)
- **Supporting Factors:** All 5 factors.
- **Limiting Factors:** None.
- **Actionable Checks:** None required.

---

### Scenario 2: Pune City $\rightarrow$ Niphad
- **Reference Location:** Pune City (`18.5204, 73.8567`)
- **Target Location:** Niphad (`20.0800, 74.1100`)
- **Overall Status:** `conditional` (Score `1.0`)
- **Live Flags Active:** Rainfall (`NASA POWER`), Slope (`Open-Meteo Copernicus DEM`)
- **Factor Evaluation:**
  - `soil_infiltration`: Ref = 22.0 mm/hr, Target = 18.0 mm/hr $\rightarrow$ **Met**
  - `slope`: Ref = 3.0%, Target = 1.4% (Live Copernicus DEM) $\rightarrow$ **Met**
  - `annual_rainfall`: Ref = 1731.3 mm/yr, Target = 858.3 mm/yr $\rightarrow$ **Met threshold, but Transfer Risk triggered!**
    * *Transfer Tolerance:* 30% of Ref = $\pm 519.4$ mm/yr.
    * *Observed Delta:* $|858.3 - 1731.3| = 873.0$ mm/yr ($50.4\%$ difference $> 30\%$).
  - `open_space`: Ref = 1.0, Target = 1.0 $\rightarrow$ **Met**
  - `building_distance`: Ref = 6.0 m, Target = 7.0 m $\rightarrow$ **Met**
- **Limiting Factors:** `annual_rainfall` (Transfer Risk).
- **Suggested Checks:** "Annual Rainfall differs from the reference site; confirm that local conditions support the adaptation."
- **Key Observation vs. Static CSV:** In the sample CSV, Niphad was assigned a 12.0% slope (an illustrative steep slope), which triggered an immediate `unsuitable` critical blocker. In live mode, actual satellite elevation data indicates flat-to-gentle terrain (1.4%), but live precipitation data uncovers a major rainfall divergence (semi-arid rain shadow region of Nashik district vs wetter Pune plateau).

---

### Scenario 3: Pune City $\rightarrow$ Lonavala
- **Reference Location:** Pune City (`18.5204, 73.8567`)
- **Target Location:** Lonavala (`18.7557, 73.4091`)
- **Overall Status:** `insufficient_data`
- **Overall Compatibility Score:** `None` (Withheld per TRD §6)
- **Live Flags Active:** Rainfall (`NASA POWER`), Slope (`Open-Meteo Copernicus DEM`)
- **Factor Evaluation:**
  - `soil_infiltration`: Ref = 22.0 mm/hr, Target = `None` $\rightarrow$ **Unknown (Critical Factor Missing)**
  - `slope`: Ref = 3.0%, Target = 1.6% (Live Copernicus DEM) $\rightarrow$ **Met**
  - `annual_rainfall`: Ref = 1731.3 mm/yr, Target = 2509.3 mm/yr $\rightarrow$ **Unmet & Transfer Risk** (>2500 mm/yr candidate limit)
  - `open_space`: Ref = 1.0, Target = 1.0 $\rightarrow$ **Met**
  - `building_distance`: Ref = 6.0 m, Target = 10.0 m $\rightarrow$ **Met**
- **Decision Rule Triggered:** Critical factor unknown (`soil_infiltration`) + missing weight ratio ($35\% > 30\%$). Classification withheld.
- **Suggested Checks:** "Obtain soil infiltration data for Location B; perform double-ring infiltrometer test."

---

### Scenario 4: Pune City $\rightarrow$ Nashik City
- **Reference Location:** Pune City (`18.5204, 73.8567`)
- **Target Location:** Nashik City (`19.9975, 73.7898`)
- **Overall Status:** `conditional`
- **Overall Compatibility Score:** `0.85` (85%)
- **Live Flags Active:** Rainfall (`NASA POWER`), Slope (`Open-Meteo Copernicus DEM`)
- **Factor Evaluation:**
  - `soil_infiltration`: Ref = 22.0 mm/hr, Target = 20.0 mm/hr $\rightarrow$ **Met**
  - `slope`: Ref = 3.0%, Target = 3.5% (Live Copernicus DEM) $\rightarrow$ **Met**
  - `annual_rainfall`: Ref = 1731.3 mm/yr, Target = 1640.0 mm/yr $\rightarrow$ **Met**
  - `open_space`: Ref = 1.0, Target = 0.0 $\rightarrow$ **Unmet (Non-critical)**
  - `building_distance`: Ref = 6.0 m, Target = 5.0 m $\rightarrow$ **Met**
- **Limiting Factors:** `open_space`.
- **Suggested Checks:** "Verify open space at Location B; requirement is present [binary (1=present, 0=absent)]."

---

## Comparison with Static CSV vs. Live Mode

| Mode | Suitable | Conditional | Unsuitable | Insufficient Data |
| :--- | :--- | :--- | :--- | :--- |
| **Static CSV Default** | Pune $\rightarrow$ Pimpri | Pune $\rightarrow$ Nashik | Pune $\rightarrow$ Niphad (12% slope) | Pune $\rightarrow$ Lonavala (Null soil) |
| **Live External APIs** | Pune $\rightarrow$ Pimpri | Pune $\rightarrow$ Niphad (Rainfall delta) & Pune $\rightarrow$ Nashik | *Use UI override preset "Unsuitable (Blocker)"* | Pune $\rightarrow$ Lonavala (Null soil) |

To enable zero-click demonstration of all 4 statuses within seconds in the UI, four preset scenario buttons are provided in the Advanced Override panel:
1. **Suitable (Pass):** All factors meet thresholds.
2. **Conditional (Survey/Risk):** Non-critical factor unmet (e.g. absent open space).
3. **Unsuitable (Blocker):** Critical slope exceeds 8% (e.g. 14.5%).
4. **Insufficient Data (Missing):** Critical infiltration rate missing (null).
