"""SQLite cache for song ratings and data persistence"""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional


logger = logging.getLogger(__name__)


# Constants
LOW_RATING_MIN = 1
LOW_RATING_MAX = 2


class RatingsCache:
    """SQLite cache for song ratings to avoid repeated scans."""

    def __init__(self, db_path: Path):
        """Initialize ratings cache.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ratings (
                    song_id TEXT PRIMARY KEY,
                    artist TEXT NOT NULL,
                    title TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    last_updated TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rating
                ON ratings(rating)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS missing_artists (
                    artist TEXT PRIMARY KEY,
                    artist_display TEXT NOT NULL,
                    missing_count INTEGER NOT NULL DEFAULT 0,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    pushed_to_lidarr TEXT,
                    push_attempt_count INTEGER NOT NULL DEFAULT 0
                )
            """)
            existing = {
                row[1]
                for row in conn.execute("PRAGMA table_info(missing_artists)")
            }
            if "push_attempt_count" not in existing:
                conn.execute(
                    "ALTER TABLE missing_artists ADD COLUMN "
                    "push_attempt_count INTEGER NOT NULL DEFAULT 0"
                )
            conn.commit()

    def get_last_scan_date(self) -> Optional[str]:
        """Get the last full scan date.
        
        Returns:
            Last scan date string or None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT value FROM cache_metadata WHERE key = 'last_scan_date'"
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def set_last_scan_date(self, date: str) -> None:
        """Update the last full scan date.
        
        Args:
            date: Date string to store
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO cache_metadata (key, value)
                   VALUES ('last_scan_date', ?)""",
                (date,)
            )
            conn.commit()

    def update_rating(self, song_id: str, artist: str, title: str, rating: int) -> None:
        """Update or insert a song rating.
        
        Args:
            song_id: Unique song identifier
            artist: Artist name
            title: Song title
            rating: Rating value (0-5)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO ratings
                   (song_id, artist, title, rating, last_updated)
                   VALUES (?, ?, ?, ?, ?)""",
                (song_id, artist, title, rating, datetime.now().isoformat())
            )
            conn.commit()

    def get_low_rated_songs(self) -> List[Dict]:
        """Get all songs rated 1-2 stars from cache.
        
        Returns:
            List of song dictionaries with id, artist, title, rating
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT song_id, artist, title, rating
                   FROM ratings
                   WHERE rating BETWEEN ? AND ?""",
                (LOW_RATING_MIN, LOW_RATING_MAX)
            )
            return [
                {"id": row[0], "artist": row[1], "title": row[2], "rating": row[3]}
                for row in cursor.fetchall()
            ]

    def clear_cache(self) -> None:
        """Clear all ratings from cache."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM ratings")
            conn.commit()

    @staticmethod
    def _normalize_artist(name: str) -> str:
        return name.strip().lower()

    def record_missing_track(self, artist: str) -> int:
        """Record that a track by `artist` was missing.

        Increments the count for that artist (case-insensitive, whitespace-trimmed).
        Returns the new count.
        """
        key = self._normalize_artist(artist)
        display = artist.strip()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """INSERT INTO missing_artists
                   (artist, artist_display, missing_count, first_seen, last_seen)
                   VALUES (?, ?, 1, ?, ?)
                   ON CONFLICT(artist) DO UPDATE SET
                     missing_count = missing_count + 1,
                     last_seen = excluded.last_seen
                   RETURNING missing_count""",
                (key, display, now, now),
            ).fetchone()
            conn.commit()
        return row[0]

    def mark_pushed(self, artist: str) -> None:
        """Mark an artist as pushed to Lidarr."""
        key = self._normalize_artist(artist)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE missing_artists SET pushed_to_lidarr=? WHERE artist=?",
                (now, key),
            )
            conn.commit()

    def increment_push_attempt(self, artist: str) -> int:
        """Record a failed push attempt; return new attempt count."""
        key = self._normalize_artist(artist)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE missing_artists SET push_attempt_count = push_attempt_count + 1 "
                "WHERE artist=?",
                (key,),
            )
            row = conn.execute(
                "SELECT push_attempt_count FROM missing_artists WHERE artist=?",
                (key,),
            ).fetchone()
            conn.commit()
        if row is None:
            logger.warning(
                "increment_push_attempt called for unknown artist %r — no row updated",
                artist,
            )
            return 0
        return row[0]

    def get_pending_pushes(self, threshold: int, max_attempts: int = 5) -> List[str]:
        """Return display names of artists at/above threshold, not yet pushed,
        and below max failed attempts."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT artist_display FROM missing_artists
                   WHERE missing_count >= ?
                     AND pushed_to_lidarr IS NULL
                     AND push_attempt_count < ?""",
                (threshold, max_attempts),
            ).fetchall()
        return [r[0] for r in rows]

    def is_pending_push(
        self, artist: str, threshold: int, max_attempts: int = 5
    ) -> bool:
        """True if `artist` is at/above threshold, not yet pushed, and below max attempts."""
        key = self._normalize_artist(artist)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT 1 FROM missing_artists
                   WHERE artist = ?
                     AND missing_count >= ?
                     AND pushed_to_lidarr IS NULL
                     AND push_attempt_count < ?""",
                (key, threshold, max_attempts),
            ).fetchone()
        return row is not None
