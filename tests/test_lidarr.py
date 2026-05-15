"""Tests for LidarrClient (mocked HTTP)."""

from unittest.mock import MagicMock, patch

import pytest

from octogen.api.lidarr import LidarrClient


@pytest.fixture
def client():
    return LidarrClient(
        url="http://lidarr.test",
        api_key="abc123",
        quality_profile="Standard",
        metadata_profile="Standard",
        tag="octogen",
        monitored=False,
        dry_run=False,
    )


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.ok = 200 <= status_code < 300
    return resp


class TestValidate:

    def test_validate_resolves_profiles_picks_root_creates_tag(self, client):
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get, \
             patch("octogen.api.lidarr.requests.Session.post") as mock_post:
            mock_get.side_effect = [
                _mock_response(200, [{"id": 1, "name": "Standard"}]),  # quality profile
                _mock_response(200, [{"id": 2, "name": "Standard"}]),  # metadata profile
                _mock_response(200, [{"id": 5, "path": "/music"}]),    # root folder
                _mock_response(200, [{"id": 7, "label": "octogen"}]),  # tag (exists)
            ]
            client.validate()
        assert client.quality_profile_id == 1
        assert client.metadata_profile_id == 2
        assert client.root_folder_path == "/music"
        assert client.tag_id == 7
        mock_post.assert_not_called()

    def test_validate_creates_tag_if_missing(self, client):
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get, \
             patch("octogen.api.lidarr.requests.Session.post") as mock_post:
            mock_get.side_effect = [
                _mock_response(200, [{"id": 1, "name": "Standard"}]),
                _mock_response(200, [{"id": 2, "name": "Standard"}]),
                _mock_response(200, [{"id": 5, "path": "/music"}]),
                _mock_response(200, []),  # tag list empty
            ]
            mock_post.return_value = _mock_response(201, {"id": 9, "label": "octogen"})
            client.validate()
        assert client.tag_id == 9
        assert mock_post.call_count == 1

    def test_validate_fails_when_quality_profile_unknown(self, client):
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get:
            mock_get.return_value = _mock_response(200, [{"id": 1, "name": "Other"}])
            with pytest.raises(RuntimeError, match="LIDARR_QUALITY_PROFILE"):
                client.validate()

    def test_validate_fails_when_unreachable(self, client):
        from requests.exceptions import ConnectionError as ReqConnError
        with patch("octogen.api.lidarr.requests.Session.get", side_effect=ReqConnError):
            with pytest.raises(RuntimeError, match="unreachable"):
                client.validate()

    def test_validate_fails_when_no_root_folders(self, client):
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(200, [{"id": 1, "name": "Standard"}]),
                _mock_response(200, [{"id": 2, "name": "Standard"}]),
                _mock_response(200, []),  # no root folders
            ]
            with pytest.raises(RuntimeError, match="root folder"):
                client.validate()
