"""Integration tests for OctoGenEngine._handle_missing_track threshold wiring.

Constructs a bare engine via __new__ to bypass network-heavy __init__, then
wires only the attributes _handle_missing_track touches.
"""

from unittest.mock import MagicMock

import pytest

from octogen.main import OctoGenEngine
from octogen.storage.cache import RatingsCache


def _engine_with(cache, lidarr=None, octo=None, min_missing=3):
    engine = OctoGenEngine.__new__(OctoGenEngine)
    engine.ratings_cache = cache
    engine.lidarr = lidarr
    engine.octo = octo
    engine.config = {"lidarr": {"min_missing": min_missing}}
    engine.stats = {"lidarr_added": 0, "lidarr_below_threshold": 0, "fiesta_skipped": 0}
    return engine


@pytest.fixture
def cache(tmp_path):
    return RatingsCache(tmp_path / "test.db")


def test_below_threshold_increments_counter_no_lidarr_call(cache):
    lidarr = MagicMock()
    engine = _engine_with(cache, lidarr=lidarr, min_missing=3)

    engine._handle_missing_track("Foo Fighters", "Everlong")

    assert engine.stats["lidarr_below_threshold"] == 1
    assert engine.stats["lidarr_added"] == 0
    lidarr.add_artist.assert_not_called()


def test_at_threshold_pushes_to_lidarr_and_marks_pushed(cache):
    lidarr = MagicMock()
    lidarr.add_artist.return_value = (True, "added")
    engine = _engine_with(cache, lidarr=lidarr, min_missing=3)

    for _ in range(3):
        engine._handle_missing_track("Foo Fighters", "Everlong")

    lidarr.add_artist.assert_called_once_with("Foo Fighters")
    assert engine.stats["lidarr_added"] == 1
    assert cache.get_pending_pushes(threshold=3) == []


def test_lidarr_disabled_skips_bridge_entirely(cache):
    engine = _engine_with(cache, lidarr=None, min_missing=3)

    for _ in range(5):
        engine._handle_missing_track("Foo Fighters", "Everlong")

    assert engine.stats["lidarr_added"] == 0
    assert engine.stats["lidarr_below_threshold"] == 0


def test_lidarr_failure_does_not_mark_pushed_or_count_added(cache):
    lidarr = MagicMock()
    lidarr.add_artist.return_value = (False, "HTTP 500")
    engine = _engine_with(cache, lidarr=lidarr, min_missing=3)

    for _ in range(3):
        engine._handle_missing_track("Foo Fighters", "Everlong")

    lidarr.add_artist.assert_called_once()
    assert engine.stats["lidarr_added"] == 0
    assert cache.get_pending_pushes(threshold=3) == ["Foo Fighters"]


def test_octofiesta_disabled_increments_skip_counter(cache):
    engine = _engine_with(cache, lidarr=None, octo=None, min_missing=3)

    success, msg = engine._handle_missing_track("Foo Fighters", "Everlong")

    assert success is False
    assert msg == "fiesta-disabled"
    assert engine.stats["fiesta_skipped"] == 1


def test_octofiesta_called_when_enabled(cache):
    octo = MagicMock()
    octo.search_and_trigger_download.return_value = (True, "downloaded")
    engine = _engine_with(cache, lidarr=None, octo=octo, min_missing=3)

    success, msg = engine._handle_missing_track("Foo Fighters", "Everlong")

    octo.search_and_trigger_download.assert_called_once_with("Foo Fighters", "Everlong")
    assert success is True
    assert engine.stats["fiesta_skipped"] == 0
