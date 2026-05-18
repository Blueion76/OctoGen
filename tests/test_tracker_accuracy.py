"""Regression tests for the time-of-day playlist tracker accuracy fix.

The bug: time-of-day playlist flow recorded service_tracker success based on
whether period_songs was non-empty, not on whether the Navidrome playlist was
actually created. When _process_recommendations finds zero library matches (and
downloads are disabled or fail), nd.create_playlist is never called, but the
tracker still reported "success: 1 playlist, N songs". The dashboard
/api/services tile showed the time-of-day service as healthy with no playlist.

The fix: switch to the counter-delta pattern (compare stats["playlists_created"]
before and after) and record success only when the counter incremented. The
failure branch records success=False with reason="No library matches..." and
includes the current_period so the dashboard tile shows the correct context.
"""

import re
from pathlib import Path

from octogen.models.tracker import ServiceTracker


class TestServiceTrackerPreservesPeriod:
    """ServiceTracker must preserve the period field on both success and failure."""

    def test_period_recorded_on_success(self):
        tracker = ServiceTracker()
        tracker.record(
            "timeofday_playlist",
            success=True,
            playlists=1,
            songs=20,
            period="evening",
        )
        assert tracker.services["timeofday_playlist"]["period"] == "evening"
        assert tracker.services["timeofday_playlist"]["success"] is True

    def test_period_recorded_on_failure(self):
        """The failure path must include period so the dashboard tile shows
        which time-of-day playlist actually failed."""
        tracker = ServiceTracker()
        tracker.record(
            "timeofday_playlist",
            success=False,
            period="evening",
            reason="No library matches for any candidate songs",
        )
        assert tracker.services["timeofday_playlist"]["period"] == "evening"
        assert tracker.services["timeofday_playlist"]["success"] is False
        assert "No library matches" in tracker.services["timeofday_playlist"]["reason"]


class TestTimeOfDayCounterDeltaPattern:
    """Source-level regression guards for the counter-delta fix in main.py.

    These assert the exact shape of the fix so an accidental revert (e.g.
    dropping the playlists_before snapshot, or removing period= from the
    failure record) gets caught by CI.
    """

    @classmethod
    def setup_class(cls):
        main_path = Path(__file__).resolve().parent.parent / "octogen" / "main.py"
        cls.source = main_path.read_text(encoding="utf-8")

    def test_playlists_before_snapshot_present(self):
        """The fix relies on snapshotting the counter before create_playlist."""
        assert 'playlists_before = self.stats["playlists_created"]' in self.source

    def test_counter_delta_check_present(self):
        assert 'self.stats["playlists_created"] > playlists_before' in self.source

    def test_failure_branch_records_period(self):
        """The failure path must pass period=current_period so the dashboard
        knows which time-of-day playlist failed.
        """
        # Find the failure-branch service_tracker.record call for timeofday_playlist.
        # Look for the block: success=False ... period=current_period ... reason="No library matches..."
        pattern = re.compile(
            r'self\.service_tracker\.record\(\s*'
            r'"timeofday_playlist",\s*'
            r'success=False,\s*'
            r'period=current_period,\s*'
            r'reason="No library matches[^"]*"',
            re.DOTALL,
        )
        assert pattern.search(self.source), (
            "Failure-path service_tracker.record must include "
            "period=current_period (regression: dashboard tile lost time-of-day context)"
        )

    def test_success_branch_records_period(self):
        pattern = re.compile(
            r'self\.service_tracker\.record\(\s*'
            r'"timeofday_playlist",\s*'
            r'success=True,\s*'
            r'playlists=1,\s*'
            r'songs=len\(period_songs\),\s*'
            r'period=current_period',
            re.DOTALL,
        )
        assert pattern.search(self.source), (
            "Success-path service_tracker.record must include period=current_period"
        )
