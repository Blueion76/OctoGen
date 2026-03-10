"""Spotify API client for playlist importing"""

import logging
import re
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    SPOTIPY_AVAILABLE = True
except ImportError:
    SPOTIPY_AVAILABLE = False


class SpotifyImporter:
    """Imports playlists from Spotify using client credentials (no user login)."""

    def __init__(self, client_id: str, client_secret: str):
        """Initialize Spotify importer.

        Args:
            client_id: Spotify application client ID
            client_secret: Spotify application client secret

        Raises:
            ImportError: If the spotipy library is not installed
        """
        if not SPOTIPY_AVAILABLE:
            raise ImportError(
                "The 'spotipy' library is required for Spotify import. "
                "Install it with: pip install spotipy>=2.24.0"
            )

        auth_manager = SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )
        self.sp = spotipy.Spotify(auth_manager=auth_manager)
        logger.info("SpotifyImporter initialized")

    def check_connection(self) -> bool:
        """Verify that the Spotify credentials are valid.

        Returns:
            True if the connection is successful, False otherwise
        """
        try:
            # A lightweight call to verify credentials work
            self.sp.search(q="test", type="track", limit=1)
            return True
        except Exception as e:
            logger.error("Spotify connection check failed: %s", e)
            return False

    @staticmethod
    def extract_playlist_id(playlist_id_or_url: str) -> str:
        """Extract the bare playlist ID from a URL or return it unchanged.

        Args:
            playlist_id_or_url: Spotify playlist URL or bare playlist ID

        Returns:
            Bare playlist ID string
        """
        # Match https://open.spotify.com/playlist/<id>[?...]
        match = re.search(r"spotify\.com/playlist/([A-Za-z0-9_-]+)", playlist_id_or_url)
        if match:
            return match.group(1)
        # Otherwise assume it is already a bare ID
        return playlist_id_or_url.rstrip("/").split("/")[-1].split("?")[0]

    def get_playlist_tracks(self, playlist_id_or_url: str) -> List[Dict]:
        """Fetch all tracks from a Spotify playlist.

        Args:
            playlist_id_or_url: Spotify playlist URL or bare playlist ID

        Returns:
            List of dicts with 'artist' and 'title' keys
        """
        playlist_id = self.extract_playlist_id(playlist_id_or_url)
        tracks: List[Dict] = []

        try:
            results = self.sp.playlist_items(
                playlist_id,
                fields="items(track(name,artists(name))),next",
                limit=100,
            )

            while results:
                for item in results.get("items", []):
                    track = item.get("track")
                    if not track:
                        continue

                    title = (track.get("name") or "").strip()
                    artists = track.get("artists") or []
                    artist = (artists[0].get("name") or "").strip() if artists else ""

                    if not artist or not title:
                        continue

                    tracks.append({"artist": artist, "title": title})

                next_url = results.get("next")
                if next_url:
                    results = self.sp.next(results)
                else:
                    break

        except Exception as e:
            logger.error("Failed to fetch Spotify playlist '%s': %s", playlist_id, e)
            return []

        logger.info("Fetched %d tracks from Spotify playlist '%s'", len(tracks), playlist_id)
        return tracks

    def get_user_playlists(self, limit: int = 20) -> List[Dict]:
        """List current user's playlists (requires user OAuth – not available with
        client credentials; returns empty list).

        Args:
            limit: Maximum number of playlists to return

        Returns:
            Empty list (client credentials flow does not support user endpoints)
        """
        logger.warning(
            "get_user_playlists() is not available with client credentials flow"
        )
        return []
