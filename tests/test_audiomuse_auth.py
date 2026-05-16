"""Tests for AudioMuse-AI bearer-token auth.

Locks in the AUDIOMUSE_API_TOKEN bearer-auth behavior so a future change to
header construction or token wiring fails CI instead of silently dropping
the Authorization header.
"""

from unittest.mock import patch, MagicMock

from octogen.api.audiomuse import AudioMuseClient


def _make_client(token=None):
    return AudioMuseClient(
        base_url="http://audiomuse.test",
        ai_provider="gemini",
        ai_model="gemini-2.5-flash",
        audiomuse_api_token=token,
    )


class TestAuthHeaders:
    def test_no_token_returns_empty_headers(self):
        assert _make_client(token=None)._auth_headers() == {}

    def test_empty_token_returns_empty_headers(self):
        assert _make_client(token="")._auth_headers() == {}

    def test_token_returns_bearer_header(self):
        headers = _make_client(token="abc123")._auth_headers()
        assert headers == {"Authorization": "Bearer abc123"}


class TestGeneratePlaylistHeaderInjection:
    @patch("octogen.api.audiomuse.requests.post")
    def test_includes_bearer_when_token_set(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": {"query_results": []}},
        )
        _make_client(token="t0k").generate_playlist("any", num_songs=5)

        _, kwargs = mock_post.call_args
        assert kwargs["headers"] == {"Authorization": "Bearer t0k"}

    @patch("octogen.api.audiomuse.requests.post")
    def test_no_auth_header_when_token_missing(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": {"query_results": []}},
        )
        _make_client(token=None).generate_playlist("any", num_songs=5)

        _, kwargs = mock_post.call_args
        assert kwargs["headers"] == {}


class TestCheckHealthHeaderInjection:
    @patch("octogen.api.audiomuse.requests.get")
    def test_includes_bearer_when_token_set(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        _make_client(token="t0k").check_health()

        _, kwargs = mock_get.call_args
        assert kwargs["headers"] == {"Authorization": "Bearer t0k"}

    @patch("octogen.api.audiomuse.requests.get")
    def test_no_auth_header_when_token_missing(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        _make_client(token=None).check_health()

        _, kwargs = mock_get.call_args
        assert kwargs["headers"] == {}
