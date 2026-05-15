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

    def test_validate_wraps_unexpected_response_shape(self, client):
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get:
            mock_get.return_value = _mock_response(
                200, [{"name": "Standard"}]  # missing 'id'
            )
            with pytest.raises(RuntimeError, match="unexpected response shape"):
                client.validate()


def _validated_client(monitored=False, dry_run=False):
    c = LidarrClient(
        url="http://lidarr.test",
        api_key="abc123",
        quality_profile="Standard",
        metadata_profile="Standard",
        tag="octogen",
        monitored=monitored,
        dry_run=dry_run,
    )
    # Skip the network round-trip
    c.quality_profile_id = 1
    c.metadata_profile_id = 2
    c.root_folder_path = "/music"
    c.tag_id = 7
    return c


class TestAddArtist:

    def test_add_artist_success_payload(self):
        client = _validated_client(monitored=False)
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get, \
             patch("octogen.api.lidarr.requests.Session.post") as mock_post:
            mock_get.return_value = _mock_response(200, [
                {"foreignArtistId": "mb-001", "artistName": "Foo Fighters"}
            ])
            mock_post.return_value = _mock_response(201, {"id": 99})

            success, msg = client.add_artist("Foo Fighters")

        assert success is True
        assert mock_post.call_count == 1
        sent = mock_post.call_args.kwargs["json"]
        assert sent["foreignArtistId"] == "mb-001"
        assert sent["qualityProfileId"] == 1
        assert sent["metadataProfileId"] == 2
        assert sent["rootFolderPath"] == "/music"
        assert sent["monitored"] is False
        assert sent["tags"] == [7]
        assert sent["addOptions"]["searchForMissingAlbums"] is False

    def test_add_artist_409_treated_as_success(self):
        client = _validated_client()
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get, \
             patch("octogen.api.lidarr.requests.Session.post") as mock_post:
            mock_get.return_value = _mock_response(200, [
                {"foreignArtistId": "mb-001", "artistName": "Foo Fighters"}
            ])
            mock_post.return_value = _mock_response(409, {"message": "already exists"})

            success, msg = client.add_artist("Foo Fighters")
        assert success is True
        assert "already" in msg.lower()

    def test_add_artist_5xx_returns_failure_no_raise(self):
        client = _validated_client()
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get, \
             patch("octogen.api.lidarr.requests.Session.post") as mock_post:
            mock_get.return_value = _mock_response(200, [
                {"foreignArtistId": "mb-001", "artistName": "Foo Fighters"}
            ])
            mock_post.return_value = _mock_response(500)

            success, msg = client.add_artist("Foo Fighters")
        assert success is False

    def test_add_artist_lookup_empty_returns_failure(self):
        client = _validated_client()
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get:
            mock_get.return_value = _mock_response(200, [])
            success, msg = client.add_artist("Nonexistent")
        assert success is False
        assert "not found" in msg.lower()

    def test_add_artist_dry_run_no_http(self):
        client = _validated_client(dry_run=True)
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get, \
             patch("octogen.api.lidarr.requests.Session.post") as mock_post:
            success, msg = client.add_artist("Foo Fighters")
        assert success is True
        assert "dry" in msg.lower()
        mock_get.assert_not_called()
        mock_post.assert_not_called()

    def test_add_artist_lookup_missing_foreign_id_returns_failure(self):
        client = _validated_client()
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get, \
             patch("octogen.api.lidarr.requests.Session.post") as mock_post:
            mock_get.return_value = _mock_response(200, [
                {"artistName": "Foo Fighters"}  # missing foreignArtistId
            ])
            success, msg = client.add_artist("Foo Fighters")
        assert success is False
        mock_post.assert_not_called()

    def test_add_artist_request_exception_returns_failure(self):
        from requests.exceptions import ConnectionError as ReqConnError
        client = _validated_client()
        with patch(
            "octogen.api.lidarr.requests.Session.get",
            side_effect=ReqConnError("network down"),
        ):
            success, msg = client.add_artist("Foo Fighters")
        assert success is False
        assert "network down" in msg

    def test_add_artist_value_error_swallowed(self):
        client = _validated_client()
        bad_resp = MagicMock()
        bad_resp.status_code = 200
        bad_resp.ok = True
        bad_resp.raise_for_status.return_value = None
        bad_resp.json.side_effect = ValueError("not json")
        with patch(
            "octogen.api.lidarr.requests.Session.get", return_value=bad_resp,
        ):
            success, msg = client.add_artist("Foo Fighters")
        assert success is False
        assert "not json" in msg

    def test_add_artist_before_validate_returns_failure(self):
        client = LidarrClient(
            url="http://lidarr.test",
            api_key="abc123",
            quality_profile="Standard",
            metadata_profile="Standard",
            tag="octogen",
            monitored=False,
        )
        with patch("octogen.api.lidarr.requests.Session.get") as mock_get:
            success, msg = client.add_artist("Foo Fighters")
        assert success is False
        assert "validate" in msg.lower()
        mock_get.assert_not_called()
