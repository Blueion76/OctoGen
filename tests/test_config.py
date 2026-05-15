"""Tests for OctoGen configuration loading."""

import os
from unittest.mock import patch

from octogen.config import load_config_from_env


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
