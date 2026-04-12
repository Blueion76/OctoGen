"""Tests for Docker secrets / environment variable loading in load_secret()."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from octogen.utils.secrets import load_secret


class TestLoadSecret:
    """Tests for load_secret() priority and fallback behaviour."""

    def test_env_var_returned_when_no_docker_secret_file(self):
        """Env var is returned when the Docker secrets file does not exist."""
        with patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "env_value"}, clear=True):
            with patch("octogen.utils.secrets.Path") as mock_path_cls:
                mock_path_cls.return_value.exists.return_value = False
                result = load_secret("SPOTIFY_CLIENT_ID", "")
        assert result == "env_value"

    def test_docker_secret_returned_when_non_empty(self, tmp_path):
        """A non-empty Docker secrets file is returned in preference to the env var."""
        secret_file = tmp_path / "spotify_client_id"
        secret_file.write_text("docker_secret_value\n")

        with patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "env_value"}, clear=True):
            with patch("octogen.utils.secrets.Path") as mock_path_cls:
                mock_path_cls.return_value.exists.return_value = True
                mock_path_cls.return_value.read_text.return_value = "docker_secret_value\n"
                result = load_secret("SPOTIFY_CLIENT_ID", "")
        assert result == "docker_secret_value"

    def test_empty_docker_secret_falls_through_to_env_var(self):
        """An empty Docker secrets file must NOT shadow a non-empty env var.

        This is the core regression: previously load_secret() returned '' from
        an empty secrets file without ever reading the environment variable,
        causing SPOTIFY_IMPORT_ENABLED=true to be ineffective even when all
        required env vars were correctly set.
        """
        with patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "real_client_id"}, clear=True):
            with patch("octogen.utils.secrets.Path") as mock_path_cls:
                mock_path_cls.return_value.exists.return_value = True
                # Simulates a Docker secrets file that exists but is empty
                mock_path_cls.return_value.read_text.return_value = ""
                result = load_secret("SPOTIFY_CLIENT_ID", "")
        assert result == "real_client_id"

    def test_whitespace_only_docker_secret_falls_through_to_env_var(self):
        """A whitespace-only secrets file is treated as empty and falls through."""
        with patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "real_client_id"}, clear=True):
            with patch("octogen.utils.secrets.Path") as mock_path_cls:
                mock_path_cls.return_value.exists.return_value = True
                mock_path_cls.return_value.read_text.return_value = "   \n  "
                result = load_secret("SPOTIFY_CLIENT_ID", "")
        assert result == "real_client_id"

    def test_returns_default_when_no_secret_and_no_env_var(self):
        """Default is returned when neither Docker secret nor env var provides a value."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("octogen.utils.secrets.Path") as mock_path_cls:
                mock_path_cls.return_value.exists.return_value = False
                result = load_secret("SPOTIFY_CLIENT_ID", "fallback")
        assert result == "fallback"

    def test_returns_none_default_when_nothing_set(self):
        """None (the default default) is returned when nothing is configured."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("octogen.utils.secrets.Path") as mock_path_cls:
                mock_path_cls.return_value.exists.return_value = False
                result = load_secret("SPOTIFY_CLIENT_ID")
        assert result is None

    def test_docker_secret_read_error_falls_through_to_env_var(self):
        """If reading the secrets file raises an exception, the env var is used."""
        with patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "env_fallback"}, clear=True):
            with patch("octogen.utils.secrets.Path") as mock_path_cls:
                mock_path_cls.return_value.exists.return_value = True
                mock_path_cls.return_value.read_text.side_effect = OSError("permission denied")
                result = load_secret("SPOTIFY_CLIENT_ID", "")
        assert result == "env_fallback"
