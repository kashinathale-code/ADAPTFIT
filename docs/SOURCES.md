# Authoritative Citations & Evidence Sources for ADAPTFIT Rules

This document provides complete bibliographic references, regulatory citations, and source URLs for all environmental compatibility rules and thresholds evaluated in ADAPTFIT for urban **Rain Gardens** (Bioretention cells).

---

## 1. Verified Engineering Rules

### 1.1 Soil Infiltration Rate (`soil_infiltration`)
- **Threshold:** Minimum 12.7 mm/hr (0.5 in/hr)
- **Rule Version:** `v1.0-verified`
- **Critical Blocker:** Yes
- **Engineering Rationale:** A minimum hydraulic conductivity of 12.7 mm/hr (0.5 inches per hour) is required for unlined infiltration basins to ensure that captured stormwater completely drains within 24 to 48 hours following a rainfall event. This prevents standing water, root rot of native bioretention vegetation, and vector/mosquito breeding. Subsoils below this rate require engineered underdrains or soil amendments (sand/compost mixtures).
- **Primary Citations:**
  1. **United States Environmental Protection Agency (US EPA):**
     * Document: *Stormwater Best Management Practice: Bioretention* (EPA 833-F-00-001) / *Soak Up the Rain: Rain Gardens*
     * URL: [https://www.epa.gov/soakuptherain/soak-rain-rain-gardens](https://www.epa.gov/soakuptherain/soak-rain-rain-gardens)
  2. **Central Public Health and Environmental Engineering Organisation (CPHEEO):**
     * Document: *Manual on Storm Water Drainage Systems (2019)*, Ministry of Housing and Urban Affairs (MoHUA), Government of India. Chapter 10: Innovative Storm Water Management Practices & SUDS.
     * URL: [http://cpheeo.gov.in/cms/manual-on-storm-water-drainage-systems-2019.php](http://cpheeo.gov.in/cms/manual-on-storm-water-drainage-systems-2019.php)

---

### 1.2 Slope (`slope`)
- **Threshold:** Maximum 8.0 %
- **Rule Version:** `v1.0-verified`
- **Critical Blocker:** Yes
- **Engineering Rationale:** Standard rain garden cells require a nearly flat basin bed (slope < 0.5%) to allow uniform ponding and infiltration. When constructed on natural terrain slopes exceeding 8.0%, cut-and-fill depths become prohibitive, and overland inflow velocities cause severe bed scour and embankment instability unless specialized retaining structures, step-pools, or check dams are installed.
- **Primary Citations:**
  1. **Minnesota Pollution Control Agency (MPCA):**
     * Document: *Minnesota Stormwater Manual: Design criteria for bioretention*
     * URL: [https://stormwater.pca.state.mn.us/index.php/Design_criteria_for_bioretention](https://stormwater.pca.state.mn.us/index.php/Design_criteria_for_bioretention)
  2. **Wisconsin Department of Natural Resources (WDNR):**
     * Document: *Bioretention for Runoff Management* (Conservation Practice Standard 1004)
     * URL: [https://dnr.wisconsin.gov/topic/Stormwater/standards/postconst_standards.html](https://dnr.wisconsin.gov/topic/Stormwater/standards/postconst_standards.html)
  3. **Philadelphia Water Department (PWD):**
     * Document: *Stormwater Management Guidance Manual*, Section 4.2 (Bioretention)
     * URL: [https://water.phila.gov/development/stormwater-plan-review/manual/](https://water.phila.gov/development/stormwater-plan-review/manual/)

---

### 1.3 Building Foundation Setback (`building_distance`)
- **Threshold:** Minimum 3.0 m (10 ft)
- **Rule Version:** `v1.0-verified`
- **Critical Blocker:** No (Weighted factor)
- **Engineering Rationale:** Infiltrating large volumes of runoff close to building foundations risks moisture migration, hydrostatic pressure buildup against basement walls, and differential foundation settlement in expansive or softening soils. Unlined rain gardens must maintain a minimum 3.0 m (10 ft) setback; if sited closer, geotechnical evaluation and impermeable waterproof geomembrane liners are mandatory.
- **Primary Citations:**
  1. **United States Environmental Protection Agency (US EPA):**
     * Document: *Soak Up the Rain: Rain Gardens – Siting and Construction Guidance*
     * URL: [https://www.epa.gov/soakuptherain/soak-rain-rain-gardens](https://www.epa.gov/soakuptherain/soak-rain-rain-gardens)
  2. **CIRIA (Construction Industry Research and Information Association, UK):**
     * Document: *The SuDS Manual (C753)*, Chapter 25: Infiltration systems & Section 25.2.3: Foundation setbacks.
     * URL: [https://www.ciria.org/ItemDetail?iProductCode=C753F](https://www.ciria.org/ItemDetail?iProductCode=C753F)

---

### 1.4 Open Space Availability (`open_space`)
- **Threshold:** Binary indicator (1.0 = present, 0.0 = absent)
- **Rule Version:** `v1.0-verified`
- **Critical Blocker:** No (Weighted factor)
- **Engineering Rationale:** Rain gardens require physically unbuilt, unpaved surface ground capable of surface grading and planting, clear of critical underground utilities (gas, high-voltage electric, telecommunications).
- **Primary Citations:**
  1. **CPHEEO Manual on Storm Water Drainage Systems (2019):**
     * Document: Chapter 10 (Sustainable Urban Drainage Systems - Site Evaluation).
     * URL: [http://cpheeo.gov.in/cms/manual-on-storm-water-drainage-systems-2019.php](http://cpheeo.gov.in/cms/manual-on-storm-water-drainage-systems-2019.php)
  2. **CIRIA C753 The SuDS Manual:**
     * Document: Chapter 20 (Bioretention systems site layout and physical integration).
     * URL: [https://www.ciria.org/ItemDetail?iProductCode=C753F](https://www.ciria.org/ItemDetail?iProductCode=C753F)

---

## 2. Candidate, Unverified Rules

### 2.1 Annual Rainfall Range (`annual_rainfall`)
- **Threshold:** 600.0 – 2500.0 mm/yr
- **Rule Version:** `v0.1-candidate`
- **Status:** **Candidate, unverified**
- **Engineering Rationale:** Unlike infiltration rate or setback distance, international stormwater manuals do not enforce strict hard cutoffs for annual cumulative precipitation. Rain gardens function across wide climate regimes (from dry climates through wet monsoon regions) by adjusting the basin-to-impervious area ratio (sizing factor) and storage depth. The range 600–2500 mm/yr represents an operational heuristic for standard bioretention cells without specialized deep aquifer retention or extreme overflow structures. Site design storm depth (e.g. 95th percentile 24-hr event) must always supersede annual totals in engineering design.
- **Reference URL:** [https://stormwater.pca.state.mn.us/index.php/Design_criteria_for_bioretention](https://stormwater.pca.state.mn.us/index.php/Design_criteria_for_bioretention) (MPCA guidance notes that water quality volume calculations govern sizing rather than annual averages).

---

## 3. Data Attribution & External APIs

| Dataset / Service | Provider | Resolution / Coverage | URL |
| :--- | :--- | :--- | :--- |
| **Meteorology / Precipitation** | NASA POWER Project (CERES / MERRA-2) | 0.5° × 0.5° (~50 km grid) | [https://power.larc.nasa.gov/](https://power.larc.nasa.gov/) |
| **Elevation & Topography** | Open-Meteo Elevation API (Copernicus DEM GLO-90) | 90 m grid | [https://open-meteo.com/en/docs/elevation-api](https://open-meteo.com/en/docs/elevation-api) |
| **Soil Physical Properties** | ISRIC SoilGrids REST API | 250 m raster | [https://rest.isric.org/](https://rest.isric.org/) |
| **Built Environment & Land Use** | OpenStreetMap (Overpass API) | Vector geometry (point / polygon) | [https://overpass-api.de/](https://overpass-api.de/) |

---

## 4. Soil Infiltration Estimation Methodology & Provenance

### 4.1 Live Soil Query Parameters
- **API Endpoint:** `https://rest.isric.org/soilgrids/v2.0/properties/query`
- **Parameters:** `lon`, `lat`, `property=sand`, `property=clay`, `property=silt`, `depth=5-15cm`, `value=mean`.
- **Scaling Factor:** Raw layer mean values are scaled by `d_factor` (10) to obtain particle size weight percentages ($\text{sand}\%$, $\text{silt}\%$, $\text{clay}\%$).

### 4.2 USDA Soil Texture Classification
Percentages are classified into one of the 12 USDA Soil Texture classes according to the *USDA Soil Survey Manual*, Agriculture Handbook No. 18 (Chapter 3: Examination and Description of Soils).
- Citation: Soil Survey Staff (2017). *Soil Survey Manual*, USDA Handbook 18, Government Printing Office, Washington, D.C. URL: [https://www.nrcs.usda.gov/resources/guides-and-instructions/soil-survey-manual](https://www.nrcs.usda.gov/resources/guides-and-instructions/soil-survey-manual)

### 4.3 Infiltration Conversion Table (Rawls et al., 1983)
The USDA texture class is translated to saturated hydraulic conductivity ($K_s$, mm/hr) using the Green-Ampt parameter table:
- Citation: Rawls, W.J., Brakensiek, D.L., & Miller, N. (1983). *"Green-Ampt infiltration parameters from soil data."* Journal of Hydraulic Engineering, 109(1), 62–70. DOI: [10.1061/(ASCE)0733-9429(1983)109:1(62)](https://doi.org/10.1061/(ASCE)0733-9429(1983)109:1(62))

| USDA Texture Class | Rawls et al. (1983) $K_s$ (mm/hr) | ADAPTFIT Rule Interpretation |
| :--- | :--- | :--- |
| **Sand** | 117.8 | Exceeds minimum (12.7 mm/hr); suitable infiltration |
| **Loamy sand** | 29.9 | Exceeds minimum (12.7 mm/hr); suitable infiltration |
| **Sandy loam** | 10.9 | Marginally below 12.7 mm/hr; conditional verification |
| **Silt loam** | 6.5 | Below 12.7 mm/hr; requires underdrain or soil amendment |
| **Silt** | 6.5 | Below 12.7 mm/hr; requires underdrain or amendment |
| **Loam** | 3.4 | Below 12.7 mm/hr; requires underdrain or amendment |
| **Sandy clay loam** | 1.5 | Unsuitable for unlined infiltration without underdrain |
| **Clay loam** | 1.0 | Unsuitable for unlined infiltration without underdrain |
| **Silty clay loam** | 1.0 | Unsuitable for unlined infiltration without underdrain |
| **Sandy clay** | 0.6 | Critical blocker for unlined infiltration |
| **Silty clay** | 0.5 | Critical blocker for unlined infiltration |
| **Clay** | 0.3 | Critical blocker for unlined infiltration |

### 4.4 Mandatory Provenance Labeling
- **Provenance Label:** **`Estimated (proxy)`**, never measured.
- **Rule:** Regional digital soil maps reflect 250 m predictive models rather than localized borehole or double-ring infiltrometer field tests. In ADAPTFIT, all SoilGrids-derived infiltration rates are strictly labeled `Estimated (proxy): SoilGrids v2.0 (ISRIC)` to maintain transparent scientific provenance.

