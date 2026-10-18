"""
ADAPTFIT Compatibility Engine
=============================
Implements TRD Section 6 (pseudocode and specification) verbatim.

Design principles:
- No Flask dependency; runs standalone for unit testing.
- No machine learning. Logic is explicit rules + weighted scoring only.
- Missing values (None) are never invented; stored and surfaced as "Unknown".
- Critical blockers override the weighted score (PRD §7, TRD §6).
- Status decision order: Insufficient data → Unsuitable → Conditional → Suitable.

Transfer-tolerance type (stored in Requirement.tolerance_type, mirrors schema/seed):
  "relative" → flag when |B − A| > tolerance × |A|
  "absolute" → flag when |B − A| > tolerance
  None       → no transfer-risk check for this factor

All rule thresholds originate from seed data marked "candidate, unverified"
and MUST be labelled as such wherever results are displayed (PRD FR-14, §8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #

DISCLAIMER: str = (
    "ADAPTFIT is a preliminary, explainable decision-support prototype. "
    "It compares documented adaptation requirements with available environmental "
    "data for reference and target locations. Results depend on data coverage, "
    "spatial resolution and the quality of the requirements; they are not a "
    "guarantee of implementation success."
)


# --------------------------------------------------------------------------- #
# Data classes                                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class Requirement:
    """One row from adaptation_requirements, materialised as a Python object."""
    factor: str
    min_value: Optional[float]
    max_value: Optional[float]
    unit: str = ""
    weight: float = 1.0
    is_critical: bool = False
    transfer_tolerance: Optional[float] = None
    tolerance_type: Optional[str] = None   # "relative" | "absolute" | None
    evidence: str = ""
    rule_version: str = ""


@dataclass
class FactorResult:
    """Per-factor evaluation output."""
    factor: str
    a_value: Optional[float]
    b_value: Optional[float]
    requirement_summary: str       # human-readable threshold description
    factor_status: str             # "met" | "unmet" | "unknown"
    transfer_risk: bool            # True when |B − A| exceeds tolerance
    interpretation: str            # plain-language sentence for the UI
    normalised_score: Optional[float]  # s_i in [0, 1], or None when unknown


@dataclass
class AssessmentResult:
    """Full output returned by assess()."""
    status: str                    # "suitable" | "conditional" | "unsuitable" | "insufficient_data"
    score: Optional[float]         # weighted S in [0, 1], or None when insufficient data
    factors: List[FactorResult]
    supporting_factors: List[str]  # factor names that are met and risk-free
    limiting_factors: List[str]    # factor names that are unmet, unknown, or risky
    suggested_checks: List[str]    # action items for the user
    data_quality_warnings: List[str]
    disclaimer: str = field(default=DISCLAIMER)


class EngineConfig:
    """
    Configurable engine thresholds.
    Both values are candidates and should be shown as such in the UI (TRD §6).
    """
    SUITABLE_MIN: float = 0.75     # candidate threshold – score >= this → Suitable
    MAX_MISSING_WEIGHT: float = 0.30  # TRD §6: unknown_weight / total_weight > 0.30 → Insufficient data


# --------------------------------------------------------------------------- #
# Internal helpers                                                             #
# --------------------------------------------------------------------------- #

def _requirement_summary(req: Requirement) -> str:
    """Return a short, human-readable requirement string, e.g. 'min 12.7 mm/hr'."""
    parts: List[str] = []
    if req.min_value is not None:
        parts.append(f"min {req.min_value} {req.unit}".strip())
    if req.max_value is not None:
        parts.append(f"max {req.max_value} {req.unit}".strip())
    if not parts:
        # Binary factor (both bounds are None)
        parts.append(f"present [{req.unit}]" if req.unit else "present (binary)")
    return ", ".join(parts)


def _in_range(value: float, req: Requirement) -> bool:
    """
    Return True when *value* satisfies the requirement.

    Special case – binary factor (both min and max are None):
        value >= 1.0 → True (present / met)
        value <  1.0 → False (absent / unmet)
    """
    if req.min_value is None and req.max_value is None:
        return value >= 1.0          # binary convention

    if req.min_value is not None and value < req.min_value:
        return False
    if req.max_value is not None and value > req.max_value:
        return False
    return True


def _normalise(value: float, req: Requirement) -> float:
    """
    Return s_i in [0, 1].
      1.0 = well within the documented requirement
      0.0 = clearly outside

    For factors that are within range, s_i = 1.0.
    For out-of-range factors a proportional partial score is given so the
    weighted average is still informative; the status field ("unmet") is the
    authoritative signal for the user.
    """
    if _in_range(value, req):
        return 1.0

    # Partial-credit logic for out-of-range values
    if req.min_value is None and req.max_value is None:
        # Binary, absent
        return 0.0

    if req.min_value is not None and value < req.min_value:
        # Below minimum
        return max(0.0, value / req.min_value) if req.min_value != 0 else 0.0

    if req.max_value is not None and value > req.max_value:
        # Above maximum
        return max(0.0, req.max_value / value) if value != 0 else 0.0

    return 0.0  # unreachable but defensive


def _is_transfer_risk(
    a_value: Optional[float],
    b_value: Optional[float],
    tolerance: Optional[float],
    tolerance_type: Optional[str] = None,
) -> bool:
    """
    Return True when the A→B difference exceeds transfer_tolerance.

    tolerance_type:
      "relative" → flag when |B − A| > tolerance × |A|
      "absolute" → flag when |B − A| > tolerance
      None       → no check (returns False)
    """
    if a_value is None or b_value is None or tolerance is None:
        return False

    if not tolerance_type:
        return False

    diff = abs(b_value - a_value)

    tt = tolerance_type.lower().strip()
    if tt == "relative":
        return diff > tolerance * abs(a_value) if a_value != 0 else diff > 0
    if tt == "absolute":
        return diff > tolerance
    return False


def _build_interpretation(
    factor: str,
    b_value: Optional[float],
    req: Requirement,
    status: str,
    risk: bool,
) -> tuple[str, List[str]]:
    """
    Return (plain-language sentence, list of suggested checks) for one factor.
    Produces sentences matching the example in TRD §6 ("Slope at B is …").
    """
    checks: List[str] = []
    summary = _requirement_summary(req)
    label = factor.replace("_", " ").title()
    crit_note = " (critical)" if req.is_critical else ""
    risk_note = (
        " Transfer risk: value differs notably from the reference site; "
        "verify local context."
        if risk
        else ""
    )

    if status == "unknown":
        sentence = (
            f"{label} at Location B is unknown. "
            f"Requirement: {summary}{crit_note}. "
            "Retrieve or measure this value before proceeding."
        )
        checks.append(f"Obtain {label.lower()} data for Location B.")

    elif status == "unmet":
        sentence = (
            f"{label} at Location B is {b_value} {req.unit}, "
            f"outside the documented requirement ({summary}){crit_note}.{risk_note}"
        )
        checks.append(
            f"Verify {label.lower()} at Location B; requirement is {summary}."
        )

    else:  # "met"
        sentence = (
            f"{label} at Location B is {b_value} {req.unit}, "
            f"within the documented requirement ({summary}).{risk_note}"
        )
        if risk:
            checks.append(
                f"{label} differs from the reference site; "
                "confirm that local conditions support the adaptation."
            )

    return sentence, checks


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

def assess(
    requirements: List[Requirement],
    profile_a: Dict[str, Optional[float]],
    profile_b: Dict[str, Optional[float]],
    cfg: Optional[EngineConfig] = None,
) -> AssessmentResult:
    """
    Run the compatibility assessment following TRD Section 6 pseudocode exactly.

    Args:
        requirements: Adaptation requirements from the knowledge base.
        profile_a:    Factor → value mapping for Location A (None = unknown).
        profile_b:    Factor → value mapping for Location B (None = unknown).
        cfg:          Engine thresholds; uses defaults when None.

    Returns:
        AssessmentResult with status, score, per-factor results, and explanations.

    Status decision order (TRD §6):
        1. Insufficient data – any critical factor unknown for B, OR
                               unknown_weight / total_weight > MAX_MISSING_WEIGHT
        2. Unsuitable        – any critical factor unmet
        3. Conditional       – any factor unknown / unmet (non-critical) / transfer_risk,
                               OR score < SUITABLE_MIN
        4. Suitable          – none of the above
    """
    if cfg is None:
        cfg = EngineConfig()

    factor_results: List[FactorResult] = []
    total_w = known_w = unknown_w = weighted_sum = 0.0
    critical_unknown = False
    critical_unmet = False
    data_quality_warnings: List[str] = []
    suggested_checks_raw: List[str] = []

    # ------------------------------------------------------------------ #
    # Per-factor evaluation (TRD §6 pseudocode)                           #
    # ------------------------------------------------------------------ #
    for req in requirements:
        total_w += req.weight
        b = profile_b.get(req.factor)
        a = profile_a.get(req.factor)

        if b is None:
            # Unknown value for Location B
            status = "unknown"
            unknown_w += req.weight
            if req.is_critical:
                critical_unknown = True
            s_i: Optional[float] = None
            data_quality_warnings.append(
                f"{req.factor.replace('_', ' ').title()} data is missing for Location B."
            )
        else:
            status = "met" if _in_range(b, req) else "unmet"
            if status == "unmet" and req.is_critical:
                critical_unmet = True
            s_i = _normalise(b, req)
            weighted_sum += req.weight * s_i
            known_w += req.weight

        risk = _is_transfer_risk(a, b, req.transfer_tolerance, req.tolerance_type)

        # Warn when Location A's value is None but B's is known
        if a is None and b is not None:
            label = req.factor.replace("_", " ").title()
            data_quality_warnings.append(
                f"{label} reference value for Location A is unknown, "
                "so transfer risk could not be checked."
            )

        interpretation, checks = _build_interpretation(req.factor, b, req, status, risk)
        suggested_checks_raw.extend(checks)

        factor_results.append(
            FactorResult(
                factor=req.factor,
                a_value=a,
                b_value=b,
                requirement_summary=_requirement_summary(req),
                factor_status=status,
                transfer_risk=risk,
                interpretation=interpretation,
                normalised_score=s_i,
            )
        )

    # ------------------------------------------------------------------ #
    # Status decision (TRD §6, evaluated in this order)                  #
    # ------------------------------------------------------------------ #
    missing_ratio = unknown_w / total_w if total_w > 0 else 0.0

    if critical_unknown or missing_ratio > cfg.MAX_MISSING_WEIGHT:
        overall = "insufficient_data"
        score: Optional[float] = None
        if critical_unknown:
            data_quality_warnings.append(
                "One or more critical factors are unknown for Location B; "
                "a compatibility classification cannot be made."
            )
        if missing_ratio > cfg.MAX_MISSING_WEIGHT:
            threshold_pct = f"{int(round(cfg.MAX_MISSING_WEIGHT * 100))} %"
            data_quality_warnings.append(
                f"Unknown factor weight ({missing_ratio:.0%}) exceeds the "
                f"{threshold_pct} threshold; "
                "the result would be unreliable – classification withheld."
            )

    elif critical_unmet:
        overall = "unsuitable"
        score = weighted_sum / known_w if known_w > 0 else None

    else:
        score = weighted_sum / known_w if known_w > 0 else None
        needs_check = any(
            fr.factor_status != "met" or fr.transfer_risk for fr in factor_results
        )
        overall = (
            "conditional"
            if needs_check or (score is not None and score < cfg.SUITABLE_MIN)
            else "suitable"
        )

    # ------------------------------------------------------------------ #
    # Supporting / limiting factor lists                                  #
    # ------------------------------------------------------------------ #
    supporting = [
        fr.factor
        for fr in factor_results
        if fr.factor_status == "met" and not fr.transfer_risk
    ]
    limiting = [
        fr.factor
        for fr in factor_results
        if fr.factor_status in ("unmet", "unknown") or fr.transfer_risk
    ]

    # Deduplicate suggested checks while preserving order
    seen: set = set()
    unique_checks: List[str] = []
    for c in suggested_checks_raw:
        if c not in seen:
            seen.add(c)
            unique_checks.append(c)

    seen_w: set = set()
    unique_warnings: List[str] = []
    for w in data_quality_warnings:
        if w not in seen_w:
            seen_w.add(w)
            unique_warnings.append(w)

    return AssessmentResult(
        status=overall,
        score=score,
        factors=factor_results,
        supporting_factors=supporting,
        limiting_factors=limiting,
        suggested_checks=unique_checks,
        data_quality_warnings=unique_warnings,
    )
