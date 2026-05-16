"""Navidrome/Subsonic API client with star rating support"""

import asyncio
import logging
import re
import time
import requests
import aiohttp
import difflib
from collections import Counter
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlencode

from octogen.utils.auth import subsonic_auth_params
from octogen.storage.cache import RatingsCache, LOW_RATING_MIN, LOW_RATING_MAX


logger = logging.getLogger(__name__)


class NavidromeAPI:
    """Navidrome/Subsonic API with star rating support and async operations."""
    
    # Version markers for detecting remixes, live versions, etc.
    VERSION_MARKERS = [
        'remix', 'mix', 'edit', 'version', 'acoustic', 'live', 'instrumental',
        'extended', 'radio edit', 'demo', 'remaster', 'cover', 'vip', 'bootleg',
        'mashup'
    ]
    
    # Search and matching thresholds
    MATCH_THRESHOLD = 0.75  # Minimum match score for library search (75%)
    SIMILARITY_THRESHOLD = 0.85  # Minimum similarity for near-duplicate detection (85%)
    LIBRARY_SEARCH_LIMIT = 30  # Max songs per search strategy in library search
    SIMILAR_SEARCH_LIMIT = 50  # Max songs for similar song detection

    # Seed-fallback heuristic: estimate how many albums to fetch to cover N
    # additional songs. Most albums hold ~10 songs; fetch a small buffer so we
    # don't have to round-trip again if a few albums come up short.
    AVG_SONGS_PER_ALBUM = 10
    ALBUM_FETCH_BUFFER = 5
    MIN_ALBUMS_TO_FETCH = 5

    def __init__(self, url: str, username: str, password: str,
                 ratings_cache: RatingsCache, config: dict):
        """Initialize Navidrome API client.
        
        Args:
            url: Navidrome server URL
            username: Username for authentication
            password: Password for authentication
            ratings_cache: RatingsCache instance for caching
            config: Configuration dictionary
        """
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.ratings_cache = ratings_cache

        # Configurable values
        self.album_batch_size = config.get("performance", {}).get("album_batch_size", 500)
        self.max_albums = config.get("performance", {}).get("max_albums_scan", 10000)
        self.scan_timeout = config.get("performance", {}).get("scan_timeout", 60)

        ai_cfg = config.get("ai", {})
        self.seed_fallback_min = ai_cfg.get("seed_fallback_min", 50)
        self.seed_fallback_target = ai_cfg.get("seed_fallback_target", 500)
        self.seed_fallback_album_count = ai_cfg.get("seed_fallback_album_count", 100)

    def _request(self, endpoint: str, extra_params: dict = None) -> Optional[dict]:
        """Make Subsonic API request.
        
        Args:
            endpoint: API endpoint
            extra_params: Additional parameters
            
        Returns:
            JSON response or None on error
        """
        params = subsonic_auth_params(self.username, self.password)
        if extra_params:
            params.update(extra_params)

        try:
            r = self.session.get(f"{self.url}/rest/{endpoint}", params=params, timeout=30)
            r.raise_for_status()
            response = r.json().get("subsonic-response", {})
            if response.get("status") == "failed":
                logger.error("Navidrome API failed: %s", response.get("error", {}).get("message"))
                return None
            return response
        except requests.exceptions.RequestException as e:
            logger.error("Navidrome request error: %s", str(e)[:200])
            return None
        except Exception as e:
            logger.error("Navidrome unexpected error: %s", str(e)[:200])
            return None

    def test_connection(self) -> bool:
        """Test Navidrome connection.
        
        Returns:
            True if connection successful
        """
        response = self._request("ping")
        if response:
            logger.info("✓ Connected to Navidrome: %s", self.url)
            return True
        logger.error("✗ Navidrome connection failed")
        return False

    def get_starred_songs(self) -> List[Dict]:
        """Get all starred songs.

        Returns:
            List of starred song dictionaries
        """
        response = self._request("getStarred2")
        if not response:
            logger.warning("Failed to fetch starred songs")
            return []

        songs: List[Dict] = []
        starred_data = response.get("starred2", {})
        for song in starred_data.get("song", []):
            songs.append({
                "id": song["id"],
                "title": song["title"],
                "artist": song["artist"],
                "album": song.get("album", ""),
                "genre": song.get("genre", "Unknown"),
            })
        return songs

    def get_seed_songs(self) -> List[Dict]:
        """Get songs to seed the AI recommendation engine.

        Returns starred songs, falling back to most-played albums when the
        starred set is too small. The Gemini context cache requires at least
        1024 tokens of seed metadata; users with few starred songs hit
        ``min_total_token_count`` errors and lose the LLM half of every
        hybrid playlist. When starred count is below ``SEED_FALLBACK_MIN``,
        augment with songs from the user's most-played albums
        (Subsonic ``getAlbumList2?type=frequent``) until
        ``SEED_FALLBACK_TARGET`` is reached.

        NOTE: This method is sync and uses ``asyncio.run()`` internally for the
        parallel album fetch. It cannot be called from inside a running event
        loop. If a caller is async, it should call
        ``_fetch_albums_songs_parallel()`` directly via ``await``.

        Returns:
            List of seed song dictionaries.
        """
        songs = self.get_starred_songs()

        if len(songs) >= self.seed_fallback_min:
            return songs

        logger.info(
            "Only %d starred songs (< %d) — augmenting AI seed with most-played albums",
            len(songs), self.seed_fallback_min,
        )
        try:
            albums_resp = self._request(
                "getAlbumList2",
                {"type": "frequent", "size": self.seed_fallback_album_count},
            )
            albums = (albums_resp or {}).get("albumList2", {}).get("album", [])
            needed = max(0, self.seed_fallback_target - len(songs))
            estimated_albums = min(
                len(albums),
                max(
                    self.MIN_ALBUMS_TO_FETCH,
                    (needed // self.AVG_SONGS_PER_ALBUM) + self.ALBUM_FETCH_BUFFER,
                ),
            )
            albums = albums[:estimated_albums]
            album_ids = [a["id"] for a in albums if a.get("id")]
            album_song_lists = asyncio.run(self._fetch_albums_songs_parallel(album_ids))

            seen_ids = {s["id"] for s in songs}
            added = 0
            for album, album_songs in zip(albums, album_song_lists):
                if len(songs) >= self.seed_fallback_target:
                    break
                for s in album_songs:
                    if s["id"] in seen_ids:
                        continue
                    seen_ids.add(s["id"])
                    songs.append({
                        "id": s["id"],
                        "title": s["title"],
                        "artist": s.get("artist", album.get("artist", "")),
                        "album": s.get("album", album.get("name", "")),
                        "genre": s.get("genre", "Unknown"),
                    })
                    added += 1
                    if len(songs) >= self.seed_fallback_target:
                        break
            logger.info(
                "Added %d songs from %d most-played albums (total seed: %d)",
                added, len(albums), len(songs),
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, TypeError, ValueError) as e:
            logger.warning("Most-played seed augmentation failed: %s", str(e)[:200])

        return songs

    async def _fetch_albums_songs_parallel(self, album_ids: List[str]) -> List[List[Dict]]:
        """Fetch songs for multiple albums in parallel.

        Uses ``return_exceptions=True`` so a single album fetch failure does
        not cancel the whole batch. Failed fetches show up as empty lists in
        the result.
        """
        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch_album_songs_async(session, aid) for aid in album_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        clean: List[List[Dict]] = []
        for aid, result in zip(album_ids, results):
            if isinstance(result, BaseException):
                logger.debug("Album %s fetch failed: %s", aid, result)
                clean.append([])
            else:
                clean.append(result)
        return clean

    def get_song_rating(self, song_id: str) -> int:
        """Get rating for a song (0-5 stars).
        
        Args:
            song_id: Song identifier
            
        Returns:
            Rating (0-5)
        """
        response = self._request("getSong", {"id": song_id})
        if not response:
            return 0
        song = response.get("song", {})
        return song.get("userRating", 0)

    def set_song_rating(self, song_id: str, rating: int) -> None:
        """Set rating for a song (1-5 stars, or 0 to remove).
        
        Args:
            song_id: Song identifier
            rating: Rating value (0-5)
        """
        if rating < 0 or rating > 5:
            logger.warning("Invalid rating %d, must be 0-5", rating)
            return
        self._request("setRating", {"id": song_id, "rating": rating})

    async def _fetch_album_songs_async(self, session: aiohttp.ClientSession,
                                       album_id: str) -> List[Dict]:
        """Async fetch songs from an album.
        
        Args:
            session: aiohttp session
            album_id: Album identifier
            
        Returns:
            List of song dictionaries
        """
        params = subsonic_auth_params(self.username, self.password)
        params["id"] = album_id
        url = f"{self.url}/rest/getAlbum"

        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
                data = await response.json()
                result = data.get("subsonic-response", {})
                if result.get("status") == "ok":
                    return result.get("album", {}).get("song", [])
        except Exception:
            pass
        return []

    async def _scan_albums_async(self, album_ids: List[str]) -> List[Dict]:
        """Scan multiple albums in parallel for rated songs.
        
        Args:
            album_ids: List of album identifiers
            
        Returns:
            List of low-rated song dictionaries
        """
        low_rated = []

        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch_album_songs_async(session, album_id) for album_id in album_ids]
            results = await asyncio.gather(*tasks)

            for songs in results:
                for song in songs:
                    rating = song.get("userRating", 0)
                    song_id = song.get("id")

                    if song_id and rating > 0:
                        # Update cache
                        self.ratings_cache.update_rating(
                            song_id,
                            song.get("artist", "Unknown"),
                            song.get("title", "Unknown"),
                            rating
                        )

                        if LOW_RATING_MIN <= rating <= LOW_RATING_MAX:
                            low_rated.append({
                                "artist": song.get("artist", "Unknown"),
                                "title": song.get("title", "Unknown"),
                                "rating": rating,
                                "id": song_id
                            })

        return low_rated

    def get_low_rated_songs(self) -> List[Dict]:
        """Get all songs rated 1-2 stars with caching.
        
        Returns:
            List of low-rated song dictionaries
        """
        today = datetime.now().strftime("%Y-%m-%d")
        last_scan = self.ratings_cache.get_last_scan_date()

        # Use cache if scanned today
        if last_scan == today:
            logger.info("Using cached low-rated songs from today")
            return self.ratings_cache.get_low_rated_songs()

        logger.info("Performing full library scan for ratings (cached daily)")

        # Fetch all albums
        albums_to_check = self._fetch_all_albums()
        logger.info("Found %d albums to scan", len(albums_to_check))

        if not albums_to_check:
            return []

        # Async scan
        album_ids = [album.get("id") for album in albums_to_check if album.get("id")]
        low_rated = asyncio.run(self._scan_albums_async(album_ids))

        # Update cache metadata
        self.ratings_cache.set_last_scan_date(today)

        logger.info("Found %d low-rated songs (1-2 stars)", len(low_rated))
        return low_rated

    def _fetch_all_albums(self) -> List[Dict]:
        """Fetch all albums from library.
        
        Returns:
            List of album dictionaries
        """
        albums = []
        offset = 0

        while offset < self.max_albums:
            response = self._request("getAlbumList2", {
                "type": "alphabeticalByName",
                "size": self.album_batch_size,
                "offset": offset
            })

            if not response:
                break

            album_list = response.get("albumList2", {}).get("album", [])
            if not album_list:
                break

            albums.extend(album_list)
            offset += self.album_batch_size

        return albums

    def get_top_artists(self, limit: int = 50) -> List[str]:
        """Get top artists from starred songs.
        
        Args:
            limit: Maximum number of artists
            
        Returns:
            List of artist names
        """
        songs = self.get_starred_songs()
        if not songs:
            return []

        artist_counts = Counter([s["artist"] for s in songs])
        return [artist for artist, _count in artist_counts.most_common(limit)]

    def get_top_genres(self, limit: int = 10) -> List[str]:
        """Get top genres from starred songs.
        
        Args:
            limit: Maximum number of genres
            
        Returns:
            List of genre names
        """
        songs = self.get_starred_songs()
        if not songs:
            return ["pop", "rock", "indie", "electronic"]

        genres = [s["genre"] for s in songs if s.get("genre") and s["genre"] != "Unknown"]
        if not genres:
            return ["pop", "rock", "indie", "electronic"]

        genre_counts = Counter(genres)
        return [g for g, _count in genre_counts.most_common(limit)]

    def _strip_featured(self, text: str) -> str:
        """Remove featured artist variations.
        
        Args:
            text: Text to process
            
        Returns:
            Text without featured artist mentions
        """
        text = re.sub(r'\s+feat\.?\s+.*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+ft\.?\s+.*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+featuring\s+.*$', '', text, flags=re.IGNORECASE)
        return text.strip()

    def get_all_playlists(self) -> List[Dict]:
        """Get all playlists from Navidrome.
        
        Returns:
            List of playlist dictionaries with id and name
        """
        response = self._request("getPlaylists")
        if not response:
            return []
        return response.get("playlists", {}).get("playlist", [])
    
    def delete_playlist(self, playlist_id: str) -> bool:
        """Delete a playlist by ID.
        
        Args:
            playlist_id: Playlist identifier
            
        Returns:
            True if successful
        """
        response = self._request("deletePlaylist", {"id": playlist_id})
        return response is not None
    
    def _normalize_for_comparison(self, text: str, preserve_version: bool = False) -> str:
        """Normalize text for comparison.
        
        Args:
            text: Text to normalize
            preserve_version: Whether to preserve version markers
            
        Returns:
            Normalized text
        """
        text = self._strip_featured(text)
        if not preserve_version:
            # Remove parentheses and brackets content
            text = re.sub(r'\s*[\[\(].*?[\]\)]', '', text)
        text = re.sub(r'[^\w\s]', ' ', text)
        text = ' '.join(text.split())
        return text.lower().strip()
    
    def _has_version_marker(self, text: str) -> Optional[str]:
        """Check if text contains version markers.
        
        Args:
            text: Text to check
            
        Returns:
            Version marker found or None
        """
        text_lower = text.lower()
        for marker in self.VERSION_MARKERS:
            # Use word boundary matching to avoid false positives
            pattern = r'\b' + re.escape(marker) + r'\b'
            if re.search(pattern, text_lower):
                return marker
        return None
    
    def _calculate_match_score(self, search_artist: str, search_title: str,
                              result_artist: str, result_title: str) -> float:
        """Calculate match score (0.0-1.0) using 50% artist + 50% title.
        
        Args:
            search_artist: Search artist name
            search_title: Search title
            result_artist: Result artist name
            result_title: Result title
            
        Returns:
            Match score between 0.0 and 1.0
        """
        artist_ratio = difflib.SequenceMatcher(None, search_artist, result_artist).ratio()
        title_ratio = difflib.SequenceMatcher(None, search_title, result_title).ratio()
        return (artist_ratio * 0.5) + (title_ratio * 0.5)

    def search_song(self, artist: str, title: str, mbid: str = None) -> Optional[str]:
        """Search for a song with fuzzy matching and version detection.
        
        Args:
            artist: Artist name
            title: Song title
            
        Returns:
            Song ID if found, None otherwise
        """
        if mbid:
            # Try a targeted artist+title search first, then validate MBID on the results
            mbid_check_response = self._request("search3", {
                "query": f'"{artist}" "{title}"',
                "songCount": 10,
                "artistCount": 0,
                "albumCount": 0
            })
            if mbid_check_response:
                for song in mbid_check_response.get("searchResult3", {}).get("song", []):
                    if song.get("musicBrainzId") == mbid:
                        logger.debug("MBID exact match: %s - %s",
                                     song.get("artist"), song.get("title"))
                        return song["id"]
            logger.debug("MBID lookup missed for %s, falling through to fuzzy", mbid)

    
        # Step 1: Normalize search terms
        search_artist_norm = self._normalize_for_comparison(artist, preserve_version=False)
        search_title_norm = self._normalize_for_comparison(title, preserve_version=False)
        search_version = self._has_version_marker(title)
        
        # Try multiple search strategies
        search_queries = [
            f'"{artist}" "{title}"',  # Exact artist and title
            f'"{title}"',  # Title only
            f'{artist} {title}',  # Concatenation
        ]
        
        all_songs = []
        for query in search_queries:
            response = self._request("search3", {"query": query, "songCount": self.LIBRARY_SEARCH_LIMIT})
            if response:
                songs = response.get("searchResult3", {}).get("song", [])
                all_songs.extend(songs)
        
        # Remove duplicates by ID
        seen_ids = set()
        unique_songs = []
        for song in all_songs:
            song_id = song.get("id")
            if song_id and song_id not in seen_ids:
                seen_ids.add(song_id)
                unique_songs.append(song)
        
        if not unique_songs:
            return None
        
        # Find best match
        best_match = None
        best_score = 0.0
        
        for song in unique_songs:
            result_artist = song.get("artist", "")
            result_title = song.get("title", "")
            
            # Normalize result
            result_artist_norm = self._normalize_for_comparison(result_artist, preserve_version=False)
            result_title_norm = self._normalize_for_comparison(result_title, preserve_version=False)
            result_version = self._has_version_marker(result_title)
            
            # Calculate match score
            score = self._calculate_match_score(search_artist_norm, search_title_norm,
                                              result_artist_norm, result_title_norm)
            
            # Check if this is a better match
            if score > best_score:
                best_score = score
                best_match = (song["id"], result_artist, result_title, result_version)
        
        if not best_match:
            return None
        
        song_id, match_artist, match_title, match_version = best_match
        
        # Decision logic based on MATCH_THRESHOLD
        if best_score >= self.MATCH_THRESHOLD:
            # Check version compatibility
            if search_version != match_version:
                # Different versions - return None to trigger download
                logger.info("Found different version: %s - %s (%.0f%% match) - search has '%s', library has '%s'",
                          match_artist, match_title, best_score * 100,
                          search_version or "original", match_version or "original")
                return None
            else:
                # Same version or both are originals
                logger.debug("Library match: %s - %s (%.0f%% match)",
                           match_artist, match_title, best_score * 100)
                return song_id
        
        # Score too low
        return None

    def check_for_similar_song(self, artist: str, title: str) -> Optional[str]:
        """Check for similar songs to prevent near-duplicates before downloading.
        
        Args:
            artist: Artist name
            title: Song title
            
        Returns:
            Song ID if similar song found, None otherwise
        """
        
        # Search by artist name
        response = self._request("search3", {"query": f'"{artist}"', "songCount": self.SIMILAR_SEARCH_LIMIT})
        
        if not response:
            return None
        
        songs = response.get("searchResult3", {}).get("song", [])
        
        if not songs:
            return None
        
        # Normalize search terms
        search_artist_norm = self._normalize_for_comparison(artist)
        search_title_norm = self._normalize_for_comparison(title)
        search_has_version = bool(self._has_version_marker(title))
        
        # Check each result for similarity
        for song in songs:
            result_artist = song.get("artist", "")
            result_title = song.get("title", "")
            
            # Check for version markers
            result_has_version = bool(self._has_version_marker(result_title))
            
            # Skip if version markers differ (don't match remix to original)
            if search_has_version != result_has_version:
                continue
            
            # Normalize result
            result_artist_norm = self._normalize_for_comparison(result_artist)
            result_title_norm = self._normalize_for_comparison(result_title)
            
            # Calculate match ratios
            artist_ratio = difflib.SequenceMatcher(None, search_artist_norm, result_artist_norm).ratio()
            title_ratio = difflib.SequenceMatcher(None, search_title_norm, result_title_norm).ratio()
            
            # If both are high similarity, consider it a near-duplicate
            if artist_ratio >= self.SIMILARITY_THRESHOLD and title_ratio >= self.SIMILARITY_THRESHOLD:
                logger.warning("Similar song found in library: %s - %s (artist: %.0f%%, title: %.0f%%)",
                             result_artist, result_title, artist_ratio * 100, title_ratio * 100)
                return song["id"]
        
        return None

    def trigger_scan(self) -> None:
        """Trigger a library scan."""
        self._request("startScan")

    def wait_for_scan(self, max_wait: int = None) -> bool:
        """Wait for library scan to complete.
        
        Args:
            max_wait: Maximum wait time in seconds
            
        Returns:
            True if scan completed, False if timeout
        """
        if max_wait is None:
            max_wait = self.scan_timeout

        start_time = time.time()
        while time.time() - start_time < max_wait:
            time.sleep(3)
            response = self._request("getScanStatus")
            if response:
                scan_status = response.get("scanStatus", {})
                if not scan_status.get("scanning", False):
                    return True
        return False

    def create_playlist(self, name: str, song_ids: List[str]) -> bool:
        """Create or update a playlist.
        
        Args:
            name: Playlist name
            song_ids: List of song IDs
            
        Returns:
            True if successful
        """
        if not song_ids:
            return False

        # Delete existing playlist
        response = self._request("getPlaylists")
        if response:
            playlists = response.get("playlists", {}).get("playlist", [])
            for pl in playlists:
                if pl.get("name") == name:
                    self._request("deletePlaylist", {"id": pl["id"]})
                    time.sleep(1)
                    break

        # Create playlist
        params = subsonic_auth_params(self.username, self.password)
        create_params = {"name": name, **params}
        create_url = f"{self.url}/rest/createPlaylist?{urlencode(create_params)}"

        try:
            r = self.session.get(create_url, timeout=30)
            response = r.json().get("subsonic-response", {})
            if response.get("status") != "ok":
                return False

            playlist_id = response.get("playlist", {}).get("id")
            if not playlist_id:
                return False

            # Add songs
            for song_id in song_ids:
                params = subsonic_auth_params(self.username, self.password)
                form_data = [("playlistId", playlist_id), ("songIdToAdd", song_id)]
                self.session.post(
                    f"{self.url}/rest/updatePlaylist",
                    params=params,
                    data=form_data,
                    timeout=30,
                )
                time.sleep(0.1)

            logger.info("Created playlist: %s (%d songs)", name, len(song_ids))
            return True

        except Exception as e:
            logger.error("Failed to create playlist %s: %s", name, str(e)[:200])
            return False


class OctoFiestaTrigger:
    """Triggers Octo-Fiesta downloads via Subsonic endpoints."""

    def __init__(self, octo_url: str, username: str, password: str, dry_run: bool = False):
        """Initialize Octo-Fiesta trigger client.
        
        Args:
            octo_url: Octo-Fiesta server URL
            username: Username for authentication
            password: Password for authentication
            dry_run: If True, only log actions without executing
        """
        self.octo_url = octo_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.dry_run = dry_run

    def _request(self, endpoint: str, extra_params: dict = None) -> Optional[dict]:
        """Make Subsonic API request.
        
        Args:
            endpoint: API endpoint
            extra_params: Additional parameters
            
        Returns:
            JSON response or None on error
        """
        params = subsonic_auth_params(self.username, self.password)
        if extra_params:
            params.update(extra_params)

        try:
            r = self.session.get(f"{self.octo_url}/rest/{endpoint}", params=params, timeout=30)
            r.raise_for_status()
            response = r.json().get("subsonic-response", {})
            if response.get("status") == "failed":
                return None
            return response
        except Exception:
            return None

    def search_and_trigger_download(self, artist: str, title: str) -> Tuple[bool, str]:
        """Search and trigger download.
        
        Args:
            artist: Artist name
            title: Song title
            
        Returns:
            Tuple of (success, result_id_or_error)
        """
        if self.dry_run:
            logger.info("[DRY RUN] Would download: %s - %s", artist, title)
            return True, "dry-run"

        logger.debug("Searching: %s - %s", artist, title)
        response = self._request("search3", {"query": f"{artist} {title}", "songCount": 5})

        if not response:
            return False, "API error"

        songs = response.get("searchResult3", {}).get("song", [])
        if not songs:
            return False, "Not found"

        best_match = songs[0]
        song_id = best_match["id"]

        logger.debug("Triggering download (stream warmup)")
        stream_url = f"{self.octo_url}/rest/stream"
        params = subsonic_auth_params(self.username, self.password)
        params["id"] = song_id

        try:
            r = self.session.get(stream_url, params=params, stream=True, timeout=10)
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    break
            return True, song_id
        except Exception as e:
            return False, str(e)[:100]
