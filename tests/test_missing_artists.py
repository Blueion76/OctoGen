"""Tests for missing_artists tracking on RatingsCache."""

import sqlite3

import pytest

from octogen.storage.cache import RatingsCache


@pytest.fixture
def cache(tmp_path):
    return RatingsCache(tmp_path / "test.db")


class TestRecordMissingTrack:

    def test_first_record_returns_count_1(self, cache):
        assert cache.record_missing_track("Foo Fighters") == 1

    def test_second_record_increments(self, cache):
        cache.record_missing_track("Foo Fighters")
        assert cache.record_missing_track("Foo Fighters") == 2

    def test_normalization_case_insensitive(self, cache):
        cache.record_missing_track("Foo Fighters")
        assert cache.record_missing_track("foo fighters") == 2

    def test_normalization_strips_whitespace(self, cache):
        cache.record_missing_track("Foo Fighters")
        assert cache.record_missing_track("  Foo Fighters  ") == 2

    def test_display_name_preserves_first_seen_casing(self, cache, tmp_path):
        cache.record_missing_track("Foo Fighters")
        cache.record_missing_track("foo fighters")
        with sqlite3.connect(tmp_path / "test.db") as conn:
            row = conn.execute(
                "SELECT artist_display FROM missing_artists WHERE artist=?",
                ("foo fighters",),
            ).fetchone()
        assert row[0] == "Foo Fighters"


class TestMarkPushed:

    def test_mark_pushed_sets_timestamp(self, cache, tmp_path):
        cache.record_missing_track("Foo Fighters")
        cache.mark_pushed("Foo Fighters")
        with sqlite3.connect(tmp_path / "test.db") as conn:
            row = conn.execute(
                "SELECT pushed_to_lidarr FROM missing_artists WHERE artist=?",
                ("foo fighters",),
            ).fetchone()
        assert row[0] is not None

    def test_mark_pushed_idempotent(self, cache):
        cache.record_missing_track("Foo Fighters")
        cache.mark_pushed("Foo Fighters")
        cache.mark_pushed("Foo Fighters")  # must not raise


class TestGetPendingPushes:

    def test_returns_only_artists_at_or_above_threshold(self, cache):
        cache.record_missing_track("Below")
        cache.record_missing_track("AtThreshold")
        cache.record_missing_track("AtThreshold")
        cache.record_missing_track("AtThreshold")
        cache.record_missing_track("Above")
        cache.record_missing_track("Above")
        cache.record_missing_track("Above")
        cache.record_missing_track("Above")
        result = cache.get_pending_pushes(threshold=3)
        assert sorted(result) == sorted(["AtThreshold", "Above"])

    def test_excludes_already_pushed(self, cache):
        for _ in range(3):
            cache.record_missing_track("Foo Fighters")
        cache.mark_pushed("Foo Fighters")
        assert cache.get_pending_pushes(threshold=3) == []


class TestPushAttemptCap:

    def test_increment_push_attempt_returns_count(self, cache):
        cache.record_missing_track("Foo Fighters")
        assert cache.increment_push_attempt("Foo Fighters") == 1
        assert cache.increment_push_attempt("Foo Fighters") == 2

    def test_pending_excludes_after_max_attempts(self, cache):
        for _ in range(3):
            cache.record_missing_track("Foo Fighters")
        for _ in range(5):
            cache.increment_push_attempt("Foo Fighters")
        assert cache.get_pending_pushes(threshold=3, max_attempts=5) == []

    def test_pending_includes_below_max_attempts(self, cache):
        for _ in range(3):
            cache.record_missing_track("Foo Fighters")
        cache.increment_push_attempt("Foo Fighters")
        assert cache.get_pending_pushes(threshold=3, max_attempts=5) == ["Foo Fighters"]
