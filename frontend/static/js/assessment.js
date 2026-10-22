/**
 * ADAPTFIT – New Assessment Page Controller
 * Map interaction (Leaflet), preset selection, preview table updates,
 * and API submission to POST /api/assessments.
 */

let map = null;
let markerA = null;
let markerB = null;
let nextMarkerToSet = 'A'; // 'A' or 'B'

// Known sample demo locations for map pins
const SAMPLE_PRESETS = [
  { name: "Pune city", lat: 18.5204, lon: 73.8567 },
  { name: "Nashik city", lat: 19.9975, lon: 73.7898 },
  { name: "Pimpri", lat: 18.6298, lon: 73.7997 },
  { name: "Niphad", lat: 20.0800, lon: 74.1100 },
  { name: "Lonavala", lat: 18.7557, lon: 73.4091 }
];

document.addEventListener("DOMContentLoaded", () => {
  initMap();
  loadAdaptations();
  updateEnvironmentalPreview();
});

/**
 * Initialize Leaflet Map
 */
function initMap() {
  const mapContainer = document.getElementById("leafletMap");
  if (!mapContainer) return;

  // Center on Western Maharashtra region
  map = L.map("leafletMap").setView([19.25, 73.85], 8);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  // Add subtle demo reference pins
  SAMPLE_PRESETS.forEach(preset => {
    const circle = L.circleMarker([preset.lat, preset.lon], {
      radius: 6,
      fillColor: "#64748b",
      color: "#ffffff",
      weight: 1.5,
      opacity: 0.9,
      fillOpacity: 0.7
    }).addTo(map);

    circle.bindTooltip(`<b>${preset.name}</b> (Sample Site)<br>Lat: ${preset.lat}, Lon: ${preset.lon}`, {
      direction: "top"
    });

    circle.on("click", (e) => {
      L.DomEvent.stopPropagation(e);
      setPresetLocation(nextMarkerToSet, preset.name, preset.lat, preset.lon);
    });
  });

  // Handle map click for Marker A then Marker B
  map.on("click", (e) => {
    const lat = parseFloat(e.latlng.lat.toFixed(4));
    const lon = parseFloat(e.latlng.lng.toFixed(4));

    if (nextMarkerToSet === 'A') {
      setLocationValues('A', `Location A (${lat}, ${lon})`, lat, lon);
      nextMarkerToSet = 'B';
      updateMapInstruction("Marker A set. Now click on the map to set <strong>Marker B (Target Site)</strong>.");
    } else {
      setLocationValues('B', `Location B (${lat}, ${lon})`, lat, lon);
      nextMarkerToSet = 'A';
      updateMapInstruction("Both markers set. Click anywhere to re-position <strong>Marker A</strong>.");
    }
  });

  // Initialize default marker positions
  const aLat = parseFloat(document.getElementById("locA_lat").value);
  const aLon = parseFloat(document.getElementById("locA_lon").value);
  const bLat = parseFloat(document.getElementById("locB_lat").value);
  const bLon = parseFloat(document.getElementById("locB_lon").value);

  updateMarker('A', aLat, aLon, "Location A (Reference)");
  updateMarker('B', bLat, bLon, "Location B (Target)");
}

function updateMapInstruction(htmlMsg) {
  const el = document.getElementById("mapClickInstruction");
  if (el) el.innerHTML = htmlMsg;
}

/**
 * Custom Pin Icons
 */
function createCustomPin(letter, colorClass) {
  return L.divIcon({
    className: "custom-map-pin",
    html: `<div class="${colorClass}"><span class="pin-text">${letter}</span></div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 32],
    popupAnchor: [0, -30]
  });
}

function updateMarker(type, lat, lon, title) {
  if (!map) return;

  const isA = type === 'A';
  const pinIcon = createCustomPin(isA ? 'A' : 'B', isA ? 'custom-pin-a' : 'custom-pin-b');

  if (isA) {
    if (markerA) {
      markerA.setLatLng([lat, lon]);
    } else {
      markerA = L.marker([lat, lon], { icon: pinIcon, draggable: true }).addTo(map);
      markerA.on("dragend", () => {
        const pos = markerA.getLatLng();
        setLocationValues('A', document.getElementById("locA_name").value, pos.lat.toFixed(4), pos.lng.toFixed(4));
      });
    }
    markerA.bindPopup(`<b>Location A (Reference Site)</b><br>${title}<br>Lat: ${lat}, Lon: ${lon}`);
  } else {
    if (markerB) {
      markerB.setLatLng([lat, lon]);
    } else {
      markerB = L.marker([lat, lon], { icon: pinIcon, draggable: true }).addTo(map);
      markerB.on("dragend", () => {
        const pos = markerB.getLatLng();
        setLocationValues('B', document.getElementById("locB_name").value, pos.lat.toFixed(4), pos.lng.toFixed(4));
      });
    }
    markerB.bindPopup(`<b>Location B (Target Site)</b><br>${title}<br>Lat: ${lat}, Lon: ${lon}`);
  }
}

/**
 * Update Location Coordinates & Trigger Environmental Preview
 */
function setLocationValues(type, name, lat, lon) {
  if (type === 'A') {
    document.getElementById("locA_name").value = name;
    document.getElementById("locA_lat").value = lat;
    document.getElementById("locA_lon").value = lon;
    updateMarker('A', lat, lon, name);
  } else {
    document.getElementById("locB_name").value = name;
    document.getElementById("locB_lat").value = lat;
    document.getElementById("locB_lon").value = lon;
    updateMarker('B', lat, lon, name);
  }
  updateEnvironmentalPreview();
}

function setPresetLocation(type, name, lat, lon) {
  setLocationValues(type, name, lat, lon);
  if (map) {
    map.panTo([lat, lon]);
  }
}

function onManualCoordChange(type) {
  const lat = parseFloat(document.getElementById(`loc${type}_lat`).value);
  const lon = parseFloat(document.getElementById(`loc${type}_lon`).value);
  const name = document.getElementById(`loc${type}_name`).value;
  if (!isNaN(lat) && !isNaN(lon)) {
    updateMarker(type, lat, lon, name);
    updateEnvironmentalPreview();
  }
}

/**
 * Fetch available adaptations from API
 */
async function loadAdaptations() {
  try {
    const res = await fetch("/api/adaptations");
    if (!res.ok) return;
    const adaptations = await res.json();
    const select = document.getElementById("adaptationSelect");
    if (select && adaptations.length > 0) {
      select.innerHTML = "";
      adaptations.forEach(a => {
        const opt = document.createElement("option");
        opt.value = a.id;
        opt.textContent = `${a.name}`;
        select.appendChild(opt);
      });
      document.getElementById("adaptationDesc").textContent = adaptations[0].description || "";
    }
  } catch (err) {
    console.error("Failed to fetch adaptations:", err);
  }
}

/**
 * Update Environmental Preview Table by calling /api/location-data
 */
let previewDebounceTimer = null;

function updateEnvironmentalPreview() {
  clearTimeout(previewDebounceTimer);
  previewDebounceTimer = setTimeout(async () => {
    const aLat = document.getElementById("locA_lat").value;
    const aLon = document.getElementById("locA_lon").value;
    const bLat = document.getElementById("locB_lat").value;
    const bLon = document.getElementById("locB_lon").value;

    if (!aLat || !aLon || !bLat || !bLon) return;

    try {
      const [resA, resB] = await Promise.all([
        fetch(`/api/location-data?lat=${aLat}&lon=${aLon}&name=${encodeURIComponent(document.getElementById("locA_name").value)}`),
        fetch(`/api/location-data?lat=${bLat}&lon=${bLon}&name=${encodeURIComponent(document.getElementById("locB_name").value)}`)
      ]);

      if (!resA.ok || !resB.ok) return;

      const dataA = await resA.json();
      const dataB = await resB.json();

      renderPreviewTable(dataA, dataB);
    } catch (err) {
      console.error("Preview fetch error:", err);
    }
  }, 250);
}

function renderPreviewTable(dataA, dataB) {
  const tbody = document.getElementById("previewTableBody");
  if (!tbody) return;

  const factorsConfig = [
    { key: "soil_infiltration", label: "Soil Infiltration", rule: "min 12.7 mm/hr (critical)" },
    { key: "slope", label: "Ground Slope", rule: "max 8.0 % (critical)" },
    { key: "annual_rainfall", label: "Annual Rainfall", rule: "600 – 2500 mm/yr" },
    { key: "open_space", label: "Open Space", rule: "Present (site survey)" },
    { key: "building_distance", label: "Building Distance", rule: "min 3.0 m" }
  ];

  tbody.innerHTML = "";

  factorsConfig.forEach(cfg => {
    const aFactor = dataA.factors ? dataA.factors[cfg.key] : null;
    const bFactor = dataB.factors ? dataB.factors[cfg.key] : null;

    // Check if user set override
    const ovA = getOverrideVal('a', cfg.key);
    const ovB = getOverrideVal('b', cfg.key);

    const valA = ovA !== null ? ovA : (aFactor ? aFactor.value : null);
    const valB = ovB !== null ? ovB : (bFactor ? bFactor.value : null);

    const unit = (bFactor && bFactor.unit) ? bFactor.unit : ((aFactor && aFactor.unit) ? aFactor.unit : "");
    const srcA = (aFactor && aFactor.source) ? aFactor.source : "Demo value";
    const srcB = (bFactor && bFactor.source) ? bFactor.source : "Demo value";
    const resA = (aFactor && aFactor.resolution) ? aFactor.resolution : "n/a (demo)";
    const resB = (bFactor && bFactor.resolution) ? bFactor.resolution : "n/a (demo)";

    function getProvenanceLabel(src) {
      if (!src) return "Demo value";
      if (src.startsWith("Live:") || src.startsWith("Estimated (proxy):")) {
        return src;
      }
      return "Demo value";
    }

    const labelA = getProvenanceLabel(srcA);
    const labelB = getProvenanceLabel(srcB);
    const isSpecialA = labelA !== "Demo value";
    const isSpecialB = labelB !== "Demo value";
    const provClassA = (srcA || "").startsWith("Live:") ? 'badge-provenance-live' : ((srcA || "").startsWith("Estimated (proxy):") ? 'badge-provenance-estimated' : 'badge-provenance-demo');
    const provClassB = (srcB || "").startsWith("Live:") ? 'badge-provenance-live' : ((srcB || "").startsWith("Estimated (proxy):") ? 'badge-provenance-estimated' : 'badge-provenance-demo');

    const badgeA = valA !== null
      ? `<div><strong>${valA}</strong> <small class="text-muted">${unit}</small></div><div class="preview-val-prov ${provClassA}">${escapeHtml(labelA)} &bull; ${escapeHtml(resA)}</div>`
      : `<span class="badge-unknown">Unknown</span>`;

    const badgeB = valB !== null
      ? `<div><strong>${valB}</strong> <small class="text-muted">${unit}</small></div><div class="preview-val-prov ${provClassB}">${escapeHtml(labelB)} &bull; ${escapeHtml(resB)}</div>`
      : `<span class="badge-unknown">Unknown</span>`;

    const isLive = isSpecialB || isSpecialA;
    const displaySource = isSpecialB ? labelB : (isSpecialA ? labelA : "Demo value");
    const displayRes = isSpecialB ? resB : (isSpecialA ? resA : (resB || resA || "n/a (demo)"));

    const row = document.createElement("tr");
    row.innerHTML = `
      <td><strong>${cfg.label}</strong></td>
      <td class="col-center">${badgeA}</td>
      <td class="col-center">${badgeB}</td>
      <td><span class="${isLive ? 'badge-provenance-live' : 'text-muted'}">${escapeHtml(displaySource)}</span></td>
      <td><span class="text-muted">${escapeHtml(displayRes)}</span></td>
      <td><span class="rule-tag">${cfg.rule}</span></td>
    `;
    tbody.appendChild(row);
  });

  // Update header badge listing which factors are currently live, estimated or demo
  updateHeaderDataBadge(dataA, dataB);

  // Render combined warnings if any
  const warningsList = document.getElementById("previewWarningsList");
  const warningsContainer = document.getElementById("previewWarningsContainer");
  const allWarnings = [...(dataA.data_quality_warnings || []), ...(dataB.data_quality_warnings || [])];

  if (warningsList && warningsContainer) {
    if (allWarnings.length > 0) {
      warningsList.innerHTML = allWarnings.map(w => `<li>${escapeHtml(w)}</li>`).join("");
      warningsContainer.style.display = "block";
    } else {
      warningsContainer.style.display = "none";
    }
  }
}

function updateHeaderDataBadge(dataA, dataB) {
  const factorNames = {
    annual_rainfall: "rainfall",
    slope: "slope",
    soil_infiltration: "soil infiltration",
    open_space: "open space",
    building_distance: "building distance"
  };

  const live = [];
  const estimated = [];
  const demo = [];

  const allKeys = ["annual_rainfall", "slope", "soil_infiltration", "open_space", "building_distance"];
  allKeys.forEach(k => {
    const srcA = dataA?.factors?.[k]?.source || "";
    const srcB = dataB?.factors?.[k]?.source || "";
    const name = factorNames[k] || k;
    if (srcA.startsWith("Live:") || srcB.startsWith("Live:")) {
      live.push(name);
    } else if (srcA.startsWith("Estimated (proxy):") || srcB.startsWith("Estimated (proxy):")) {
      estimated.push(name);
    } else {
      demo.push(name);
    }
  });

  const parts = [];
  if (live.length > 0) parts.push(`Live: ${live.join(", ")}`);
  if (estimated.length > 0) parts.push(`Estimated: ${estimated.join(", ")}`);
  if (demo.length > 0) parts.push(`Demo: ${demo.join(", ")}`);

  const text = parts.join(" | ");
  const isMixedOrLive = live.length > 0 || estimated.length > 0;

  const badgeText = document.getElementById("headerBadgeText");
  const badgeContainer = document.getElementById("headerDataBadge") || document.querySelector(".demo-badge-header");

  if (badgeText) {
    badgeText.textContent = text;
  } else if (badgeContainer) {
    const span = badgeContainer.querySelector("span:not(.badge-dot)");
    if (span) span.textContent = text;
  }

  if (badgeContainer) {
    if (isMixedOrLive) {
      badgeContainer.classList.add("mixed-live");
    } else {
      badgeContainer.classList.remove("mixed-live");
    }
  }

  // Also update page-level demo pill badges
  const bannerBadges = document.querySelectorAll(".demo-pill-highlight, .demo-badge-inline");
  bannerBadges.forEach(b => {
    const strong = b.querySelector("strong");
    if (strong) {
      strong.textContent = text;
    } else {
      const span = b.querySelector("span:not(.pulse-indicator)");
      if (span) span.textContent = text;
    }
  });
}

function formatValBadge(val, unit) {
  if (val === null || val === undefined) {
    return `<span class="badge-unknown">Unknown</span>`;
  }
  return `<strong>${val}</strong> <small class="text-muted">${unit}</small>`;
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[m]);
}

/**
 * Handle Override Helper Values
 */
function getOverrideVal(loc, factorKey) {
  const map = {
    "soil_infiltration": `ov_${loc}_soil`,
    "slope": `ov_${loc}_slope`,
    "annual_rainfall": `ov_${loc}_rain`,
    "open_space": `ov_${loc}_space`,
    "building_distance": `ov_${loc}_dist`
  };
  const el = document.getElementById(map[factorKey]);
  if (!el || el.value.trim() === "") return null;
  const num = parseFloat(el.value);
  return isNaN(num) ? null : num;
}

function applyDemoProfile(type) {
  if (type === 'suitable') {
    // Both pass, similar profiles
    document.getElementById("ov_a_soil").value = "30.0";
    document.getElementById("ov_a_slope").value = "3.0";
    document.getElementById("ov_a_rain").value = "1200";
    document.getElementById("ov_a_space").value = "1";
    document.getElementById("ov_a_dist").value = "5.0";

    document.getElementById("ov_b_soil").value = "28.0";
    document.getElementById("ov_b_slope").value = "4.0";
    document.getElementById("ov_b_rain").value = "1100";
    document.getElementById("ov_b_space").value = "1";
    document.getElementById("ov_b_dist").value = "6.0";
  } else if (type === 'unsuitable') {
    // Location B fails slope blocker (>8%)
    document.getElementById("ov_a_soil").value = "30.0";
    document.getElementById("ov_a_slope").value = "3.0";
    document.getElementById("ov_a_rain").value = "1200";
    document.getElementById("ov_a_space").value = "1";
    document.getElementById("ov_a_dist").value = "5.0";

    document.getElementById("ov_b_soil").value = "25.0";
    document.getElementById("ov_b_slope").value = "14.5"; // Critical blocker!
    document.getElementById("ov_b_rain").value = "1100";
    document.getElementById("ov_b_space").value = "1";
    document.getElementById("ov_b_dist").value = "6.0";
  }
  updateEnvironmentalPreview();
}

function clearDemoOverrides() {
  ["a", "b"].forEach(loc => {
    ["soil", "slope", "rain", "dist"].forEach(k => {
      const el = document.getElementById(`ov_${loc}_${k}`);
      if (el) el.value = "";
    });
    const spaceEl = document.getElementById(`ov_${loc}_space`);
    if (spaceEl) spaceEl.value = "";
  });
  updateEnvironmentalPreview();
}

/**
 * Submit Assessment
 */
async function submitAssessment() {
  const errBox = document.getElementById("formErrorMessage");
  const btn = document.getElementById("submitAssessmentBtn");
  const btnText = document.getElementById("btnText");

  errBox.style.display = "none";
  btn.disabled = true;
  btnText.textContent = "Screening in progress...";

  const payload = {
    adaptation_id: document.getElementById("adaptationSelect").value,
    reference_location: {
      name: document.getElementById("locA_name").value,
      latitude: parseFloat(document.getElementById("locA_lat").value),
      longitude: parseFloat(document.getElementById("locA_lon").value),
      factors: {}
    },
    target_location: {
      name: document.getElementById("locB_name").value,
      latitude: parseFloat(document.getElementById("locB_lat").value),
      longitude: parseFloat(document.getElementById("locB_lon").value),
      factors: {}
    }
  };

  // Collect manual overrides if provided
  ["soil_infiltration", "slope", "annual_rainfall", "open_space", "building_distance"].forEach(k => {
    const aVal = getOverrideVal('a', k);
    if (aVal !== null) payload.reference_location.factors[k] = aVal;

    const bVal = getOverrideVal('b', k);
    if (bVal !== null) payload.target_location.factors[k] = bVal;
  });

  try {
    const res = await fetch("/api/assessments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Assessment failed. Please check inputs.");
    }

    // Save assessment result in sessionStorage and redirect to /results
    sessionStorage.setItem("lastAssessment", JSON.stringify(data));
    window.location.href = `/results?id=${data.assessment_id}`;
  } catch (err) {
    errBox.textContent = err.message;
    errBox.style.display = "block";
    btn.disabled = false;
    btnText.textContent = "Run assessment";
  }
}
