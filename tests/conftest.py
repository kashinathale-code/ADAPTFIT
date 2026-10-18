"""
Pytest configuration and global fixtures for ADAPTFIT test suite.
"""

import pytest

from config import Config


@pytest.fixture(autouse=True)
def force_live_rainfall_off_by_default(monkeypatch):
    """
    Force USE_LIVE_RAINFALL off by default across the test suite,
    ensuring standard tests run against predictable sample CSV data
    even when USE_LIVE_RAINFALL is set in the shell environment.
    Tests specifically targeting live NASA POWER integration will
    explicitly enable the flag or pass use_live_rainfall=True.
    """
    monkeypatch.setenv("USE_LIVE_RAINFALL", "false")
    monkeypatch.setattr(Config, "USE_LIVE_RAINFALL", False)
