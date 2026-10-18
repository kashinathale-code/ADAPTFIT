"""
tests/test_compatibility.py

Unit tests for backend/compatibility_engine.py.
All tests run without network access, a database, or Flask.

Test cases correspond to TRD §11 (Testing Plan):
  TC-1  Both locations have complete, in-range data         → Suitable; all factors explained
  TC-2  A critical factor is missing for Location B         → Insufficient data
  TC-3  >30 % of total weight is unknown for B              → Insufficient data
  TC-4  Critical requirement unmet; all others pass         → Unsuitable (blocker override)
  TC-5  A and B profiles are very similar                   → no transfer-risk flags
  TC-6  Non-critical factor unmet; critical factors met     → Conditional
"""

import pytest

from backend.compatibility_engine import (
    EngineConfig,
    Requirement,
    assess,
)


# =========================================================================== #
# Shared fixtures                                                              #
# =========================================================================== #

@pytest.fixture()
def reqs() -> list[Requirement]:
    """
    Rain Garden requirements mirroring database/seed.py exactly.

    tolerance_type:
      "relative" → flag when |B − A| > tolerance × |A|
      "absolute" → flag when |B − A| > tolerance
      None       → no transfer-risk check
    """
    return [
        Requirement(
            factor="soil_infiltration",
            min_value=12.7, max_value=None, unit="mm/hr",
            weight=0.35, is_critical=True, transfer_tolerance=0.50,
            tolerance_type="relative",
            evidence="candidate, unverified", rule_version="v0.1-candidate",
        ),
        Requirement(
            factor="slope",
            min_value=None, max_value=8.0, unit="%",
            weight=0.25, is_critical=True, transfer_tolerance=3.0,
            tolerance_type="absolute",
            evidence="candidate, unverified", rule_version="v0.1-candidate",
        ),
        Requirement(
            factor="annual_rainfall",
            min_value=600.0, max_value=2500.0, unit="mm/yr",
            weight=0.15, is_critical=False, transfer_tolerance=0.30,
            tolerance_type="relative",
            evidence="candidate, unverified", rule_version="v0.1-candidate",
        ),
        Requirement(
            factor="open_space",
            min_value=None, max_value=None, unit="binary (1=present, 0=absent)",
            weight=0.15, is_critical=False, transfer_tolerance=None,
            tolerance_type=None,
            evidence="candidate, unverified", rule_version="v0.1-candidate",
        ),
        Requirement(
            factor="building_distance",
            min_value=3.0, max_value=None, unit="m",
            weight=0.10, is_critical=False, transfer_tolerance=None,
            tolerance_type=None,
            evidence="candidate, unverified", rule_version="v0.1-candidate",
        ),
    ]


@pytest.fixture()
def cfg() -> EngineConfig:
    return EngineConfig()


# Convenient complete, in-range profiles (A and B very similar)
_PROFILE_A_GOOD = {
    "soil_infiltration": 30.0,
    "slope": 3.0,
    "annual_rainfall": 1200.0,
    "open_space": 1.0,
    "building_distance": 5.0,
}

_PROFILE_B_GOOD = {
    "soil_infiltration": 28.0,   # |28-30|/30 = 6.7 % < 50 % → no risk
    "slope": 4.0,                # |4-3| = 1 < 3 abs → no risk
    "annual_rainfall": 1100.0,   # |1100-1200|/1200 = 8.3 % < 30 % → no risk
    "open_space": 1.0,
    "building_distance": 6.0,
}


# =========================================================================== #
# TC-1  Complete data – all factors known and within range                     #
# =========================================================================== #

class TestCompleteData:
    """TC-1: Both locations have complete data → valid status, all factors explained."""

    def test_status_is_suitable(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_B_GOOD, cfg)
        assert result.status == "suitable", (
            f"Expected 'suitable', got '{result.status}'. "
            f"Limiting factors: {result.limiting_factors}"
        )

    def test_all_five_factors_present(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_B_GOOD, cfg)
        assert len(result.factors) == 5

    def test_every_factor_has_interpretation(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_B_GOOD, cfg)
        for fr in result.factors:
            assert fr.interpretation, f"Empty interpretation for factor '{fr.factor}'"

    def test_every_factor_has_requirement_summary(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_B_GOOD, cfg)
        for fr in result.factors:
            assert fr.requirement_summary, (
                f"Empty requirement_summary for factor '{fr.factor}'"
            )

    def test_score_between_0_and_1(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_B_GOOD, cfg)
        assert result.score is not None
        assert 0.0 <= result.score <= 1.0, f"Score out of bounds: {result.score}"

    def test_no_limiting_factors(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_B_GOOD, cfg)
        assert result.limiting_factors == [], (
            f"Unexpected limiting factors: {result.limiting_factors}"
        )

    def test_all_factors_are_supporting(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_B_GOOD, cfg)
        factor_names = {r.factor for r in reqs}
        assert set(result.supporting_factors) == factor_names

    def test_disclaimer_present(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_B_GOOD, cfg)
        assert result.disclaimer and len(result.disclaimer) > 0

    def test_no_data_quality_warnings(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_B_GOOD, cfg)
        assert result.data_quality_warnings == []


# =========================================================================== #
# TC-2  Missing critical factor                                                #
# =========================================================================== #

class TestMissingCriticalFactor:
    """TC-2: A critical factor is missing for Location B → Insufficient data."""

    def test_soil_infiltration_missing_gives_insufficient(self, reqs, cfg):
        profile_b = {**_PROFILE_B_GOOD, "soil_infiltration": None}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.status == "insufficient_data"

    def test_slope_missing_gives_insufficient(self, reqs, cfg):
        profile_b = {**_PROFILE_B_GOOD, "slope": None}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.status == "insufficient_data"

    def test_score_is_none_when_insufficient(self, reqs, cfg):
        profile_b = {**_PROFILE_B_GOOD, "soil_infiltration": None}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.score is None

    def test_data_quality_warning_mentions_critical(self, reqs, cfg):
        profile_b = {**_PROFILE_B_GOOD, "soil_infiltration": None}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        all_warnings = " ".join(result.data_quality_warnings).lower()
        assert "critical" in all_warnings, (
            f"Expected 'critical' in warnings; got: {result.data_quality_warnings}"
        )

    def test_missing_factor_in_factor_results_as_unknown(self, reqs, cfg):
        profile_b = {**_PROFILE_B_GOOD, "slope": None}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        slope_result = next(fr for fr in result.factors if fr.factor == "slope")
        assert slope_result.factor_status == "unknown"
        assert slope_result.normalised_score is None

    def test_suggested_check_exists_for_unknown_factor(self, reqs, cfg):
        profile_b = {**_PROFILE_B_GOOD, "soil_infiltration": None}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert any("soil infiltration" in c.lower() for c in result.suggested_checks), (
            f"No suggested check for missing soil_infiltration; got: {result.suggested_checks}"
        )


# =========================================================================== #
# TC-3  >30 % of weight unknown (no critical factor missing)                  #
# =========================================================================== #

class TestMissingWeightExceeds30Pct:
    """TC-3: >30 % of total weight unknown → Insufficient data."""

    def test_40pct_unknown_gives_insufficient(self, reqs, cfg):
        """
        annual_rainfall (0.15) + open_space (0.15) + building_distance (0.10) = 0.40
        Both critical factors known and met → triggered by weight rule, not critical_unknown.
        """
        profile_b = {
            "soil_infiltration": 25.0,   # met, critical – known
            "slope": 4.0,                # met, critical – known
            "annual_rainfall": None,     # 0.15
            "open_space": None,          # 0.15
            "building_distance": None,   # 0.10   total unknown = 0.40 > 0.30
        }
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.status == "insufficient_data"

    def test_warning_mentions_missing_weight_threshold(self, reqs, cfg):
        profile_b = {
            "soil_infiltration": 25.0,
            "slope": 4.0,
            "annual_rainfall": None,
            "open_space": None,
            "building_distance": None,
        }
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        combined = " ".join(result.data_quality_warnings).lower()
        assert "30" in combined or "threshold" in combined, (
            f"Expected 30 %/threshold in warnings; got: {result.data_quality_warnings}"
        )

    def test_exactly_30pct_missing_is_not_insufficient(self, reqs, cfg):
        """
        annual_rainfall (0.15) + open_space (0.15) = 0.30.
        Condition is strictly >0.30, so this should NOT give insufficient_data.
        """
        profile_b = {
            "soil_infiltration": 25.0,
            "slope": 4.0,
            "annual_rainfall": None,    # 0.15
            "open_space": None,         # 0.15  → total = 0.30, NOT > 0.30
            "building_distance": 5.0,
        }
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.status != "insufficient_data", (
            "Exactly 30 % missing should NOT trigger insufficient_data "
            f"(condition is strictly >30 %); got status: {result.status}"
        )


# =========================================================================== #
# TC-4  Critical requirement unmet – score is high → Unsuitable               #
# =========================================================================== #

class TestCriticalBlockerOverride:
    """TC-4: Critical requirement unmet → Unsuitable, even when score is high."""

    def test_low_soil_infiltration_is_unsuitable(self, reqs, cfg):
        """
        soil_infiltration B=5.0 < min 12.7 (critical, unmet).
        All other factors met → without blocker, score would be ~0.92.
        Blocker must override to Unsuitable.
        """
        profile_b = {**_PROFILE_B_GOOD, "soil_infiltration": 5.0}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.status == "unsuitable", (
            f"Critical blocker must give 'unsuitable'; got '{result.status}' "
            f"(score={result.score})"
        )

    def test_score_still_computed_for_unsuitable(self, reqs, cfg):
        """Score is reported even for Unsuitable so users see the partial picture."""
        profile_b = {**_PROFILE_B_GOOD, "soil_infiltration": 5.0}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.score is not None, "Score should be computed for Unsuitable"

    def test_score_below_1_with_critical_unmet(self, reqs, cfg):
        """Score should be <1.0 because the unmet factor contributes partial credit ≤1."""
        profile_b = {**_PROFILE_B_GOOD, "soil_infiltration": 5.0}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.score < 1.0

    def test_unmet_critical_factor_in_limiting_factors(self, reqs, cfg):
        profile_b = {**_PROFILE_B_GOOD, "soil_infiltration": 5.0}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert "soil_infiltration" in result.limiting_factors

    def test_slope_critical_unmet_is_also_unsuitable(self, reqs, cfg):
        """slope=15 % > max 8 % (critical). Should be Unsuitable."""
        profile_b = {**_PROFILE_B_GOOD, "slope": 15.0}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.status == "unsuitable"

    def test_high_score_does_not_prevent_unsuitable(self, reqs, cfg):
        """
        Explicitly verify the score is above SUITABLE_MIN while status is Unsuitable.
        This proves the blocker override, not just a low score.
        """
        profile_b = {
            "soil_infiltration": 10.0,  # below 12.7 (critical, unmet); s_i ≈ 0.79
            "slope": 3.0,               # met
            "annual_rainfall": 1200.0,  # met
            "open_space": 1.0,          # met
            "building_distance": 5.0,   # met
        }
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        # Weighted score: soil contributes 0.35×(10/12.7)≈0.276; others 0.65×1≈0.65 → ~0.93
        assert result.status == "unsuitable"
        assert result.score is not None and result.score > cfg.SUITABLE_MIN, (
            f"Score {result.score} should be above SUITABLE_MIN {cfg.SUITABLE_MIN} "
            "to prove the blocker is overriding a good score"
        )


# =========================================================================== #
# TC-5  Similar profiles → no transfer-risk flags                             #
# =========================================================================== #

class TestSimilarProfiles:
    """TC-5: A and B are similar → transfer_risk=False for every factor."""

    def test_identical_profiles_no_transfer_risk(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_A_GOOD.copy(), cfg)
        for fr in result.factors:
            assert not fr.transfer_risk, (
                f"Unexpected transfer_risk on factor '{fr.factor}' with identical profiles"
            )

    def test_slightly_different_within_tolerance_no_risk(self, reqs, cfg):
        """Differences well inside tolerance must not trigger transfer_risk."""
        profile_b = {
            "soil_infiltration": 31.0,  # |31-30|/30 = 3.3 % < 50 %
            "slope": 3.5,               # |3.5-3| = 0.5 < 3 abs
            "annual_rainfall": 1250.0,  # |1250-1200|/1200 = 4.2 % < 30 %
            "open_space": 1.0,          # no tolerance
            "building_distance": 5.5,   # no tolerance
        }
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        for fr in result.factors:
            assert not fr.transfer_risk, (
                f"Unexpected transfer_risk on '{fr.factor}' with in-tolerance values"
            )

    def test_identical_profiles_are_suitable(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_A_GOOD.copy(), cfg)
        assert result.status == "suitable"


# =========================================================================== #
# TC-6  Non-critical factor unmet → Conditional                               #
# =========================================================================== #

class TestNonCriticalUnmet:
    """TC-6: A non-critical factor fails; critical factors met → Conditional."""

    def test_rainfall_below_min_gives_conditional(self, reqs, cfg):
        """annual_rainfall B=300 < min 600 (non-critical, unmet) → Conditional."""
        profile_b = {**_PROFILE_B_GOOD, "annual_rainfall": 300.0}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.status == "conditional", (
            f"Expected 'conditional'; got '{result.status}'"
        )

    def test_open_space_absent_gives_conditional(self, reqs, cfg):
        """open_space=0 (absent, non-critical, unmet) → Conditional."""
        profile_b = {**_PROFILE_B_GOOD, "open_space": 0.0}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.status == "conditional"

    def test_building_distance_below_min_gives_conditional(self, reqs, cfg):
        """building_distance B=2.0 < min 3.0 (non-critical, unmet) → Conditional."""
        profile_b = {**_PROFILE_B_GOOD, "building_distance": 2.0}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert result.status == "conditional"

    def test_unmet_non_critical_in_limiting_not_supporting(self, reqs, cfg):
        profile_b = {**_PROFILE_B_GOOD, "annual_rainfall": 300.0}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        assert "annual_rainfall" in result.limiting_factors
        assert "annual_rainfall" not in result.supporting_factors

    def test_critical_factors_still_met_in_conditional(self, reqs, cfg):
        """When status is Conditional due to non-critical unmet, critical factors are met."""
        profile_b = {**_PROFILE_B_GOOD, "annual_rainfall": 300.0}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        for fr in result.factors:
            if fr.factor in ("soil_infiltration", "slope"):
                assert fr.factor_status == "met", (
                    f"Critical factor '{fr.factor}' should be 'met'; got '{fr.factor_status}'"
                )

    def test_transfer_risk_alone_gives_conditional(self, reqs, cfg):
        """
        Transfer risk on a met factor should also push status to Conditional.
        soil_infiltration: B=50, A=30 → |50-30|/30 = 66.7 % > 50 % tolerance → risk
        (but B >= 12.7, so still 'met')
        """
        profile_b = {**_PROFILE_B_GOOD, "soil_infiltration": 50.0}
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, cfg)
        si_result = next(fr for fr in result.factors if fr.factor == "soil_infiltration")
        assert si_result.factor_status == "met"
        assert si_result.transfer_risk is True
        assert result.status == "conditional", (
            f"Transfer risk alone should give 'conditional'; got '{result.status}'"
        )


# =========================================================================== #
# TC-7  Location A unknown for factor with transfer tolerance                 #
# =========================================================================== #

class TestLocationAUnknownWarning:
    """When Location A's value is None but B's is known, warn about unchecked transfer risk."""

    def test_location_a_none_b_known_generates_warning(self, reqs, cfg):
        profile_a = {**_PROFILE_A_GOOD, "soil_infiltration": None}
        result = assess(reqs, profile_a, _PROFILE_B_GOOD, cfg)
        expected = (
            "Soil Infiltration reference value for Location A is unknown, "
            "so transfer risk could not be checked."
        )
        assert expected in result.data_quality_warnings

    def test_location_a_known_b_known_no_warning(self, reqs, cfg):
        result = assess(reqs, _PROFILE_A_GOOD, _PROFILE_B_GOOD, cfg)
        for w in result.data_quality_warnings:
            assert "reference value for Location A is unknown" not in w

    def test_both_locations_none_no_transfer_risk_warning(self, reqs, cfg):
        profile_a = {**_PROFILE_A_GOOD, "soil_infiltration": None}
        profile_b = {**_PROFILE_B_GOOD, "soil_infiltration": None}
        result = assess(reqs, profile_a, profile_b, cfg)
        assert not any(
            "Soil Infiltration reference value for Location A is unknown" in w
            for w in result.data_quality_warnings
        )

    def test_location_a_none_b_known_generates_warning_for_any_factor(self, reqs, cfg):
        profile_a = {**_PROFILE_A_GOOD, "open_space": None}
        result = assess(reqs, profile_a, _PROFILE_B_GOOD, cfg)
        expected = (
            "Open Space reference value for Location A is unknown, "
            "so transfer risk could not be checked."
        )
        assert expected in result.data_quality_warnings


# =========================================================================== #
# TC-8  Explicit tolerance_type ('relative', 'absolute', None)                #
# =========================================================================== #

class TestToleranceType:
    """Explicit tolerance_type configuration on Requirement."""

    def test_relative_tolerance_triggers_risk_when_exceeded(self, cfg):
        req = Requirement(
            factor="soil_infiltration",
            min_value=10.0,
            max_value=None,
            transfer_tolerance=0.20,  # 20 %
            tolerance_type="relative",
        )
        # A=100, B=125 -> |125 - 100| / 100 = 25 % > 20 % -> risk
        result = assess([req], {"soil_infiltration": 100.0}, {"soil_infiltration": 125.0}, cfg)
        assert result.factors[0].transfer_risk is True

    def test_relative_tolerance_within_bounds_no_risk(self, cfg):
        req = Requirement(
            factor="soil_infiltration",
            min_value=10.0,
            max_value=None,
            transfer_tolerance=0.20,  # 20 %
            tolerance_type="relative",
        )
        # A=100, B=115 -> |115 - 100| / 100 = 15 % < 20 % -> no risk
        result = assess([req], {"soil_infiltration": 100.0}, {"soil_infiltration": 115.0}, cfg)
        assert result.factors[0].transfer_risk is False

    def test_absolute_tolerance_triggers_risk_when_exceeded(self, cfg):
        req = Requirement(
            factor="slope",
            min_value=None,
            max_value=15.0,
            transfer_tolerance=2.0,  # 2 units
            tolerance_type="absolute",
        )
        # A=3.0, B=5.5 -> |5.5 - 3.0| = 2.5 > 2.0 -> risk
        result = assess([req], {"slope": 3.0}, {"slope": 5.5}, cfg)
        assert result.factors[0].transfer_risk is True

    def test_absolute_tolerance_within_bounds_no_risk(self, cfg):
        req = Requirement(
            factor="slope",
            min_value=None,
            max_value=15.0,
            transfer_tolerance=2.0,  # 2 units
            tolerance_type="absolute",
        )
        # A=3.0, B=4.5 -> |4.5 - 3.0| = 1.5 < 2.0 -> no risk
        result = assess([req], {"slope": 3.0}, {"slope": 4.5}, cfg)
        assert result.factors[0].transfer_risk is False

    def test_none_tolerance_type_never_triggers_risk(self, cfg):
        req = Requirement(
            factor="slope",
            min_value=None,
            max_value=15.0,
            transfer_tolerance=1.0,
            tolerance_type=None,
        )
        result = assess([req], {"slope": 3.0}, {"slope": 10.0}, cfg)
        assert result.factors[0].transfer_risk is False


# =========================================================================== #
# TC-9  Dynamic warning percentage from cfg.MAX_MISSING_WEIGHT                #
# =========================================================================== #

class TestDynamicMissingWeightWarning:
    """Warning text percentage is derived from cfg.MAX_MISSING_WEIGHT."""

    def test_warning_reflects_custom_max_missing_weight(self, reqs):
        custom_cfg = EngineConfig()
        custom_cfg.MAX_MISSING_WEIGHT = 0.20
        # annual_rainfall (0.15) + open_space (0.15) = 0.30 > 0.20
        profile_b = {
            "soil_infiltration": 25.0,
            "slope": 4.0,
            "annual_rainfall": None,
            "open_space": None,
            "building_distance": 5.0,
        }
        result = assess(reqs, _PROFILE_A_GOOD, profile_b, custom_cfg)
        assert result.status == "insufficient_data"
        combined = " ".join(result.data_quality_warnings)
        assert "20 %" in combined
        assert "30 %" not in combined

