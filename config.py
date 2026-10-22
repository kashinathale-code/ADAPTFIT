"""
ADAPTFIT configuration.

All secrets and deployment-specific values are loaded from environment variables.
Never put API keys or passwords directly in this file or in the repository.
"""

import os


class Config:
    # ------------------------------------------------------------------ #
    # Database                                                             #
    DATABASE_PATH: str = os.environ.get(
        "DATABASE_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "adaptfit.db"),
    )

    # ------------------------------------------------------------------ #
    # Compatibility engine thresholds                                      #
    # Both values are documented as configurable candidates (TRD §6).     #
    # ------------------------------------------------------------------ #
    SUITABLE_MIN: float = float(os.environ.get("SUITABLE_MIN", "0.75"))
    # ^ candidate threshold: score >= SUITABLE_MIN → Suitable
    MAX_MISSING_WEIGHT: float = float(os.environ.get("MAX_MISSING_WEIGHT", "0.30"))
    # ^ per TRD §6: unknown_weight / total_weight > 0.30 → Insufficient data

    # ------------------------------------------------------------------ #
    # Live data flags                                                      #
    # ------------------------------------------------------------------ #
    USE_LIVE_RAINFALL: bool = os.environ.get("USE_LIVE_RAINFALL", "false").lower() == "true"
    USE_LIVE_SLOPE: bool = os.environ.get("USE_LIVE_SLOPE", "false").lower() == "true"
    USE_LIVE_SOIL: bool = os.environ.get("USE_LIVE_SOIL", "false").lower() == "true"
    USE_LIVE_OSM: bool = os.environ.get("USE_LIVE_OSM", "false").lower() == "true"


    # ------------------------------------------------------------------ #
    # External HTTP requests                                               #
    # ------------------------------------------------------------------ #
    HTTP_USER_AGENT: str = os.environ.get(
        "HTTP_USER_AGENT",
        "ADAPTFIT/1.0 (Climate Adaptation Transferability Tool; https://github.com/adaptfit; contact: research@adaptfit.org)",
    )

    # ------------------------------------------------------------------ #
    # Caching                                                              #
    # ------------------------------------------------------------------ #
    CACHE_STALENESS_HOURS: int = int(os.environ.get("CACHE_STALENESS_HOURS", "24"))

    # ------------------------------------------------------------------ #
    # Flask                                                                #
    # ------------------------------------------------------------------ #
    DEBUG: bool = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "change-me-in-production")
