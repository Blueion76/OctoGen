"""Tests for ListenBrainz generated playlist title parser."""

from octogen.api.listenbrainz import ListenBrainzAPI


parse = ListenBrainzAPI.parse_generated_playlist_title


class TestParseGeneratedPlaylistTitle:
    """Unit tests for parse_generated_playlist_title."""

    # --- Valid cases --------------------------------------------------------

    def test_valid_weekly_jams(self):
        result = parse("Weekly Jams for blueion, week of 2026-04-06 Mon")
        assert result == {
            "base_title": "Weekly Jams",
            "username": "blueion",
            "week_start": "2026-04-06",
            "dow": "Mon",
        }

    def test_valid_arbitrary_prefix(self):
        """Any generated playlist prefix is supported, not just 'Weekly Jams'."""
        result = parse("Exploration for alice, week of 2026-04-07 Tue")
        assert result is not None
        assert result["base_title"] == "Exploration"
        assert result["username"] == "alice"
        assert result["week_start"] == "2026-04-07"
        assert result["dow"] == "Tue"

    def test_valid_multi_word_prefix(self):
        result = parse("Top Discoveries for bob_99, week of 2026-04-04 Sat")
        assert result is not None
        assert result["base_title"] == "Top Discoveries"
        assert result["username"] == "bob_99"

    def test_prefix_containing_for(self):
        """Greedy base_title group splits on the final 'for <user>, week of' suffix."""
        result = parse("Songs for Sleep for blueion, week of 2026-04-06 Mon")
        assert result is not None
        assert result["base_title"] == "Songs for Sleep"
        assert result["username"] == "blueion"

    def test_base_title_trimmed(self):
        """Trailing whitespace between base title and 'for' is stripped."""
        result = parse("Weekly Jams   for blueion, week of 2026-04-06 Mon")
        # Extra spaces before 'for' are accepted; the parsed base_title should
        # still be trimmed.
        assert result is not None
        assert result["base_title"] == result["base_title"].rstrip()

    # --- Day mismatch -------------------------------------------------------

    def test_invalid_day_mismatch(self):
        """2026-04-06 is a Monday; 'Tue' must be rejected."""
        assert parse("Weekly Jams for blueion, week of 2026-04-06 Tue") is None

    def test_invalid_day_mismatch_saturday(self):
        """2026-04-07 is a Tuesday; 'Sat' must be rejected."""
        assert parse("Weekly Jams for blueion, week of 2026-04-07 Sat") is None

    # --- Malformed date -----------------------------------------------------

    def test_malformed_date_invalid_month(self):
        assert parse("Weekly Jams for blueion, week of 2026-13-01 Mon") is None

    def test_malformed_date_invalid_day(self):
        assert parse("Weekly Jams for blueion, week of 2026-02-30 Mon") is None

    def test_malformed_date_not_a_date(self):
        assert parse("Weekly Jams for blueion, week of abcd-ef-gh Mon") is None

    # --- Non-matching titles ------------------------------------------------

    def test_empty_string(self):
        assert parse("") is None

    def test_none_input(self):
        assert parse(None) is None

    def test_no_suffix_at_all(self):
        assert parse("My Custom Playlist") is None

    def test_missing_week_of(self):
        assert parse("Weekly Jams for blueion, 2026-04-06 Mon") is None

    def test_missing_username(self):
        assert parse("Weekly Jams for , week of 2026-04-06 Mon") is None

    def test_missing_comma(self):
        assert parse("Weekly Jams for blueion week of 2026-04-06 Mon") is None

    def test_unknown_day_abbreviation(self):
        assert parse("Weekly Jams for blueion, week of 2026-04-06 Monday") is None
