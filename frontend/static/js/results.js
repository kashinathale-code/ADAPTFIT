/**
 * ADAPTFIT – Results Page Controller
 * Renders assessment screening status, score, factor comparison table,
 * limiting factors, suggested checks, and data-quality warnings.
 */

document.addEventListener("DOMContentLoaded", () => {
  initResultsPage();
});

async function initResultsPage() {
  const loading = document.getElementById("loadingState");
  const errorCard = document.getElementById("errorState");
  const content = document.getElementById("resultsContent");

  const urlParams = new URLSearchParams(window.location.search);
  const appEl = document.getElementById("resultsApp");
  const embeddedId = appEl ? appEl.dataset.assessmentId : null;
  let assessmentId = urlParams.get("id") || embeddedId;
  if (!assessmentId) {
    const pathMatch = window.location.pathname.match(/\/results\/(\d+)/);
    if (pathMatch) {
      assessmentId = pathMatch[1];
    }
  }

  let assessmentData = null;
  const cachedJson = sessionStorage.getItem("lastAssessment");

  // Always fetch fresh data from GET /api/assessments/<id> if assessmentId exists
  if (assessmentId) {
    try {
      const res = await fetch(`/api/assessments/${assessmentId}`);
      if (res.ok) {
        const fetchedData = await res.json();
        if (cachedJson) {
          try {
            const parsed = JSON.parse(cachedJson);
            if (String(parsed.assessment_id) === String(assessmentId)) {
              // Merge cached rich info (warnings, suggested_checks) with fresh DB records
              assessmentData = { ...parsed, ...fetchedData };
            } else {
              assessmentData = fetchedData;
            }
          } catch (e) {
            assessmentData = fetchedData;
          }
        } else {
          assessmentData = fetchedData;
        }
      }
    } catch (err) {
      console.warn("Failed to fetch assessment from API", err);
    }
  }

  // Fallback to cachedJson if fetch did not populate assessmentData
  if (!assessmentData && cachedJson) {
    try {
      const parsed = JSON.parse(cachedJson);
      if (!assessmentId || String(parsed.assessment_id) === String(assessmentId)) {
        assessmentData = parsed;
      }
    } catch (e) {
      console.warn("Failed to parse cached assessment", e);
    }
  }

  // If still no assessment, show empty state
  if (!assessmentData) {
    loading.style.display = "none";
    errorCard.style.display = "block";
    return;
  }

  // Render assessment data
  renderAssessment(assessmentData);
  loading.style.display = "none";
  content.style.display = "block";
}

function renderAssessment(data) {
  // Assessment ID and title
  const idEl = document.getElementById("assessmentIdLabel");
  const titleEl = document.getElementById("assessmentTitle");
  if (idEl) idEl.textContent = `Assessment ID: #${data.assessment_id || '--'}`;
  if (titleEl) titleEl.textContent = `Assessment #${data.assessment_id || '--'} Results`;

  // Locations
  const refLoc = data.reference_location || data.location_a || {};
  const tgtLoc = data.target_location || data.location_b || {};

  const locANameEl = document.getElementById("locAName");
  const locBNameEl = document.getElementById("locBName");
  const locACoordsEl = document.getElementById("locACoords");
  const locBCoordsEl = document.getElementById("locBCoords");

  if (locANameEl) locANameEl.textContent = refLoc.name || "Location A";
  if (locBNameEl) locBNameEl.textContent = tgtLoc.name || "Location B";

  if (locACoordsEl) {
    if (refLoc.latitude != null && refLoc.longitude != null) {
      locACoordsEl.textContent = `Lat: ${refLoc.latitude}, Lon: ${refLoc.longitude}`;
    } else {
      locACoordsEl.textContent = "Lat: --, Lon: --";
    }
  }

  if (locBCoordsEl) {
    if (tgtLoc.latitude != null && tgtLoc.longitude != null) {
      locBCoordsEl.textContent = `Lat: ${tgtLoc.latitude}, Lon: ${tgtLoc.longitude}`;
    } else {
      locBCoordsEl.textContent = "Lat: --, Lon: --";
    }
  }

  // Set adaptation tag from API
  const adaptTagEl = document.getElementById("adaptationTag");
  if (adaptTagEl) {
    const adaptName = data.adaptation_name || (data.adaptation_id ? data.adaptation_id.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : "Rain Garden");
    adaptTagEl.textContent = `${adaptName} Assessment`;
  }

  // 1. Status Banner
  renderStatusBanner(data.status, data);

  // Update header badge listing which factors are currently live, estimated or demo
  updateHeaderDataBadge(data);

  // 2. Screening Score
  renderScore(data.score, data.status, data);

  // 3. Factor Comparison Table
  renderFactorsTable(data.factors || []);

  // 4. Limiting Factors Panel
  renderListPanel(
    "limitingFactorsList",
    data.limiting_factors || [],
    "No limiting factors or transfer risks identified."
  );

  // 5. Suggested Checks Panel
  renderListPanel(
    "suggestedChecksList",
    data.suggested_checks || [],
    "No specific field checks suggested; standard maintenance applies."
  );

  // 6. Data Quality Warnings Panel
  renderListPanel(
    "dataQualityWarningsList",
    data.data_quality_warnings || [],
    "No data quality warnings; coverage and resolution were adequate."
  );

  // 7. Disclaimer
  if (data.disclaimer) {
    const discEl = document.getElementById("disclaimerText");
    if (discEl) discEl.textContent = `“${data.disclaimer}”`;
  }
}

/**
 * Render Large Status Banner
 */
function renderStatusBanner(status, data) {
  const banner = document.getElementById("statusBanner");
  const iconWrap = document.getElementById("statusIcon");
  const statusText = document.getElementById("statusText");
  const headline = document.getElementById("statusHeadline");
  const explanation = document.getElementById("statusExplanation");

  banner.className = "status-banner";

  const maxMissingPct = data?.max_missing_weight != null ? Math.round(data.max_missing_weight * 100) : 30;

  const configs = {
    "suitable": {
      cls: "status-suitable",
      badge: "SUITABLE",
      headline: "Intervention Appears Suitable for Transfer",
      explanation: "Key documented requirements appear met at the target site with no critical blockers or high transfer risks identified.",
      icon: `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`
    },
    "conditional": {
      cls: "status-conditional",
      badge: "CONDITIONAL",
      headline: "Conditions Need Verification Before Transfer",
      explanation: "Important criteria require engineering verification, non-critical thresholds are unmet, or significant divergence from Location A poses a transfer risk.",
      icon: `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`
    },
    "unsuitable": {
      cls: "status-unsuitable",
      badge: "UNSUITABLE",
      headline: "Transfer Unsuitable Due to Critical Blocker",
      explanation: "One or more critical documented requirements are unmet at the target site. Implementation is not recommended without major engineering controls.",
      icon: `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`
    },
    "insufficient_data": {
      cls: "status-insufficient",
      badge: "INSUFFICIENT DATA",
      headline: "Data Gaps Prevent Comprehensive Screening",
      explanation: `One or more critical parameters are unknown for the target site or missing factor weight exceeds the acceptable ${maxMissingPct}% threshold. Classification is withheld.`,
      icon: `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`
    }
  };

  const current = configs[status] || configs["insufficient_data"];
  banner.classList.add(current.cls);
  statusText.textContent = current.badge;
  headline.textContent = current.headline;
  explanation.textContent = current.explanation;
  iconWrap.innerHTML = current.icon;
}

/**
 * Render Screening Score
 */
function renderScore(score, status, data) {
  const scoreVal = document.getElementById("scoreValueDisplay");
  const scoreDesc = document.getElementById("scoreDescription");
  const maxMissingPct = data?.max_missing_weight != null ? Math.round(data.max_missing_weight * 100) : 30;

  if (score == null || status === "insufficient_data") {
    scoreVal.textContent = "--";
    scoreDesc.textContent = `Screening score is withheld when critical factors are unknown or missing data weight exceeds the ${maxMissingPct}% threshold.`;
  } else {
    const formatted = typeof score === "number" ? score.toFixed(2) : score;
    scoreVal.textContent = formatted;
    scoreDesc.textContent = `Calculated as the normalized weighted average of evaluated factors (${(score * 100).toFixed(0)}%). A high score cannot override an unmet critical blocker.`;
  }
}

/**
 * Render Factor Comparison Table
 */
function renderFactorsTable(factors) {
  const tbody = document.getElementById("factorsTableBody");
  if (!tbody) return;

  tbody.innerHTML = "";

  factors.forEach(f => {
    const label = f.factor.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

    const srcA = f.a_source || (f.a_value != null ? (f.source || "Demo value") : "");
    const resA = f.a_resolution || (f.a_value != null ? (f.resolution || "n/a (demo)") : "");
    const srcB = f.b_source || f.source || "Demo value";
    const resB = f.b_resolution || f.resolution || "n/a (demo)";

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

    const subA = (f.a_value != null && srcA) ? `<div class="preview-val-prov ${provClassA}">${escapeHtml(labelA)} &bull; ${escapeHtml(resA)}</div>` : "";
    const subB = (f.b_value != null && srcB) ? `<div class="preview-val-prov ${provClassB}">${escapeHtml(labelB)} &bull; ${escapeHtml(resB)}</div>` : "";

    const valA = f.a_value != null ? `<div><strong>${f.a_value}</strong></div>${subA}` : `<span class="badge-unknown">Unknown</span>`;
    const valB = f.b_value != null ? `<div><strong>${f.b_value}</strong></div>${subB}` : `<span class="badge-unknown">Unknown</span>`;

    // Status pill
    let statusBadge = "";
    if (f.factor_status === "met") {
      statusBadge = `<span class="status-pill-met">Met</span>`;
    } else if (f.factor_status === "unmet") {
      statusBadge = `<span class="status-pill-unmet">Unmet</span>`;
    } else {
      statusBadge = `<span class="status-pill-unknown">Unknown</span>`;
    }

    // Transfer risk badge
    let riskBadge = "";
    if (f.transfer_risk) {
      riskBadge = `<br><span class="risk-flag-tag">Transfer Risk</span>`;
    }

    // Provenance (source / resolution)
    const isLive = isSpecialB || isSpecialA;
    const displaySrc = isSpecialB ? labelB : (isSpecialA ? labelA : "Demo value");
    const displayRes = isSpecialB ? resB : (isSpecialA ? resA : (f.resolution || "n/a (demo)"));
    const prov = `<div class="table-prov-text">Source: ${escapeHtml(displaySrc)} &bull; Res: ${escapeHtml(displayRes)}</div>`;

    const row = document.createElement("tr");
    row.innerHTML = `
      <td><strong>${label}</strong></td>
      <td class="col-center">${valA}</td>
      <td class="col-center">${valB}</td>
      <td>
        <span>${escapeHtml(f.requirement || '')}</span>
      </td>
      <td class="col-center">
        ${statusBadge}
        ${riskBadge}
      </td>
      <td>
        <div>${escapeHtml(f.interpretation || '')}</div>
        ${prov}
      </td>
    `;
    tbody.appendChild(row);
  });
}

/**
 * Render Diagnostic Panels (Lists)
 */
function renderListPanel(elementId, items, emptyText) {
  const listEl = document.getElementById(elementId);
  if (!listEl) return;

  listEl.innerHTML = "";

  if (!items || items.length === 0) {
    const li = document.createElement("li");
    li.className = "empty-list-notice";
    li.textContent = emptyText;
    listEl.appendChild(li);
    return;
  }

  items.forEach(item => {
    const li = document.createElement("li");
    li.innerHTML = escapeHtml(item);
    listEl.appendChild(li);
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[m]);
}

function updateHeaderDataBadge(data) {
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

  const factors = (data && data.factors) ? data.factors : [];
  const allKeys = ["annual_rainfall", "slope", "soil_infiltration", "open_space", "building_distance"];
  allKeys.forEach(k => {
    const f = factors.find(item => item.factor === k);
    const srcA = f?.a_source || "";
    const srcB = f?.b_source || f?.source || "";
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

  const resBadgeText = document.getElementById("resultsPageBadgeText");
  if (resBadgeText) resBadgeText.textContent = text;

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
