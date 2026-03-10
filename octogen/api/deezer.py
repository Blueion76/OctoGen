"""Deezer API client for playlist importing"""

import logging
import re
from typing import List, Dict

logger = logging.getLogger(__name__)

try:
    import deezer
    DEEZER_AVAILABLE = True
except ImportError:
    DEEZER_AVAILABLE = False


class DeezerImporter:
    """Imports playlists from Deezer (no authentication required for public playlists)."""

    def __init__(self):
        """Initialize Deezer importer.

        Raises:
            ImportError: If the deezer-python library is not installed
        """
        if not DEEZER_AVAILABLE:
            raise ImportError(
                "The 'deezer-python' library is required for Deezer import. "
                "Install it with: pip install deezer-python>=0.10.0"
            )

        self.client = deezer.Client()
        logger.info("DeezerImporter initialized")

    def check_connection(self) -> bool:
        """Verify that the Deezer API is reachable.

        Returns:
            True if the connection is successful, False otherwise
        """
        try:
            # Lightweight call to verify API is reachable
            self.client.search("test")
            return True
        except Exception as e:
            logger.error("Deezer connection check failed: %s", e)
            return False

    @staticmethod
    def _extract_playlist_id(playlist_id_or_url: str) -> str:
        """Extract the bare playlist ID from a Deezer URL or return it unchanged.

        Args:
            playlist_id_or_url: Deezer playlist URL or bare playlist ID

        Returns:
            Bare playlist ID string
        """
        # Match https://www.deezer.com/[locale/]playlist/<id>[?...]
        match = re.search(r"deezer\.com(?:/[a-z]{2})?/playlist/(\d+)", playlist_id_or_url)
        if match:
            return match.group(1)
        # Otherwise assume it is already a bare ID
        return playlist_id_or_url.rstrip("/").split("/")[-1].split("?")[0]

    def get_playlist_tracks(self, playlist_id_or_url: str) -> List[Dict]:
        """Fetch all tracks from a Deezer playlist.

        Args:
            playlist_id_or_url: Deezer playlist URL or bare playlist ID (int or str)

        Returns:
            List of dicts with 'artist' and 'title' keys
        """
        playlist_id = self._extract_playlist_id(str(playlist_id_or_url))
        tracks: List[Dict] = []

        try:
            playlist = self.client.get_playlist(int(playlist_id))
            for track in playlist.tracks:
                title = (getattr(track, "title", None) or "").strip()
                artist_obj = getattr(track, "artist", None)
                artist = (getattr(artist_obj, "name", None) or "").strip() if artist_obj else ""

                if not artist or not title:
                    continue

                tracks.append({"artist": artist, "title": title})

        except Exception as e:
            logger.error("Failed to fetch Deezer playlist '%s': %s", playlist_id, e)
            return []

        logger.info("Fetched %d tracks from Deezer playlist '%s'", len(tracks), playlist_id)
        return tracks
