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
                    pushed_to_lidarr TEXT
                )
            """)
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
                "SELECT missing_count FROM missing_artists WHERE artist=?",
                (key,),
            ).fetchone()
            if row:
                new_count = row[0] + 1
                conn.execute(
                    "UPDATE missing_artists SET missing_count=?, last_seen=? WHERE artist=?",
                    (new_count, now, key),
                )
            else:
                new_count = 1
                conn.execute(
                    """INSERT INTO missing_artists
                       (artist, artist_display, missing_count, first_seen, last_seen)
                       VALUES (?, ?, 1, ?, ?)""",
                    (key, display, now, now),
                )
            conn.commit()
        return new_count

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

    def get_pending_pushes(self, threshold: int) -> List[str]:
        """Return display names of artists at/above threshold and not yet pushed."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT artist_display FROM missing_artists
                   WHERE missing_count >= ? AND pushed_to_lidarr IS NULL""",
                (threshold,),
            ).fetchall()
        return [r[0] for r in rows]
