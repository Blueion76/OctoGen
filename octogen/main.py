#!/usr/bin/env python3
"""OctoGen - Main orchestration engine and entry point

This module contains the core OctoGenEngine class and main() entry point.
"""

import sys
import os
import json
import logging
import random
import time
import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from collections import Counter

# Import from refactored modules
from octogen.utils.auth import subsonic_auth_params
from octogen.utils.retry import retry_with_backoff
from octogen.utils.secrets import load_secret
from octogen.utils.helpers import (
    print_banner, 
    acquire_lock, 
    LOW_RATING_MIN, 
    LOW_RATING_MAX,
    COOLDOWN_EXIT_DELAY_SECONDS,
    DEFAULT_DAILY_MIX_GENRES
)
from octogen.storage.cache import RatingsCache
from octogen.api.navidrome import NavidromeAPI, OctoFiestaTrigger
from octogen.api.lastfm import LastFMAPI
from octogen.api.listenbrainz import ListenBrainzAPI
from octogen.api.audiomuse import AudioMuseClient
from octogen.api.spotify import SpotifyImporter
from octogen.api.deezer import DeezerImporter
from octogen.ai.engine import AIRecommendationEngine, GEMINI_SDK_AVAILABLE
from octogen.models.tracker import ServiceTracker, RunTracker
from octogen.web.health import write_health_status
from octogen.scheduler.cron import calculate_next_run, wait_until, calculate_cron_interval
from octogen.monitoring.metrics import setup_metrics, record_playlist_created, record_song_downloaded, record_run_complete

# Try to import croniter for scheduling support
try:
    from croniter import croniter
    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False

logger = logging.getLogger(__name__)

# Data directory from environment (defaults to /data in Docker)
BASE_DIR = Path(os.getenv("OCTOGEN_DATA_DIR", Path(__file__).parent.parent.absolute()))
RATINGS_DB = BASE_DIR / "octogen_cache.db"
LOCK_FILE = BASE_DIR / "octogen.lock"

# Ensure data directory exists
BASE_DIR.mkdir(parents=True, exist_ok=True)

class OctoGenEngine:
    """Main orchestrator with environment variable configuration."""

    def __init__(self, dry_run: bool = False):
        # Load configuration from environment variables
        self.config = self._load_config_from_env()
        self._validate_env_config()

        self.dry_run = dry_run
        if dry_run:
            logger.info("=" * 70)
            logger.info("DRY RUN MODE - No downloads or playlist changes will be made")
            logger.info("=" * 70)

        # Initialize ratings cache
        self.ratings_cache = RatingsCache(RATINGS_DB)

        # Initialize APIs
        self.nd = NavidromeAPI(
            self.config["navidrome"]["url"],
            self.config["navidrome"]["username"],
            self.config["navidrome"]["password"],
            self.ratings_cache,
            self.config
        )

        if not self.nd.test_connection():
            logger.error("Cannot connect to Navidrome")
            sys.exit(1)

        self.octo = OctoFiestaTrigger(
            self.config["octofiesta"]["url"],
            self.config["navidrome"]["username"],
            self.config["navidrome"]["password"],
            dry_run=dry_run
        )

        # Initialize AI engine (optional if other services are configured)
        self.ai = None
        if self.config["ai"]["api_key"]:
            max_context = int(self.config.get("ai", {}).get("max_context_songs", 500))
            max_output = int(self.config.get("ai", {}).get("max_output_tokens", 65535))
            backend = self.config.get("ai", {}).get("backend", "gemini")
            request_timeout = int(self.config.get("ai", {}).get("request_timeout", 300))

            self.ai = AIRecommendationEngine(
                api_key=self.config["ai"]["api_key"],
                model=self.config["ai"]["model"],
                backend=backend,
                base_url=self.config.get("ai", {}).get("base_url"),
                max_context_songs=max_context,
                max_output_tokens=max_output,
                request_timeout=request_timeout,
            )
            logger.info("✓ AI engine initialized")
        else:
            logger.info("ℹ️  AI engine not configured (using alternative music sources)")


        # Optional services
        self.lastfm: Optional[LastFMAPI] = None
        if self.config.get("lastfm", {}).get("enabled", False):
            self.lastfm = LastFMAPI(
                self.config["lastfm"]["api_key"],
                self.config["lastfm"]["username"],
            )

        self.listenbrainz: Optional[ListenBrainzAPI] = None
        if self.config.get("listenbrainz", {}).get("enabled", False):
            self.listenbrainz = ListenBrainzAPI(
                self.config["listenbrainz"]["username"],
                self.config["listenbrainz"].get("token"),
            )

        # Initialize AudioMuse client if enabled
        self.audiomuse_client = None
        if self.config.get("audiomuse", {}).get("enabled", False):
            audiomuse_url = self.config["audiomuse"]["url"]
            audiomuse_client = AudioMuseClient(
                base_url=audiomuse_url,
                ai_provider=self.config["audiomuse"]["ai_provider"],
                ai_model=self.config["audiomuse"]["ai_model"],
                api_key=self.config["audiomuse"]["ai_api_key"] or None
            )
            if audiomuse_client.check_health():
                logger.info("✅ AudioMuse-AI connected at %s", audiomuse_url)
                self.audiomuse_client = audiomuse_client
            else:
                logger.warning("⚠️ AudioMuse-AI not accessible at %s, falling back to LLM-only mode", audiomuse_url)
                self.audiomuse_client = None

        self.spotify_importer: Optional[SpotifyImporter] = None
        if self.config.get("spotify", {}).get("enabled", False):
            try:
                spotify_importer = SpotifyImporter(
                    client_id=self.config["spotify"]["client_id"],
                    client_secret=self.config["spotify"]["client_secret"],
                )
            except ImportError as e:
                logger.warning("⚠️ Spotify importer disabled: missing optional dependency (%s)", e)
            except Exception as e:
                logger.warning("⚠️ Spotify importer disabled due to initialization error: %s", e)
            else:
                if not spotify_importer.check_connection():
                    logger.warning("⚠️ Spotify credentials invalid or connection failed")
                else:
                    self.spotify_importer = spotify_importer
                    logger.info("✅ Spotify importer connected")

        self.deezer_importer: Optional[DeezerImporter] = None
        if self.config.get("deezer", {}).get("enabled", False):
            try:
                deezer_importer = DeezerImporter()
            except ImportError as e:
                logger.warning("⚠️ Deezer importer disabled: missing optional dependency (%s)", e)
            except Exception as e:
                logger.warning("⚠️ Deezer importer disabled due to initialization error: %s", e)
            else:
                if not deezer_importer.check_connection():
                    logger.warning("⚠️ Deezer connection failed")
                else:
                    self.deezer_importer = deezer_importer
                    logger.info("✅ Deezer importer connected")

        # Stats
        self.stats = {
            "playlists_created": 0,
            "songs_found": 0,
            "songs_downloaded": 0,
            "songs_failed": 0,
            "songs_skipped_low_rating": 0,
            "songs_skipped_duplicate": 0,
            "duplicates_prevented": 0,
            "ai_calls": 0,
        }

        # Track processed songs to avoid duplicates
        self.processed_songs: Set[Tuple[str, str]] = set()

        # Initialize service tracker
        self.service_tracker = ServiceTracker()

        # Configurable delays
        self.download_delay = self.config.get("performance", {}).get("download_delay_seconds", 10)
        self.post_scan_delay = self.config.get("performance", {}).get("post_scan_delay_seconds", 3)

    def _load_config_from_env(self) -> dict:
        """Load all configuration from environment variables"""
        logger.info("Loading configuration from environment variables...")

        # Check required variables (except AI_API_KEY which is now optional)
        required_vars = [
            "NAVIDROME_URL",
            "NAVIDROME_USER",
            "NAVIDROME_PASSWORD",
            "OCTOFIESTA_URL"
        ]

        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            logger.error("❌ Missing required environment variables: %s", ", ".join(missing))
            logger.error("")
            logger.error("Required variables:")
            logger.error("  NAVIDROME_URL       - Navidrome server URL")
            logger.error("  NAVIDROME_USER      - Navidrome username")
            logger.error("  NAVIDROME_PASSWORD  - Navidrome password")
            logger.error("  OCTOFIESTA_URL      - Octo-Fiesta server URL")
            logger.error("")
            logger.error("See ENV_VARS.md for complete reference")
            sys.exit(1)

        config = {
            "navidrome": {
                "url": os.getenv("NAVIDROME_URL"),
                "username": os.getenv("NAVIDROME_USER"),
                "password": os.getenv("NAVIDROME_PASSWORD")
            },
            "octofiesta": {
                "url": os.getenv("OCTOFIESTA_URL")
            },
            "ai": {
                "api_key": os.getenv("AI_API_KEY", ""),
                "model": os.getenv("AI_MODEL", "gemini-2.5-flash"),
                "backend": os.getenv("AI_BACKEND", "gemini"),
                "base_url": os.getenv("AI_BASE_URL"),
                "max_context_songs": self._get_env_int("AI_MAX_CONTEXT_SONGS", 500),
                "max_output_tokens": self._get_env_int("AI_MAX_OUTPUT_TOKENS", 65535),
                "request_timeout": max(30, self._get_env_int("AI_REQUEST_TIMEOUT", 300)),
            },
            "performance": {
                "album_batch_size": self._get_env_int("PERF_ALBUM_BATCH_SIZE", 500),
                "max_albums_scan": self._get_env_int("PERF_MAX_ALBUMS_SCAN", 10000),
                "scan_timeout": self._get_env_int("PERF_SCAN_TIMEOUT", 60),
                "download_delay_seconds": self._get_env_int("PERF_DOWNLOAD_DELAY", 10),
                "post_scan_delay_seconds": self._get_env_int("PERF_POST_SCAN_DELAY", 30)
            },
            "lastfm": {
                "enabled": self._get_env_bool("LASTFM_ENABLED", False),
                "api_key": os.getenv("LASTFM_API_KEY", ""),
                "username": os.getenv("LASTFM_USERNAME", "")
            },
            "listenbrainz": {
                "enabled": self._get_env_bool("LISTENBRAINZ_ENABLED", False),
                "username": os.getenv("LISTENBRAINZ_USERNAME", ""),
                "token": os.getenv("LISTENBRAINZ_TOKEN", "")
            },
            "audiomuse": {
                "enabled": self._get_env_bool("AUDIOMUSE_ENABLED", False),
                "url": os.getenv("AUDIOMUSE_URL", "http://localhost:8000"),
                "ai_provider": os.getenv("AUDIOMUSE_AI_PROVIDER", "gemini"),
                "ai_model": os.getenv("AUDIOMUSE_AI_MODEL", "gemini-2.5-flash"),
                "ai_api_key": os.getenv("AUDIOMUSE_AI_API_KEY", ""),
                "songs_per_mix": self._get_env_int("AUDIOMUSE_SONGS_PER_MIX", 25),
                "llm_songs_per_mix": self._get_env_int("LLM_SONGS_PER_MIX", 5)
            },
            "spotify": {
                "enabled": self._get_env_bool("SPOTIFY_IMPORT_ENABLED", False),
                "client_id": load_secret("SPOTIFY_CLIENT_ID", ""),
                "client_secret": load_secret("SPOTIFY_CLIENT_SECRET", ""),
                "playlist_urls": os.getenv("SPOTIFY_PLAYLIST_URLS", ""),
            },
            "deezer": {
                "enabled": self._get_env_bool("DEEZER_IMPORT_ENABLED", False),
                "playlist_urls": os.getenv("DEEZER_PLAYLIST_URLS", ""),
            },
        }

        # Log configuration (without secrets)
        logger.info("✓ Navidrome: %s", config['navidrome']['url'])
        logger.info("✓ Octo-Fiesta: %s", config['octofiesta']['url'])
        if config['lastfm']['enabled']:
            logger.info("✓ Last.fm enabled: %s", config['lastfm']['username'])
        if config['listenbrainz']['enabled']:
            logger.info("✓ ListenBrainz enabled: %s", config['listenbrainz']['username'])
        if config['audiomuse']['enabled']:
            logger.info("✓ AudioMuse-AI enabled: %s", config['audiomuse']['url'])
        if config['spotify']['enabled']:
            logger.info("✓ Spotify import enabled")
        if config['deezer']['enabled']:
            logger.info("✓ Deezer import enabled")

        return config

    def _get_env_bool(self, key: str, default: bool = False) -> bool:
        """Get boolean from environment variable"""
        value = os.getenv(key, str(default)).lower()
        return value in ('true', '1', 'yes', 'on')

    def _get_env_int(self, key: str, default: int) -> int:
        """Get integer from environment variable"""
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default

    def _validate_env_config(self) -> None:
        """Validate environment configuration"""
        errors = []
        
        # Check if at least one music source is configured
        has_ai = bool(self.config["ai"]["api_key"])
        has_audiomuse = self.config.get("audiomuse", {}).get("enabled", False)
        has_lastfm = self.config.get("lastfm", {}).get("enabled", False)
        has_listenbrainz = self.config.get("listenbrainz", {}).get("enabled", False)
        has_spotify = self.config.get("spotify", {}).get("enabled", False)
        has_deezer = self.config.get("deezer", {}).get("enabled", False)
        
        if not (has_ai or has_audiomuse or has_lastfm or has_listenbrainz or has_spotify or has_deezer):
            logger.error("=" * 70)
            logger.error("❌ No music source configured!")
            logger.error("❌ OctoGen requires at least one of:")
            logger.error("   1. AI_API_KEY (for LLM-based recommendations)")
            logger.error("   2. AUDIOMUSE_ENABLED=true (for AudioMuse-AI sonic analysis)")
            logger.error("   3. LASTFM_ENABLED=true (for Last.fm recommendations)")
            logger.error("   4. LISTENBRAINZ_ENABLED=true (for ListenBrainz recommendations)")
            logger.error("   5. SPOTIFY_IMPORT_ENABLED=true (for Spotify playlist import)")
            logger.error("   6. DEEZER_IMPORT_ENABLED=true (for Deezer playlist import)")
            logger.error("=" * 70)
            sys.exit(1)
        
        # Log available music sources
        sources = []
        if has_ai:
            sources.append("LLM")
        if has_audiomuse:
            sources.append("AudioMuse-AI")
        if has_lastfm:
            sources.append("Last.fm")
        if has_listenbrainz:
            sources.append("ListenBrainz")
        if has_spotify:
            sources.append("Spotify Import")
        if has_deezer:
            sources.append("Deezer Import")
        logger.info("✓ Music sources: %s", ", ".join(sources))
        
        # Validate URLs
        for name, url in [
            ("Navidrome", self.config["navidrome"]["url"]),
            ("Octo-Fiesta", self.config["octofiesta"]["url"])
        ]:
            if not url:
                errors.append(f"{name} URL is empty")
            elif not url.startswith(("http://", "https://")):
                errors.append(f"Invalid {name} URL: {url} (must start with http:// or https://)")
            elif url.endswith("/"):
                logger.warning("%s URL ends with '/'. This will be stripped automatically.", name)
        
        # Validate AI model for backend (only if AI is configured)
        if has_ai:
            backend = self.config["ai"]["backend"]
            model = self.config["ai"]["model"]
            
            if backend == "gemini" and not model.startswith("gemini"):
                logger.warning("Backend is 'gemini' but model is '%s' - this may cause errors", model)
            elif backend == "openai" and model.startswith("gemini"):
                logger.warning("Backend is 'openai' but model is '%s' - this may cause errors", model)
        
        # Validate optional services
        if self.config.get("lastfm", {}).get("enabled", False):
            if not self.config["lastfm"].get("api_key"):
                errors.append("Last.fm is enabled but LASTFM_API_KEY is empty")
            if not self.config["lastfm"].get("username"):
                errors.append("Last.fm is enabled but LASTFM_USERNAME is empty")
        
        if self.config.get("listenbrainz", {}).get("enabled", False):
            if not self.config["listenbrainz"].get("username"):
                errors.append("ListenBrainz is enabled but LISTENBRAINZ_USERNAME is empty")

        if self.config.get("spotify", {}).get("enabled", False):
            if not self.config["spotify"].get("client_id"):
                errors.append("Spotify import is enabled but SPOTIFY_CLIENT_ID is empty")
            if not self.config["spotify"].get("client_secret"):
                errors.append("Spotify import is enabled but SPOTIFY_CLIENT_SECRET is empty")
            if not self.config["spotify"].get("playlist_urls"):
                errors.append("Spotify import is enabled but SPOTIFY_PLAYLIST_URLS is empty")

        if self.config.get("deezer", {}).get("enabled", False):
            if not self.config["deezer"].get("playlist_urls"):
                errors.append("Deezer import is enabled but DEEZER_PLAYLIST_URLS is empty")
        
        # Validate performance settings
        perf = self.config.get("performance", {})
        if perf.get("download_delay_seconds", 10) < 1:
            logger.warning("PERF_DOWNLOAD_DELAY is very low (%ds) - may cause issues", 
                          perf["download_delay_seconds"])
        
        # Report errors
        if errors:
            logger.error("=" * 70)
            logger.error("CONFIGURATION ERRORS FOUND:")
            logger.error("=" * 70)
            for error in errors:
                logger.error("  ❌ %s", error)
            logger.error("=" * 70)
            logger.error("Please fix the above errors and try again.")
            logger.error("See your environment variables or docker-compose.yml")
            sys.exit(1)
        
        logger.info("✅ Configuration validated successfully")

    def _check_run_cooldown(self) -> bool:
        """Check if enough time has passed since last run with smart service-based cooldown.
        
        Returns True if we should run, False if still in cooldown.
        """
        run_tracker_file = BASE_DIR / "octogen_last_run.json"
        
        # Determine cooldown periods
        schedule_cron = os.getenv("SCHEDULE_CRON", "").strip()
        
        if schedule_cron and schedule_cron.lower() not in ("manual", "false", "no", "off", "disabled"):
            # Use 90% of detected cron interval for full cooldown
            detected_interval = calculate_cron_interval(schedule_cron)
            full_cooldown_hours = detected_interval * 0.9
            logger.info("🕐 Cooldown period: %.1f hours (90%% of cron interval)", full_cooldown_hours)
        else:
            # Manual mode - use environment variable for full cooldown
            full_cooldown_hours = float(os.getenv("MIN_RUN_INTERVAL_HOURS", "6"))
            logger.info("🕐 Cooldown period: %.1f hours (manual mode)", full_cooldown_hours)
        
        # Check last run time
        if not run_tracker_file.exists():
            logger.info("✅ First run ever - no cooldown")
            return True  # First run ever
        
        try:
            with open(run_tracker_file, 'r') as f:
                data = json.load(f)
                last_run_str = data.get('last_run_timestamp')
                services = data.get('services', {})
                
                if not last_run_str:
                    logger.info("✅ No last run timestamp - allowing run")
                    return True
                
                last_run = datetime.fromisoformat(last_run_str)
                now = datetime.now(timezone.utc)
                
                # Ensure last_run is timezone-aware for comparison
                if last_run.tzinfo is None:
                    last_run = last_run.replace(tzinfo=timezone.utc)
                
                hours_since_last = (now - last_run).total_seconds() / 3600
                
                # Always apply full cooldown to respect schedule
                # This prevents constant re-runs when only Last.fm/ListenBrainz succeed
                cooldown_to_apply = full_cooldown_hours
                
                if hours_since_last < cooldown_to_apply:
                    logger.info("=" * 70)
                    logger.info("⏭️  OctoGen ran %.1f hours ago (cooldown: %.1f hours)", 
                                 hours_since_last, cooldown_to_apply)
                    logger.info("⏭️  Skipping to prevent duplicate run")
                    logger.info("⏭️  Last run: %s", last_run.strftime("%Y-%m-%d %H:%M:%S"))
                    logger.info("⏭️  Next run allowed after: %s", 
                                 (last_run + timedelta(hours=cooldown_to_apply)).strftime("%Y-%m-%d %H:%M:%S"))
                    
                    # Show what services succeeded/failed last time
                    if services:
                        logger.info("⏭️  Last run services:")
                        for service_name, service_data in services.items():
                            status = "✅" if service_data.get("success") else "❌"
                            reason = f" ({service_data.get('reason')})" if not service_data.get("success") else ""
                            logger.info("⏭️    %s %s%s", status, service_name, reason)
                    
                    logger.info("=" * 70)
                    return False
                
                logger.info("✅ Cooldown passed (%.1f hours since last run)", hours_since_last)
                
                # Show what services succeeded/failed last time for context
                if services:
                    logger.info("ℹ️  Last run services:")
                    for service_name, service_data in services.items():
                        status = "✅" if service_data.get("success") else "❌"
                        reason = f" ({service_data.get('reason')})" if not service_data.get("success") else ""
                        logger.info("   %s %s%s", status, service_name, reason)
                
                return True
                
        except Exception as e:
            logger.warning("Could not read run tracker: %s", str(e))
            return True  # Allow run if we can't read tracker

    def _record_successful_run(self) -> None:
        """Record that a successful run completed with service tracking data."""
        run_tracker_file = BASE_DIR / "octogen_last_run.json"
        
        try:
            # Use single timestamp to ensure consistency
            now = datetime.now(timezone.utc)
            
            # Prepare service tracker data
            services_data = {}
            for service_name, service_info in self.service_tracker.services.items():
                services_data[service_name] = service_info
            
            # Calculate next scheduled run if SCHEDULE_CRON is set
            next_scheduled_run = None
            schedule_cron = os.getenv("SCHEDULE_CRON", "").strip()
            
            if schedule_cron and schedule_cron.lower() not in ("manual", "false", "no", "off", "disabled"):
                try:
                    # Import croniter if available
                    if CRONITER_AVAILABLE:
                        from croniter import croniter
                        cron = croniter(schedule_cron, now)
                        next_run_time = cron.get_next(datetime)
                        next_scheduled_run = next_run_time.isoformat()
                        logger.debug(f"Next scheduled run: {next_run_time.strftime('%Y-%m-%d %H:%M:%S')}")
                except Exception as e:
                    logger.warning(f"Could not calculate next scheduled run: {e}")
            
            with open(run_tracker_file, 'w') as f:
                json.dump({
                    'last_run_timestamp': now.isoformat(),
                    'last_run_date': now.strftime("%Y-%m-%d"),
                    'last_run_formatted': now.strftime("%Y-%m-%d %H:%M:%S"),
                    'next_scheduled_run': next_scheduled_run,
                    'services': services_data
                }, f, indent=2)
            logger.info("✓ Recorded successful run timestamp with service tracking")
        except Exception as e:
            logger.error("Could not write run tracker: %s", str(e))

    def _is_duplicate(self, artist: str, title: str) -> bool:
        """Check if song was already processed."""
        key = (artist.lower().strip(), title.lower().strip())
        if key in self.processed_songs:
            return True
        self.processed_songs.add(key)
        return False

    def _check_and_skip_low_rating(self, song_id: str, artist: str, title: str) -> bool:
        """Check rating and return True if should skip."""
        rating = self.nd.get_song_rating(song_id)
        if LOW_RATING_MIN <= rating <= LOW_RATING_MAX:
            logger.debug("Skipping low-rated: %s - %s (%d stars)", artist, title, rating)
            self.stats["songs_skipped_low_rating"] += 1
            return True
        return False

    def _process_single_recommendation(self, rec: Dict) -> Optional[str]:
        """Process a single recommendation and return song ID if successful."""
        artist = (rec.get("artist") or "").strip()
        title = (rec.get("title") or "").strip()
        mbid   = rec.get("mbid")
        
        if not artist or not title:
            return None

        # Priority 1: Check for duplicates (already processed)
        if self._is_duplicate(artist, title):
            logger.debug("Skipping duplicate: %s - %s", artist, title)
            self.stats["songs_skipped_duplicate"] += 1
            return None

        # Priority 2: Search library thoroughly with fuzzy matching
        logger.debug("Checking library for: %s - %s", artist, title)
        song_id = self.nd.search_song(artist, title, mbid=mbid)

        if song_id:
            if self._check_and_skip_low_rating(song_id, artist, title):
                return None
            logger.info("Using library version: %s - %s", artist, title)
            self.stats["songs_found"] += 1
            return song_id

        # Priority 3: Check for similar songs to prevent near-duplicates
        logger.debug("Checking for similar songs: %s - %s", artist, title)
        similar_song_id = self.nd.check_for_similar_song(artist, title)
        
        if similar_song_id:
            if self._check_and_skip_low_rating(similar_song_id, artist, title):
                return None
            logger.info("Using similar song from library: %s - %s", artist, title)
            self.stats["songs_found"] += 1
            self.stats["duplicates_prevented"] += 1
            return similar_song_id

        # Priority 4: Download only if definitely not in library
        logger.info("Not in library, downloading: %s - %s", artist, title)
        
        if self.dry_run:
            return None

        success, _result = self.octo.search_and_trigger_download(artist, title)

        if not success:
            self.stats["songs_failed"] += 1
            return None

        # Wait and rescan
        time.sleep(self.download_delay)
        self.nd.trigger_scan()
        self.nd.wait_for_scan()
        time.sleep(self.post_scan_delay)

        song_id = self.nd.search_song(artist, title, mbid=mbid)

        if song_id:
            if self._check_and_skip_low_rating(song_id, artist, title):
                return None
            self.stats["songs_downloaded"] += 1
            return song_id
        else:
            self.stats["songs_failed"] += 1
            return None

    def _process_recommendations(
        self,
        playlist_name: str,
        recommendations: List[Dict],
        max_songs: int = 100,
    ) -> List[str]:
        """Process recommendations with strict-fill and per-playlist dedup.
    
        Keeps scanning/downloading in up to 3 rounds until len(song_ids) == max_songs
        or all candidates are exhausted. Dedup is scoped per-playlist so every
        playlist can independently fill to max_songs.
        """
        MAX_ROUNDS = 3
    
        # Give ourselves a generous candidate pool (5x target) to survive skips/failures
        max_candidates = min(len(recommendations), max(50, max_songs * 5))
    
        song_ids: List[str] = []
        playlist_seen: Set[Tuple[str, str]] = set()  # per-playlist dedup
        download_attempted: Set[Tuple[str, str]] = set()
    
        idx = 0
    
        def seen_key(a: str, t: str) -> Tuple[str, str]:
            return (a.lower().strip(), t.lower().strip())
    
        logger.info(
            "Processing playlist '%s': %d songs to check (target=%d, max_candidates=%d)",
            playlist_name, len(recommendations), max_songs, max_candidates
        )
    
        for round_num in range(1, MAX_ROUNDS + 1):
            needs_download: List[Tuple[str, str, Optional[str]]] = []
    
            # Phase 1: scan candidates until we have enough confirmed + pending to hit target
            while idx < max_candidates and (len(song_ids) + len(needs_download)) < max_songs:
                rec = recommendations[idx]
                idx += 1
    
                artist = (rec.get("artist") or "").strip()
                title = (rec.get("title") or "").strip()
                mbid = rec.get("mbid")
    
                if not artist or not title:
                    continue
    
                k = seen_key(artist, title)
                if k in playlist_seen:
                    self.stats["songs_skipped_duplicate"] += 1
                    continue
                playlist_seen.add(k)
    
                checked = len(song_ids) + len(needs_download) + 1
                if checked % 10 == 1 or checked == max_songs:
                    logger.info(" [%s] Checking library: %d/%d", playlist_name, checked, max_songs)
    
                # MBID-aware lookup (falls back internally if mbid is None or misses)
                song_id = self.nd.search_song(artist, title, mbid=mbid)  
    
                if song_id:
                    if not self._check_and_skip_low_rating(song_id, artist, title):
                        song_ids.append(song_id)
                        self.stats["songs_found"] += 1
                else:
                    similar_song_id = self.nd.check_for_similar_song(artist, title)
                    if similar_song_id:
                        if not self._check_and_skip_low_rating(similar_song_id, artist, title):
                            song_ids.append(similar_song_id)
                            self.stats["songs_found"] += 1
                            self.stats["duplicates_prevented"] += 1
                    elif not self.dry_run and k not in download_attempted:
                        needs_download.append((artist, title, mbid))  
                        download_attempted.add(k)
    
                if len(song_ids) >= max_songs:
                    break
    
            # Phase 2: batch download everything collected this round
            if needs_download and not self.dry_run:
                logger.info(
                    " [%s] Round %d/%d: Downloading %d missing songs in batch...",
                    playlist_name, round_num, MAX_ROUNDS, len(needs_download)
                )
    
                downloaded_count = 0
                for d_idx, (artist, title, _mbid) in enumerate(needs_download, 1):
                    if d_idx % 5 == 0 or d_idx == 1 or d_idx == len(needs_download):
                        logger.info(" [%s] Download progress: %d/%d", playlist_name, d_idx, len(needs_download))
    
                    success, _result = self.octo.search_and_trigger_download(artist, title)
                    if success:
                        downloaded_count += 1
    
                if downloaded_count > 0:
                    logger.info(" [%s] Waiting for downloads to settle...", playlist_name)
                    wait_time = self.download_delay * min(downloaded_count, 5)
                    time.sleep(wait_time)
    
                    logger.info(" [%s] Triggering library scan...", playlist_name)
                    self.nd.trigger_scan()
                    self.nd.wait_for_scan()
                    time.sleep(self.post_scan_delay)
    
                    logger.info(" [%s] Checking for downloaded songs...", playlist_name)
                    for artist, title, mbid in needs_download:
                        if len(song_ids) >= max_songs:
                            break
    
                        # MBID-aware re-check after scan
                        song_id = self.nd.search_song(artist, title, mbid=mbid)  
    
                        if song_id and not self._check_and_skip_low_rating(song_id, artist, title):
                            song_ids.append(song_id)
                            self.stats["songs_downloaded"] += 1
                        elif not song_id:
                            self.stats["songs_failed"] += 1
                else:
                    logger.warning(" [%s] All %d download attempts failed", playlist_name, len(needs_download))
                    self.stats["songs_failed"] += len(needs_download)
    
            elif needs_download and self.dry_run:
                logger.info(" [%s] [DRY RUN] Would download %d songs", playlist_name, len(needs_download))
    
            if not needs_download or idx >= max_candidates:
                break  # nothing left to try
    
        if len(song_ids) < max_songs:
            logger.warning(
                " [%s] Underfilled: %d/%d songs (pool exhausted after %d candidates)",
                playlist_name, len(song_ids), max_songs, idx
            )
        else:
            logger.info(
                " [%s] Complete: %d/%d songs added to playlist",
                playlist_name, len(song_ids), max_songs
            )
    
        return song_ids[:max_songs]

    def create_playlist(self, name: str, recommendations: List[Dict],
                       max_songs: int = 100) -> None:
        """Create a playlist from recommendations."""
        logger.info("Creating playlist: %s", name)

        if self.dry_run:
            logger.info("[DRY RUN] Would process %d recommendations", len(recommendations))
            return

        song_ids = self._process_recommendations(name, recommendations, max_songs)

        if song_ids and self.nd.create_playlist(name, song_ids):
            self.stats["playlists_created"] += 1

    def _generate_hybrid_daily_mix(
        self,
        mix_number: int,
        genre_focus: str,
        characteristics: str,
        top_artists: List[str],
        top_genres: List[str],
        favorited_songs: List[Dict],
        low_rated_songs: Optional[List[Dict]] = None,
        playlist_name: str = None
    ) -> List[Dict]:
        """
        Generate a daily mix using both AudioMuse-AI and LLM
        
        Args:
            mix_number: Mix number (1-6)
            genre_focus: Main genre focus
            characteristics: Additional characteristics
            top_artists: Top artists from library
            top_genres: Top genres from library
            favorited_songs: Favorited songs for LLM context
            low_rated_songs: Low rated songs to avoid
        
        Returns:
            List of song dicts: [{"artist": "...", "title": "..."}]
        """
        songs = []
        label = f"Daily Mix {mix_number}" if mix_number in [1,2,3,4,5,6] else playlist_name
        
        # Get configuration
        audiomuse_songs_count = self.config["audiomuse"]["songs_per_mix"]
        llm_songs_count = self.config["audiomuse"]["llm_songs_per_mix"]
        
        # Get songs from AudioMuse-AI if enabled
        audiomuse_actual_count = 0
        if self.audiomuse_client:
            logger.debug(f"Requesting {audiomuse_songs_count} songs from AudioMuse-AI for {label}")
            # --- Begin multi-version prompt logic ---
            modifiers = characteristics.split() if characteristics else []
            prompt_variants = []
            if characteristics and genre_focus:
                prompt_variants.append(f"{characteristics} {genre_focus} music")  # all modifiers
            if modifiers:
                prompt_variants.append(f"{modifiers[0]} {genre_focus} music")     # first modifier
            if genre_focus:
                prompt_variants.append(f"{genre_focus} music")                    # genre only
                prompt_variants.append(f"{genre_focus}")                          # genre only, no "music"
            logger.debug(f"AudioMuse prompt attempts: {prompt_variants}")
            audiomuse_collected: List[Dict] = []
            audiomuse_seen: Set[Tuple[str, str]] = set()
            for prompt in prompt_variants:
                remaining = audiomuse_songs_count - len(audiomuse_collected)
                if remaining <= 0:
                    break
                logger.debug(f"AudioMuse request: '{prompt}' (need {remaining} more)")
                batch = self.audiomuse_client.generate_playlist(
                    user_request=prompt,
                    num_songs=remaining
                ) or []
                logger.info(f"AudioMuse prompt '{prompt}' yielded {len(batch)} songs")
                for s in batch:
                    a = (s.get("artist") or "").strip()
                    t = (s.get("title") or "").strip()
                    k = (a.lower(), t.lower())
                    if a and t and k not in audiomuse_seen:
                        audiomuse_seen.add(k)
                        audiomuse_collected.append({"artist": a, "title": t})
                if len(audiomuse_collected) >= audiomuse_songs_count:
                    break
            songs.extend(audiomuse_collected)
            audiomuse_actual_count = len(audiomuse_collected)
            logger.info(f"📻 {label}: Got {audiomuse_actual_count} songs from AudioMuse-AI")
            if audiomuse_actual_count < audiomuse_songs_count:
                logger.debug(f"AudioMuse returned fewer songs than requested ({audiomuse_actual_count}/{audiomuse_songs_count})")
        
        # Get additional songs from LLM
        # If AudioMuse returned fewer songs, request more from LLM to reach target
        num_llm_songs = llm_songs_count if self.audiomuse_client else 30
        if self.audiomuse_client and audiomuse_actual_count < audiomuse_songs_count:
                # Request extra LLM songs to compensate, plus a buffer for version
                # mismatches and download failures
                shortfall = audiomuse_songs_count - audiomuse_actual_count
                buffer = max(15, int((shortfall + llm_songs_count) * 0.5))
                num_llm_songs = llm_songs_count + shortfall + buffer
                logger.info(f"🔄 AudioMuse returned {audiomuse_actual_count}/{audiomuse_songs_count} songs, "
                            f"requesting {num_llm_songs} from LLM (includes {buffer} song buffer)")
        
        logger.debug(f"Requesting {num_llm_songs} songs from LLM for {label}")
        # We'll use the AI engine to generate just the LLM portion
        llm_songs = self._generate_llm_songs_for_daily_mix(
            mix_number=mix_number,
            genre_focus=genre_focus,
            characteristics=characteristics,
            num_songs=num_llm_songs,
            top_artists=top_artists,
            top_genres=top_genres,
            favorited_songs=favorited_songs,
            low_rated_songs=low_rated_songs
        )
        
        songs.extend(llm_songs)
        random.shuffle(songs)
        
        logger.info(f"🤖 {label}: Got {len(llm_songs)} songs from LLM")
        logger.info(f"🎵 {label}: Total {len(songs)} songs (AudioMuse: {audiomuse_actual_count}, LLM: {len(llm_songs)})")
        
        # Return the full pool so _process_recommendations can iterate past cross-playlist
        # duplicates and still find enough unique songs to fill max_songs.
        # DO NOT slice here — slicing to 30 caused later playlists to get 0 songs because
        # all 30 candidates had already been marked as processed by earlier playlists.
        return songs

    def _generate_llm_songs_for_daily_mix(
        self,
        mix_number: int,
        genre_focus: str,
        characteristics: str,
        num_songs: int,
        top_artists: List[str],
        top_genres: List[str],
        favorited_songs: List[Dict],
        low_rated_songs: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Generate LLM songs for a specific daily mix
        
        Returns:
            List of song dicts: [{"artist": "...", "title": "..."}]
        """
        # Build a focused prompt for this specific daily mix
        artist_list = ", ".join(random.sample(top_artists[:20], min(10, len(top_artists[:20]))))
        genre_list = ", ".join(random.sample(top_genres[:12], min(6, len(top_genres[:12]))))
        
        # Randomly sample a 20-song context window — avoids O(n) shuffle of the full library
        k = min(20, len(favorited_songs))
        favorited_sample = [
            f"{s.get('artist','')} - {s.get('title','')}"
            for s in random.sample(favorited_songs, k)
        ]
        favorited_context = "\n".join(favorited_sample)
        
        negative_context = ""
        if low_rated_songs:
            negative_sample = [
                f"{s.get('artist','')} - {s.get('title','')}"
                for s in low_rated_songs[:20]
            ]
            negative_context = f"\n\nSONGS TO AVOID (rated {LOW_RATING_MIN}-{LOW_RATING_MAX} stars):\n" + "\n".join(negative_sample)
        
        prompt = f"""You are a music curator creating a {genre_focus} playlist.

User's music taste:
- Top artists: {artist_list}
- Top genres: {genre_list}

Sample of favorited songs:
{favorited_context}
{negative_context}

Generate {num_songs} {characteristics} {genre_focus} songs. Mix library favorites with new discoveries.

Return ONLY valid JSON array:
[
  {{"artist": "Artist Name", "title": "Song Title"}},
  {{"artist": "Artist Name", "title": "Song Title"}}
]

CRITICAL RULES:
- Both "artist" and "title" required
- Double quotes for ALL strings
- No trailing commas
- NEVER recommend avoided songs
- No markdown, just raw JSON array
- ESCAPE ALL BACKSLASHES: Use \\\\ not \\
"""
        
        try:
            if self.ai.backend == "gemini":
                if not GEMINI_SDK_AVAILABLE:
                    logger.error("Gemini backend required but not available")
                    return []
                
                from google.genai import types
                response = self.ai.genai_client.models.generate_content(
                    model=self.ai.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=1.0,
                        max_output_tokens=4096
                    )
                )
                content = response.text
            else:
                # OpenAI-compatible API
                response = self.ai.client.chat.completions.create(
                    model=self.ai.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=1.0,
                    max_tokens=4096
                )
                content = response.choices[0].message.content
            
            # Clean JSON
            content = re.sub(r'^```(?:json)?\s*', '', content, flags=re.MULTILINE)
            content = re.sub(r'\s*```$', '', content, flags=re.MULTILINE)
            content = content.strip()
            
            # Extract JSON array
            json_start = content.find('[')
            json_end = content.rfind(']')
            if json_start != -1 and json_end != -1:
                content = content[json_start:json_end + 1]
            
            songs = json.loads(content)
            
            if not isinstance(songs, list):
                logger.error("LLM response is not a JSON array")
                return []
            
            # Validate songs
            valid_songs = [
                song for song in songs
                if isinstance(song, dict) and "artist" in song and "title" in song
            ]
            
            return valid_songs[:num_songs]
            
        except Exception as e:
            logger.error(f"Failed to generate LLM songs for Daily Mix {mix_number}: {e}")
            return []


    def run(self) -> None:
        """Run the main discovery engine."""
        start_time = datetime.now()

        write_health_status(BASE_DIR, "starting", "Initializing OctoGen")
        
        logger.info("=" * 70)
        logger.info("OCTOGEN - Starting: %s", start_time.strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("=" * 70)
    
        try:

            write_health_status(BASE_DIR, "running", "Analyzing music library")
            # Analyze library
            logger.info("Analyzing music library...")
            logger.debug("Fetching starred songs from Navidrome")
            favorited_songs = self.nd.get_starred_songs()
    
            if not favorited_songs:
                logger.warning("No starred songs found - library analysis limited")
                logger.debug("Continuing with alternative music sources")
    
            # Check if regular playlists should be generated now (time-gating)
            from octogen.scheduler.timeofday import should_generate_regular_playlists, record_regular_playlist_generation
            
            should_generate_regular, reason = should_generate_regular_playlists(BASE_DIR)
            
            if not should_generate_regular:
                logger.info("=" * 70)
                logger.info("⏭️  SKIPPING REGULAR PLAYLIST GENERATION")
                logger.info("=" * 70)
                logger.info(f"Reason: {reason}")
                logger.info("Regular playlists (Daily Mix, etc.) will be generated at scheduled time")
                logger.info("=" * 70)
                
                # Skip to time-of-day playlist check only
                # Set empty playlists to skip regular generation
                all_playlists = {}
            else:
                logger.info("=" * 70)
                logger.info("✅ PROCEEDING WITH REGULAR PLAYLIST GENERATION")
                logger.info("=" * 70)
                logger.info(f"Reason: {reason}")
                logger.info("=" * 70)
                # Initialize all_playlists for playlist generation
                all_playlists = {}

            # Generate AI playlists (only if AI is configured and should_generate_regular is True)
            if should_generate_regular and self.ai and favorited_songs:
                logger.debug("AI engine is configured, proceeding with AI generation")
                # Continue with normal AI generation
                top_artists = self.nd.get_top_artists(100)
                top_genres = self.nd.get_top_genres(20)
                low_rated_songs = self.nd.get_low_rated_songs()
    
                logger.info("Library: %d favorited songs", len(favorited_songs))
                logger.info("Top artists: %s", ", ".join(top_artists[:5]))
                logger.info("Top genres: %s", ", ".join(top_genres[:5]))
                logger.info("Songs to avoid: %d (rated %d-%d stars)",
                           len(low_rated_songs), LOW_RATING_MIN, LOW_RATING_MAX)
                logger.debug(f"Library analysis complete: {len(top_artists)} artists, {len(top_genres)} genres")
    
                # Generate AI playlists
                logger.info("=" * 70)
                logger.info("AI CALL LIMIT: %d maximum", self.ai.max_calls)
                logger.info("=" * 70)
    
                all_playlists, ai_error = self.ai.generate_all_playlists(
                    top_artists,
                    top_genres,
                    favorited_songs,
                    low_rated_songs
                )
    
                self.stats["ai_calls"] = self.ai.call_count
                logger.debug(f"AI generation complete, made {self.ai.call_count} API calls")
                
                # Track AI service outcome
                if ai_error:
                    self.service_tracker.record(
                        "ai_playlists",
                        success=False,
                        reason=ai_error,
                        api_calls=self.ai.call_count
                    )
                    logger.warning("AI service failed: %s", ai_error)
                else:
                    playlist_count = len(all_playlists)
                    song_count = sum(len(songs) for songs in all_playlists.values())
                    self.service_tracker.record(
                        "ai_playlists",
                        success=True,
                        playlists=playlist_count,
                        songs=song_count,
                        api_calls=self.ai.call_count
                    )
                    logger.info("AI service succeeded: %d playlists, %d songs", playlist_count, song_count)
            elif not self.ai:
                logger.info("=" * 70)
                logger.info("AI not configured - using alternative music sources only")
                logger.info("=" * 70)
                logger.debug("Setting up library data for alternative sources")
                # Set required variables for alternative sources
                top_artists = self.nd.get_top_artists(100) if favorited_songs else []
                top_genres = self.nd.get_top_genres(20) if favorited_songs else []
                low_rated_songs = self.nd.get_low_rated_songs() if favorited_songs else []
            else:
                logger.info("=" * 70)
                logger.info("No starred songs - skipping AI generation")
                logger.info("=" * 70)
                logger.debug("No library data available for analysis")
                top_artists = []
                top_genres = []
                low_rated_songs = []
    
            # Check if we have any music sources available (but only fail if not generating regular playlists)
            if not should_generate_regular:
                # When skipping regular playlists, we only need time-of-day playlists
                # Don't exit, just skip to time-of-day playlist generation
                pass
            elif not all_playlists and not self.audiomuse_client and not self.lastfm and not self.listenbrainz and not self.spotify_importer and not self.deezer_importer:
                logger.error("=" * 70)
                logger.error("❌ No playlists generated and no alternative services configured")
                logger.error("❌ Nothing to process - exiting with error")
                logger.error("=" * 70)
                logger.debug("Available sources check: AI=%s, AudioMuse=%s, Last.fm=%s, ListenBrainz=%s, Spotify=%s, Deezer=%s",
                           bool(all_playlists), bool(self.audiomuse_client), bool(self.lastfm), bool(self.listenbrainz),
                           bool(self.spotify_importer), bool(self.deezer_importer))
                write_health_status(BASE_DIR, "unhealthy", "No music sources available")
                sys.exit(1)
    
            if should_generate_regular and all_playlists:
                # Handle hybrid playlists if AudioMuse is enabled
                if self.audiomuse_client:
                    logger.info("=" * 70)
                    logger.info("GENERATING HYBRID PLAYLISTS (AudioMuse + LLM)")
                    logger.info("=" * 70)
                    
                    playlists_before_audiomuse = self.stats["playlists_created"]
                    
                    # Define all hybrid playlist configurations (everything except Discovery)
                    hybrid_playlist_configs = [
                        # Daily Mixes (num 1-6)
                        {"name": "Daily Mix 1", "genre": top_genres[0] if len(top_genres) > 0 else DEFAULT_DAILY_MIX_GENRES[0], "characteristics": "energetic", "num": 1},
                        {"name": "Daily Mix 2", "genre": top_genres[1] if len(top_genres) > 1 else DEFAULT_DAILY_MIX_GENRES[1], "characteristics": "catchy upbeat", "num": 2},
                        {"name": "Daily Mix 3", "genre": top_genres[2] if len(top_genres) > 2 else DEFAULT_DAILY_MIX_GENRES[2], "characteristics": "danceable rhythmic", "num": 3},
                        {"name": "Daily Mix 4", "genre": top_genres[3] if len(top_genres) > 3 else DEFAULT_DAILY_MIX_GENRES[3], "characteristics": "rhythmic bass-heavy", "num": 4},
                        {"name": "Daily Mix 5", "genre": top_genres[4] if len(top_genres) > 4 else DEFAULT_DAILY_MIX_GENRES[4], "characteristics": "alternative atmospheric", "num": 5},
                        {"name": "Daily Mix 6", "genre": top_genres[5] if len(top_genres) > 5 else DEFAULT_DAILY_MIX_GENRES[5], "characteristics": "smooth melodic", "num": 6},
                        # Mood/Activity playlists (no num)
                        {"name": "Chill Vibes", "genre": "ambient", "characteristics": "relaxing calm peaceful", "num": None},
                        {"name": "Workout Energy", "genre": "high-energy", "characteristics": "upbeat motivating intense", "num": None},
                        {"name": "Focus Flow", "genre": "instrumental", "characteristics": "ambient atmospheric concentration", "num": None},
                        {"name": "Drive Time", "genre": "upbeat", "characteristics": "driving energetic feel-good", "num": None}
                    ]
                    
                    # Generate and create hybrid playlists
                    for mix_config in hybrid_playlist_configs:
                        playlist_name = mix_config["name"]
                        mix_number = mix_config.get("num")
                        hybrid_songs = self._generate_hybrid_daily_mix(
                            mix_number=mix_number,
                            genre_focus=mix_config["genre"],
                            characteristics=mix_config["characteristics"],
                            top_artists=top_artists,
                            top_genres=top_genres,
                            favorited_songs=favorited_songs,
                            low_rated_songs=low_rated_songs,
                            playlist_name=playlist_name
                        )
                        if hybrid_songs:
                            self.create_playlist(playlist_name, hybrid_songs, max_songs=30)
                    
                    # Track AudioMuse service
                    audiomuse_playlists = self.stats["playlists_created"] - playlists_before_audiomuse
                    self.service_tracker.record(
                        "audiomuse",
                        success=True,
                        playlists=audiomuse_playlists
                    )
                    logger.info("AudioMuse-AI service succeeded: %d playlists", audiomuse_playlists)
                    
                    # Create Discovery from AI response (LLM-only for new discoveries)
                    if "Discovery" in all_playlists:
                        discovery_songs = all_playlists["Discovery"]
                        if isinstance(discovery_songs, list) and discovery_songs:
                            logger.info("=" * 70)
                            logger.info("DISCOVERY (LLM-only for new discoveries)")
                            logger.info("=" * 70)
                            self.create_playlist("Discovery", discovery_songs, max_songs=50)
                else:
                    # Original behavior: use all AI-generated playlists
                    for playlist_name, songs in all_playlists.items():
                        if isinstance(songs, list) and songs:
                            self.create_playlist(playlist_name, songs, max_songs=100)

            
            # External services (run regardless of starred songs, but only if should_generate_regular)
            if should_generate_regular and self.lastfm:
                logger.info("=" * 70)
                logger.info("LAST.FM RECOMMENDATIONS")
                logger.info("=" * 70)
                try:
                    playlists_before = self.stats["playlists_created"]
                    recs = self.lastfm.get_recommended_tracks(50)
                    if recs:
                        self.create_playlist("Last.fm Recommended", recs, 50)
                    playlists_created = self.stats["playlists_created"] - playlists_before
                    
                    self.service_tracker.record(
                        "lastfm",
                        success=True,
                        playlists=playlists_created,
                        songs=len(recs) if recs else 0
                    )
                    logger.info("Last.fm service succeeded: %d playlists, %d songs", playlists_created, len(recs) if recs else 0)
                except Exception as e:
                    self.service_tracker.record(
                        "lastfm",
                        success=False,
                        reason=str(e)[:100]
                    )
                    logger.warning("Last.fm service failed: %s", e)
    
            if should_generate_regular and self.listenbrainz:
                logger.info("Creating ListenBrainz 'Created For You' playlists...")
            
                try:
                    playlists_before = self.stats["playlists_created"]
            
                    # --- Cleanup stale LB weekly playlists in Navidrome ---
                    # Delete any Navidrome playlists that were previously imported
                    # from a ListenBrainz generated weekly playlist but are now
                    # older than two weeks (i.e. the week_start date embedded in
                    # the name is more than 14 days in the past).
                    #
                    # Covered formats:
                    #   "LB: Weekly Jams for blueion, week of 2026-04-06 Mon"
                    #   "LB: Exploration for blueion, week of 2026-04-06 Mon"
                    #   etc. – any "LB: <title> for <user>, week of YYYY-MM-DD Ddd"
                    # Legacy static names ("LB: Weekly Exploration",
                    # "LB: Last Week's Exploration") are replaced in-place by
                    # create_playlist() so they need no explicit cleanup here.
                    try:
                        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                        cutoff = today - timedelta(days=14)
                        all_nd_playlists = self.nd.get_all_playlists()
                        cleanup_scanned = 0
                        cleanup_matched = 0
                        cleanup_deleted = 0
                        cleanup_failed = 0
                        for nd_pl in all_nd_playlists:
                            nd_name = nd_pl.get("name", "")
                            if not nd_name.startswith("LB: "):
                                continue
                            cleanup_scanned += 1
                            # Strip the "LB: " prefix and try to parse
                            inner = nd_name[len("LB: "):]
                            parsed = self.listenbrainz.parse_generated_playlist_title(inner)
                            if not parsed:
                                continue
                            try:
                                week_dt = datetime.strptime(parsed["week_start"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                            except ValueError:
                                continue
                            if week_dt <= cutoff:
                                cleanup_matched += 1
                                pl_id = nd_pl.get("id")
                                if pl_id:
                                    logger.info(
                                        "🗑️  Deleting stale LB weekly playlist: %s (id: %s, week of %s)",
                                        nd_name,
                                        pl_id,
                                        parsed["week_start"],
                                    )
                                    if self.nd.delete_playlist(pl_id):
                                        cleanup_deleted += 1
                                    else:
                                        cleanup_failed += 1
                                        logger.warning(
                                            "Failed to delete stale LB weekly playlist: %s (id: %s, week of %s)",
                                            nd_name,
                                            pl_id,
                                            parsed["week_start"],
                                        )
                        logger.info(
                            "LB weekly playlist cleanup: scanned=%d matched=%d deleted=%d failed=%d",
                            cleanup_scanned,
                            cleanup_matched,
                            cleanup_deleted,
                            cleanup_failed,
                        )
                    except Exception as e:
                        logger.warning("Could not clean up stale LB playlists: %s", e)
                    # --- End cleanup ---

                    lb_playlists = self.listenbrainz.get_created_for_you_playlists()
                    for lb_playlist in lb_playlists:
                        # The data is nested inside a "playlist" key
                        playlist_data = lb_playlist.get("playlist", {})
                        playlist_name = playlist_data.get("title", "Unknown")
            
                        # Get the identifier from the nested structure
                        playlist_mbid = None
                        if "identifier" in playlist_data:
                            identifier = playlist_data["identifier"]
                            # identifier might be a string or a list
                            if isinstance(identifier, str):
                                playlist_mbid = identifier.split("/")[-1]
                            elif isinstance(identifier, list) and len(identifier) > 0:
                                playlist_mbid = identifier[0].split("/")[-1]
            
                        if not playlist_mbid:
                            logger.error("Cannot find playlist ID for: %s", playlist_name)
                            continue
            
                        # Determine if this is current week or last week
                        renamed_playlist = None
                        should_process = True
            
                        if "Weekly Exploration" in playlist_name and "week of" in playlist_name:
                            try:
                                # Extract the date string
                                date_part = playlist_name.split("week of ")[1].split()[0]  # Gets "2026-02-09"
                                playlist_date = datetime.strptime(date_part, "%Y-%m-%d")
            
                                # Calculate start of current week (Monday)
                                today = datetime.now()
                                start_of_this_week = today - timedelta(days=today.weekday())
                                start_of_last_week = start_of_this_week - timedelta(days=7)
            
                                # Compare dates (ignoring time)
                                playlist_week_start = playlist_date.replace(hour=0, minute=0, second=0, microsecond=0)
                                this_week_start = start_of_this_week.replace(hour=0, minute=0, second=0, microsecond=0)
                                last_week_start = start_of_last_week.replace(hour=0, minute=0, second=0, microsecond=0)
            
                                if playlist_week_start == this_week_start:
                                    renamed_playlist = "LB: Weekly Exploration"
                                elif playlist_week_start == last_week_start:
                                    renamed_playlist = "LB: Last Week's Exploration"
                                else:
                                    # Older than 2 weeks - skip
                                    logger.info(
                                        "Skipping old Weekly Exploration: %s (keeping only last 2 weeks)",
                                        playlist_name
                                    )
                                    should_process = False
            
                            except Exception:
                                logger.warning("Could not parse date from playlist: %s", playlist_name)
                                renamed_playlist = f"LB: {playlist_name}"
            
                        else:
                            # Non-weekly playlists (Daily Jams, etc.)
                            renamed_playlist = f"LB: {playlist_name}"
            
                        if not should_process:
                            continue
            
                        logger.info("Processing: %s -> %s (MBID: %s)", playlist_name, renamed_playlist, playlist_mbid)
            
                        tracks = self.listenbrainz.get_playlist_tracks(playlist_mbid)
            
                        # Process songs with download support (limit to 50)
                        found_ids: List[str] = []
                        for track in tracks[:50]:
                            song_id = self._process_single_recommendation(track)
                            if song_id:
                                found_ids.append(song_id)
            
                        if found_ids:
                            if self.nd.create_playlist(renamed_playlist, found_ids):
                                self.stats["playlists_created"] += 1  
            
                    playlists_created = self.stats["playlists_created"] - playlists_before
                    self.service_tracker.record(
                        "listenbrainz",
                        success=True,
                        playlists=playlists_created
                    )
                    logger.info("ListenBrainz service succeeded: %d playlists", playlists_created)
            
                except Exception as e:
                    self.service_tracker.record(
                        "listenbrainz",
                        success=False,
                        reason=str(e)[:100]
                    )
                    logger.warning("ListenBrainz service failed: %s", e)

    
            # --- SPOTIFY IMPORT ---
            if should_generate_regular and self.spotify_importer:
                logger.info("=" * 70)
                logger.info("SPOTIFY PLAYLIST IMPORT")
                logger.info("=" * 70)
                try:
                    playlists_before = self.stats["playlists_created"]
                    playlist_urls = [
                        u.strip()
                        for u in self.config["spotify"]["playlist_urls"].split(",")
                        if u.strip()
                    ]
                    for playlist_url in playlist_urls:
                        tracks = self.spotify_importer.get_playlist_tracks(playlist_url, max_tracks=100)
                        if tracks:
                            playlist_id = self.spotify_importer.extract_playlist_id(playlist_url)
                            playlist_name = f"Spotify: {playlist_id}"
                            self.create_playlist(playlist_name, tracks, max_songs=100)
                    playlists_created = self.stats["playlists_created"] - playlists_before
                    self.service_tracker.record("spotify_import", success=True, playlists=playlists_created)
                    logger.info("Spotify import succeeded: %d playlists", playlists_created)
                except Exception as e:
                    self.service_tracker.record("spotify_import", success=False, reason=str(e)[:100])
                    logger.warning("Spotify import failed: %s", e)

            # --- DEEZER IMPORT ---
            if should_generate_regular and self.deezer_importer:
                logger.info("=" * 70)
                logger.info("DEEZER PLAYLIST IMPORT")
                logger.info("=" * 70)
                try:
                    playlists_before = self.stats["playlists_created"]
                    playlist_urls = [
                        u.strip()
                        for u in self.config["deezer"]["playlist_urls"].split(",")
                        if u.strip()
                    ]
                    for playlist_url in playlist_urls:
                        tracks = self.deezer_importer.get_playlist_tracks(playlist_url, max_tracks=100)
                        if tracks:
                            playlist_id = self.deezer_importer.extract_playlist_id(playlist_url)
                            playlist_name = f"Deezer: {playlist_id}"
                            self.create_playlist(playlist_name, tracks, max_songs=100)
                    playlists_created = self.stats["playlists_created"] - playlists_before
                    self.service_tracker.record("deezer_import", success=True, playlists=playlists_created)
                    logger.info("Deezer import succeeded: %d playlists", playlists_created)
                except Exception as e:
                    self.service_tracker.record("deezer_import", success=False, reason=str(e)[:100])
                    logger.warning("Deezer import failed: %s", e)

    
            # Record successful regular playlist generation
            if should_generate_regular:
                record_regular_playlist_generation(BASE_DIR)
    
            # Time-Period Playlist Generation 
            try:
                from octogen.scheduler.timeofday import (
                    should_generate_period_playlist_now,
                    get_current_period,
                    get_period_display_name,
                    get_time_context,
                    record_period_playlist_generation,
                    get_period_playlist_size
                )
                
                should_generate, reason = should_generate_period_playlist_now(data_dir=BASE_DIR)
                
                if should_generate:
                    logger.info("=" * 70)
                    logger.info("TIME-OF-DAY PLAYLIST GENERATION")
                    logger.info("=" * 70)
                    
                    current_period = get_current_period()
                    playlist_name = get_period_display_name(current_period)
                    time_context = get_time_context(current_period)
                    playlist_size = get_period_playlist_size()
                    
                    logger.info(f"Period: {time_context.get('description')}")
                    logger.info(f"Mood: {time_context.get('mood')}")
                    logger.info(f"Playlist: {playlist_name}")
                    logger.info(f"Reason: {reason}")
                    
                    # Delete old period playlists first
                    try:
                        all_playlists_in_navidrome = self.nd.get_all_playlists()
                        period_patterns = ["Morning Mix", "Afternoon Flow", "Evening Chill", "Night Vibes"]
                        
                        for nd_playlist in all_playlists_in_navidrome:
                            nd_playlist_name = nd_playlist.get("name", "")
                            # Delete if it's a time-period playlist but not the current one
                            if any(pattern in nd_playlist_name for pattern in period_patterns) and nd_playlist_name != playlist_name:
                                playlist_id = nd_playlist.get("id")
                                if playlist_id:
                                    logger.info(f"🗑️  Deleting old period playlist: {nd_playlist_name}")
                                    self.nd.delete_playlist(playlist_id)
                    except Exception as e:
                        logger.warning(f"Could not delete old period playlists: {e}")
                    
                    # Generate the time-period playlist
                    # Use AudioMuse for 25 songs, LLM for 5 songs
                    period_songs = []
                    
                    # Get 25 songs from AudioMuse if enabled
                    if self.audiomuse_client:
                        logger.info("🎵 Generating 25 songs via AudioMuse-AI...")
                        try:
                            if favorited_songs:
                                # Use random seed from favorited songs
                                seed_song = random.choice(favorited_songs)
                                # Build a natural language request for AudioMuse
                                mood = time_context.get("mood", "")
                                request_text = f"{mood} music similar to {seed_song.get('title', '')} by {seed_song.get('artist', '')}"
                                audiomuse_songs = self.audiomuse_client.generate_playlist(
                                    user_request=request_text,
                                    num_songs=25
                                )
                                
                                if audiomuse_songs:
                                    period_songs.extend(audiomuse_songs[:25])
                                    logger.info(f"✓ Got {len(audiomuse_songs[:25])} songs from AudioMuse")
                        except Exception as e:
                            logger.warning(f"AudioMuse generation failed: {e}")
                    
                    # Get 5 songs from LLM
                    if self.ai and favorited_songs:
                        logger.info("🤖 Generating 5 songs via LLM...")
                        try:
                            # Build a special prompt for time-period playlist
                            llm_prompt = f"""Generate exactly 5 new song recommendations for a {playlist_name}.

Time context: {time_context.get('description')}
Mood: {time_context.get('mood')}
Energy level: {time_context.get('energy')}

{time_context.get('guidance')}

Return ONLY valid JSON:
{{
  "songs": [
    {{"artist": "Artist Name", "title": "Song Title"}},
    {{"artist": "Artist Name", "title": "Song Title"}}
  ]
}}

CRITICAL RULES:
- Exactly 5 songs
- Both "artist" and "title" required
- Double quotes for ALL strings
- No trailing commas
- No markdown, just raw JSON
"""
                            
                            # Use simplified AI call for just 5 songs
                            if self.ai.backend == "gemini" and hasattr(self.ai, 'genai_client'):
                                from google.genai import types
                                response = self.ai.genai_client.models.generate_content(
                                    model=self.ai.model,
                                    contents=llm_prompt,
                                    config=types.GenerateContentConfig(
                                        temperature=0.9,
                                        max_output_tokens=1000,
                                        response_mime_type="application/json"
                                    )
                                )
                                llm_response = response.text
                            else:
                                # OpenAI-compatible
                                response = self.ai.client.chat.completions.create(
                                    model=self.ai.model,
                                    messages=[{"role": "user", "content": llm_prompt}],
                                    temperature=0.9,
                                    max_tokens=1000,
                                    response_format={"type": "json_object"}
                                )
                                llm_response = response.choices[0].message.content
                            
                            # Parse response
                            llm_data = json.loads(llm_response)
                            llm_songs = llm_data.get("songs", [])
                            
                            if llm_songs:
                                period_songs.extend(llm_songs[:5])
                                logger.info(f"✓ Got {len(llm_songs[:5])} songs from LLM")
                        except Exception as e:
                            logger.warning(f"LLM generation failed: {e}")
                    
                    # Create the playlist if we have songs
                    if period_songs:
                        logger.info(f"Creating {playlist_name} with {len(period_songs)} songs...")
                        self.create_playlist(playlist_name, period_songs, max_songs=playlist_size)
                        
                        # Record generation
                        record_period_playlist_generation(current_period, playlist_name, BASE_DIR)
                        
                        # Track in service summary
                        self.service_tracker.record(
                            "timeofday_playlist",
                            success=True,
                            playlists=1,
                            songs=len(period_songs),
                            period=current_period
                        )
                        logger.info(f"✅ Time-of-day playlist created: {playlist_name}")
                    else:
                        logger.warning("No songs generated for time-period playlist")
                        self.service_tracker.record(
                            "timeofday_playlist",
                            success=False,
                            reason="No songs generated"
                        )
                else:
                    logger.info(f"⏭️  Skipping time-period playlist: {reason}")
                    
            except Exception as e:
                logger.warning(f"Time-period playlist generation failed: {e}")
                if hasattr(self, 'service_tracker'):
                    self.service_tracker.record(
                        "timeofday_playlist",
                        success=False,
                        reason=str(e)[:100]
                    )
    
            # Service Execution Summary
            logger.info("=" * 70)
            logger.info("SERVICE EXECUTION SUMMARY")
            logger.info("=" * 70)
            
            for service_name, service_data in self.service_tracker.services.items():
                if service_data.get("success"):
                    playlists = service_data.get("playlists", 0)
                    songs = service_data.get("songs", 0)
                    api_calls = service_data.get("api_calls", "")
                    
                    service_display = {
                        "ai_playlists": "AI Playlists",
                        "audiomuse": "AudioMuse-AI",
                        "lastfm": "Last.fm",
                        "listenbrainz": "ListenBrainz",
                        "spotify_import": "Spotify Import",
                        "deezer_import": "Deezer Import",
                        "timeofday_playlist": "Time-of-Day Playlist"
                    }.get(service_name, service_name)
                    
                    if api_calls:
                        logger.info("✅ %s: %d playlists created (%d API calls)", service_display, playlists, api_calls)
                    elif songs:
                        logger.info("✅ %s: %d playlists created (%d songs)", service_display, playlists, songs)
                    else:
                        logger.info("✅ %s: %d playlists created", service_display, playlists)
                else:
                    reason = service_data.get("reason", "unknown")
                    service_display = {
                        "ai_playlists": "AI Playlists",
                        "audiomuse": "AudioMuse-AI",
                        "lastfm": "Last.fm",
                        "listenbrainz": "ListenBrainz",
                        "spotify_import": "Spotify Import",
                        "deezer_import": "Deezer Import",
                        "timeofday_playlist": "Time-of-Day Playlist"
                    }.get(service_name, service_name)
                    
                    logger.warning("❌ %s: FAILED (reason: %s)", service_display, reason)
            
            logger.info("=" * 70)
            
            # Summary
            elapsed = datetime.now() - start_time
            logger.info("=" * 70)
            logger.info("COMPLETED")
            write_health_status(BASE_DIR, "healthy", f"Last run completed successfully at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 70)
            logger.info("Total time: %dm %ds", elapsed.seconds // 60, elapsed.seconds % 60)
            if self.ai:
                logger.info("AI API calls: %d / %d", self.stats["ai_calls"], self.ai.max_calls)
            else:
                logger.info("AI: Not configured")
            logger.info("Playlists created: %d", self.stats["playlists_created"])
            logger.info("Songs in library: %d", self.stats["songs_found"])
            logger.info("Songs downloaded: %d", self.stats["songs_downloaded"])
            logger.info("Near-duplicates avoided: %d", self.stats["duplicates_prevented"])
            logger.info("Songs skipped (low rating): %d", self.stats["songs_skipped_low_rating"])
            logger.info("Songs skipped (duplicate): %d", self.stats["songs_skipped_duplicate"])
            logger.info("Songs failed: %d", self.stats["songs_failed"])
            logger.info("=" * 70)
            
            # Record successful run
            self._record_successful_run()
    
        except Exception as e:
            write_health_status(BASE_DIR, "unhealthy", f"Error: {str(e)[:200]}")
            logger.error("Fatal error: %s", e, exc_info=True)
            sys.exit(1)


# ============================================================================
# SCHEDULING SUPPORT
# ============================================================================

def run_with_schedule(dry_run: bool = False):
    """Run engine with optional cron scheduling."""
    schedule_cron = os.getenv("SCHEDULE_CRON", "").strip()

    # Check if scheduling is disabled
    if not schedule_cron or schedule_cron.lower() in ("manual", "false", "no", "off", "disabled"):
        logger.info("🔧 Running in manual mode (no schedule)")
        engine = OctoGenEngine(dry_run=dry_run)
        
        # Check cooldown before running in manual mode
        if not engine._check_run_cooldown():
            write_health_status(BASE_DIR, "skipped", "Cooldown active - skipping run")
            logger.info("💤 Sleeping %ds before exit to prevent rapid restarts", COOLDOWN_EXIT_DELAY_SECONDS)
            time.sleep(COOLDOWN_EXIT_DELAY_SECONDS)
            sys.exit(0)  # Clean exit - not an error
        
        engine.run()
        return

    # Validate croniter is available
    if not CRONITER_AVAILABLE:
        logger.error("❌ SCHEDULE_CRON is set but croniter is not installed")
        logger.error("Run: pip install croniter")
        logger.error("Or unset SCHEDULE_CRON for manual mode")
        sys.exit(1)

    # Scheduled mode
    print("")  # Blank line after banner
    logger.info("═" * 70)
    logger.info("🕐 OCTOGEN SCHEDULER")
    logger.info("═" * 70)
    logger.info("Schedule: %s", schedule_cron)
    logger.info("Timezone: %s", os.getenv("TZ", "UTC (default)"))
    logger.info("═" * 70)

    run_count = 0

    while True:
        try:
            # Calculate next run time
            next_run = calculate_next_run(schedule_cron)
            logger.info("📅 Next scheduled run: %s", next_run.strftime("%Y-%m-%d %H:%M:%S"))
            write_health_status(BASE_DIR, "scheduled", f"Waiting for next run at {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

            # Wait until next run
            wait_until(next_run)

            # Execute
            run_count += 1
            logger.info("═" * 70)
            logger.info("🚀 SCHEDULED RUN #%d - %s", run_count, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            logger.info("═" * 70)

            engine = OctoGenEngine(dry_run=dry_run)
            
            # Check cooldown before running in scheduled mode
            if not engine._check_run_cooldown():
                logger.info("⏭️ Cooldown active, waiting for next scheduled run")
                write_health_status(BASE_DIR, "scheduled", "Cooldown active - waiting for next schedule")
                continue  # Continue to scheduler loop, don't exit
            
            engine.run()

            logger.info("✅ Scheduled run #%d completed successfully", run_count)

        except KeyboardInterrupt:
            logger.info("⚠️  Scheduler interrupted by user")
            break
        except Exception as e:
            logger.error("❌ Scheduled run failed: %s", e, exc_info=True)
            # Continue scheduling despite errors
            logger.info("🔄 Will retry on next scheduled run")
            time.sleep(60)  # Wait 1 minute before recalculating


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main() -> None:
    """Main entry point."""

    from octogen.utils.logging_config import setup_logging
    log_level = os.getenv("LOG_LEVEL", "INFO")
    setup_logging(log_level=log_level)

    
    # Initialize metrics if available and enabled
    try:
        metrics_enabled = os.getenv("METRICS_ENABLED", "true").lower() == "true"
        metrics_port = int(os.getenv("METRICS_PORT", "9090"))
        if metrics_enabled:
            setup_metrics(enabled=True, port=metrics_port)
            logger.info(f"Prometheus metrics enabled on port {metrics_port}")
    except Exception as e:
        logger.warning(f"Failed to initialize metrics: {e}")
    
    # Start web UI if enabled
    web_enabled = os.getenv("WEB_ENABLED", "true").lower() not in ("false", "no", "off", "disabled")
    if web_enabled:
        try:
            from octogen.web.app import start_web_server
            
            web_port = int(os.getenv("WEB_PORT", "5000"))
            
            # Start web server in background thread
            web_thread = start_web_server(port=web_port, data_dir=BASE_DIR, threaded=True)
            
            if web_thread:
                logger.info(f"🌐 Web UI started on port {web_port}")
                logger.info(f"🌐 Access dashboard at http://localhost:{web_port}")
            
        except Exception as e:
            logger.warning(f"Failed to start web UI: {e}")
            logger.warning("Continuing without web UI...")

    print_banner()

    parser = argparse.ArgumentParser(
        description="OctoGen - AI-Powered Music Discovery for Navidrome",
        epilog="Configure via environment variables - see ENV_VARS.md"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without making downloads or playlist changes"
    )

    args = parser.parse_args()

    lock = acquire_lock(LOCK_FILE)

    try:
        run_with_schedule(dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error("Startup failed: %s", e, exc_info=True)
        sys.exit(1)
