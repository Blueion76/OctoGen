"""Tests for OctoGen configuration loading."""

import os
from unittest.mock import MagicMock, patch

from octogen.config import load_config_from_env
from octogen.main import OctoGenEngine


# Minimal required env vars so load_config_from_env() doesn't call sys.exit(1)
_REQUIRED_ENV = {
    "NAVIDROME_URL": "http://navidrome.test",
    "NAVIDROME_USER": "user",
    "NAVIDROME_PASSWORD": "pass",
    "OCTOFIESTA_URL": "http://octofiesta.test",
}


class TestLoadConfigFromEnvAITimeout:
    """Tests for AI_REQUEST_TIMEOUT clamping in load_config_from_env()."""

    def test_default_timeout(self):
        """Default timeout (300s) is returned when env var is not set."""
        env = {**_REQUIRED_ENV}
        env.pop("AI_REQUEST_TIMEOUT", None)
        with patch.dict(os.environ, env, clear=True):
            config = load_config_from_env()
        assert config["ai"]["request_timeout"] == 300

    def test_timeout_above_minimum(self):
        """Values above 30 are returned as-is."""
        with patch.dict(os.environ, {**_REQUIRED_ENV, "AI_REQUEST_TIMEOUT": "120"}):
            config = load_config_from_env()
        assert config["ai"]["request_timeout"] == 120

    def test_timeout_below_minimum_clamped_to_30(self):
        """Values below 30 are clamped to 30 to satisfy AIConfig ge=30 constraint."""
        with patch.dict(os.environ, {**_REQUIRED_ENV, "AI_REQUEST_TIMEOUT": "5"}):
            config = load_config_from_env()
        assert config["ai"]["request_timeout"] == 30

    def test_timeout_of_zero_clamped_to_30(self):
        """Zero is clamped to 30."""
        with patch.dict(os.environ, {**_REQUIRED_ENV, "AI_REQUEST_TIMEOUT": "0"}):
            config = load_config_from_env()
        assert config["ai"]["request_timeout"] == 30

    def test_timeout_exactly_30_unchanged(self):
        """Exactly 30 is at the minimum and must not be changed."""
        with patch.dict(os.environ, {**_REQUIRED_ENV, "AI_REQUEST_TIMEOUT": "30"}):
            config = load_config_from_env()
        assert config["ai"]["request_timeout"] == 30


class TestOctoFiestaToggle:
    """Tests for OCTOFIESTA_ENABLED toggle."""

    def test_enabled_default_true_requires_url(self):
        """When OCTOFIESTA_ENABLED is unset, OCTOFIESTA_URL must be present (back-compat)."""
        env = {k: v for k, v in _REQUIRED_ENV.items() if k != "OCTOFIESTA_URL"}
        with patch.dict(os.environ, env, clear=True):
            with patch("octogen.config.sys.exit") as mock_exit:
                result = load_config_from_env()
                mock_exit.assert_called_once_with(1)
        # Confirm nothing meaningful was returned after the mocked exit
        assert result["octofiesta"]["url"] is None

    def test_enabled_false_makes_url_optional(self):
        """OCTOFIESTA_ENABLED=false: OCTOFIESTA_URL is no longer required."""
        env = {k: v for k, v in _REQUIRED_ENV.items() if k != "OCTOFIESTA_URL"}
        env["OCTOFIESTA_ENABLED"] = "false"
        with patch.dict(os.environ, env, clear=True):
            config = load_config_from_env()
        assert config["octofiesta"]["enabled"] is False
        assert config["octofiesta"]["url"] is None

    def test_enabled_true_keeps_url_required(self):
        """OCTOFIESTA_ENABLED=true (explicit): OCTOFIESTA_URL still required."""
        env = {k: v for k, v in _REQUIRED_ENV.items() if k != "OCTOFIESTA_URL"}
        env["OCTOFIESTA_ENABLED"] = "true"
        with patch.dict(os.environ, env, clear=True):
            with patch("octogen.config.sys.exit") as mock_exit:
                result = load_config_from_env()
                mock_exit.assert_called_once_with(1)
        assert result["octofiesta"]["url"] is None


class TestHybridDailyMixWithoutOctoFiesta:
    """Tests for the LLM-clamp behavior of `_generate_hybrid_daily_mix` when
    Octo-Fiesta is disabled. Without a download path, LLM picks would silently
    drop out of the playlist, so we skip the LLM call entirely and ship a pure
    AudioMuse mix.
    """

    @staticmethod
    def _make_engine(octo, audiomuse_songs):
        """Build an engine with just enough state for `_generate_hybrid_daily_mix`."""
        engine = OctoGenEngine.__new__(OctoGenEngine)
        engine.octo = octo
        engine.config = {
            "audiomuse": {"songs_per_mix": 25, "llm_songs_per_mix": 5},
        }
        engine.audiomuse_client = MagicMock()
        engine.audiomuse_client.generate_playlist.return_value = audiomuse_songs
        # Sentinel: the LLM helper must not be called when octo is None.
        engine._generate_llm_songs_for_daily_mix = MagicMock(
            side_effect=AssertionError("LLM should not be called when octo is None")
        )
        return engine

    def test_octo_none_skips_llm_call(self):
        """When self.octo is None, the LLM helper is never invoked."""
        audiomuse_picks = [
            {"artist": "Artist A", "title": f"Song {i}"} for i in range(25)
        ]
        engine = self._make_engine(octo=None, audiomuse_songs=audiomuse_picks)
        songs = engine._generate_hybrid_daily_mix(
            mix_number=1,
            genre_focus="rock",
            characteristics="energetic",
            top_artists=["A"],
            top_genres=["rock"],
            favorited_songs=[{"artist": "A", "title": "X"}],
            low_rated_songs=None,
            playlist_name="Daily Mix 1",
        )
        # All 25 picks come from AudioMuse, none from LLM.
        assert len(songs) == 25
        engine._generate_llm_songs_for_daily_mix.assert_not_called()

    def test_octo_present_calls_llm(self):
        """When self.octo is set, the LLM helper is invoked as usual."""
        audiomuse_picks = [
            {"artist": "Artist A", "title": f"Song {i}"} for i in range(25)
        ]
        engine = OctoGenEngine.__new__(OctoGenEngine)
        engine.octo = MagicMock()  # truthy, not None
        engine.config = {
            "audiomuse": {"songs_per_mix": 25, "llm_songs_per_mix": 5},
        }
        engine.audiomuse_client = MagicMock()
        engine.audiomuse_client.generate_playlist.return_value = audiomuse_picks
        engine._generate_llm_songs_for_daily_mix = MagicMock(return_value=[
            {"artist": "LLM Artist", "title": f"LLM Song {i}"} for i in range(5)
        ])
        songs = engine._generate_hybrid_daily_mix(
            mix_number=1,
            genre_focus="rock",
            characteristics="energetic",
            top_artists=["A"],
            top_genres=["rock"],
            favorited_songs=[{"artist": "A", "title": "X"}],
            low_rated_songs=None,
            playlist_name="Daily Mix 1",
        )
        assert len(songs) == 30
        engine._generate_llm_songs_for_daily_mix.assert_called_once()


class TestTimeOfDayPlaylistsPersist:
    """Tests for the TIMEOFDAY_PLAYLISTS_PERSIST toggle."""

    def test_default_is_false(self):
        """When unset, the toggle defaults to False (preserve existing behavior)."""
        env = {**_REQUIRED_ENV}
        env.pop("TIMEOFDAY_PLAYLISTS_PERSIST", None)
        with patch.dict(os.environ, env, clear=True):
            config = load_config_from_env()
        assert config["playlists"]["time_of_day_persist"] is False

    def test_true(self):
        """`true` enables persistence."""
        with patch.dict(
            os.environ,
            {**_REQUIRED_ENV, "TIMEOFDAY_PLAYLISTS_PERSIST": "true"},
        ):
            config = load_config_from_env()
        assert config["playlists"]["time_of_day_persist"] is True

    def test_false_explicit(self):
        """Explicit `false` keeps it disabled."""
        with patch.dict(
            os.environ,
            {**_REQUIRED_ENV, "TIMEOFDAY_PLAYLISTS_PERSIST": "false"},
        ):
            config = load_config_from_env()
        assert config["playlists"]["time_of_day_persist"] is False

    def test_arbitrary_value_treated_as_false(self):
        """Anything not equal to `true` (case-insensitive) is False."""
        with patch.dict(
            os.environ,
            {**_REQUIRED_ENV, "TIMEOFDAY_PLAYLISTS_PERSIST": "yes"},
        ):
            config = load_config_from_env()
        assert config["playlists"]["time_of_day_persist"] is False


class TestCleanupOtherPeriodPlaylists:
    """Tests for the _cleanup_other_period_playlists gating helper."""

    @staticmethod
    def _make_engine(persist: bool, existing: list[dict]) -> OctoGenEngine:
        """Build an engine instance with just enough state for the helper."""
        engine = OctoGenEngine.__new__(OctoGenEngine)
        engine.config = {"playlists": {"time_of_day_persist": persist}}
        engine.nd = MagicMock()
        engine.nd.get_all_playlists.return_value = existing
        return engine

    def test_persist_true_skips_delete(self):
        """When the toggle is on, no delete calls fire even if old periods exist."""
        engine = self._make_engine(
            persist=True,
            existing=[
                {"id": "1", "name": "Morning Mix"},
                {"id": "2", "name": "Afternoon Flow"},
            ],
        )
        engine._cleanup_other_period_playlists("Evening Chill")
        engine.nd.get_all_playlists.assert_not_called()
        engine.nd.delete_playlist.assert_not_called()

    def test_persist_false_deletes_only_other_periods(self):
        """Default behavior: delete other period playlists, never the current one."""
        engine = self._make_engine(
            persist=False,
            existing=[
                {"id": "1", "name": "Morning Mix"},
                {"id": "2", "name": "Afternoon Flow"},
                {"id": "3", "name": "Evening Chill"},  # current
                {"id": "4", "name": "My Hand-Curated Mix"},
            ],
        )
        engine._cleanup_other_period_playlists("Evening Chill")
        deleted_ids = [c.args[0] for c in engine.nd.delete_playlist.call_args_list]
        assert sorted(deleted_ids) == ["1", "2"]

    def test_persist_false_swallows_errors(self):
        """A failure listing playlists is logged but never raised."""
        engine = self._make_engine(persist=False, existing=[])
        engine.nd.get_all_playlists.side_effect = RuntimeError("boom")
        engine._cleanup_other_period_playlists("Morning Mix")
        engine.nd.delete_playlist.assert_not_called()
