"""
Pytest configuration and global fixtures for ADAPTFIT test suite.
"""

import pytest

from config import Config


@pytest.fixture(autouse=True)
def force_live_flags_off_by_default(monkeypatch):
    """
    Force all live flags off by default across the test suite,
    ensuring standard tests run against predictable sample CSV data
    even when live flags are set in the shell environment.
    Tests specifically targeting live sources will explicitly enable them.
    """
    monkeypatch.setenv("USE_LIVE_RAINFALL", "false")
    monkeypatch.setattr(Config, "USE_LIVE_RAINFALL", False)
    monkeypatch.setenv("USE_LIVE_SLOPE", "false")
    monkeypatch.setattr(Config, "USE_LIVE_SLOPE", False)
    monkeypatch.setenv("USE_LIVE_SOIL", "false")
    monkeypatch.setattr(Config, "USE_LIVE_SOIL", False)
    monkeypatch.setenv("USE_LIVE_OSM", "false")
    monkeypatch.setattr(Config, "USE_LIVE_OSM", False)


# Keep backwards-compatible alias in case any test or fixture references it
force_live_rainfall_off_by_default = force_live_flags_off_by_default
