"""Tests for the Lidarr health probe."""

from unittest.mock import patch, MagicMock

import pytest
import requests

from octogen.web.health import check_lidarr


@pytest.fixture(autouse=True)
def clear_lidarr_env(monkeypatch):
    monkeypatch.delenv("LIDARR_URL", raising=False)
    monkeypatch.delenv("LIDARR_API_KEY", raising=False)


def test_check_lidarr_disabled_when_no_url():
    assert check_lidarr()["status"] == "disabled"


def test_check_lidarr_error_when_url_set_but_no_key(monkeypatch):
    monkeypatch.setenv("LIDARR_URL", "http://lidarr.test")
    result = check_lidarr()
    assert result["status"] == "error"
    assert "configuration" in result["message"].lower()


def test_check_lidarr_healthy_when_status_endpoint_ok(monkeypatch):
    monkeypatch.setenv("LIDARR_URL", "http://lidarr.test")
    monkeypatch.setenv("LIDARR_API_KEY", "abc123")
    resp = MagicMock(status_code=200)
    with patch("octogen.web.health.requests.get", return_value=resp):
        result = check_lidarr()
    assert result["status"] == "healthy"
    assert result["healthy"] is True


def test_check_lidarr_warning_on_non_200(monkeypatch):
    monkeypatch.setenv("LIDARR_URL", "http://lidarr.test")
    monkeypatch.setenv("LIDARR_API_KEY", "abc123")
    resp = MagicMock(status_code=503)
    with patch("octogen.web.health.requests.get", return_value=resp):
        result = check_lidarr()
    assert result["status"] == "warning"
    assert "503" in result["message"]


def test_check_lidarr_error_on_connection_refused(monkeypatch):
    monkeypatch.setenv("LIDARR_URL", "http://lidarr.test")
    monkeypatch.setenv("LIDARR_API_KEY", "abc123")
    with patch(
        "octogen.web.health.requests.get",
        side_effect=requests.exceptions.ConnectionError(),
    ):
        result = check_lidarr()
    assert result["status"] == "error"
    assert "refused" in result["message"].lower()


def test_check_lidarr_error_on_timeout(monkeypatch):
    monkeypatch.setenv("LIDARR_URL", "http://lidarr.test")
    monkeypatch.setenv("LIDARR_API_KEY", "abc123")
    with patch(
        "octogen.web.health.requests.get",
        side_effect=requests.exceptions.Timeout(),
    ):
        result = check_lidarr()
    assert result["status"] == "error"
    assert "timeout" in result["message"].lower()
