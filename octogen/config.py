"""Configuration management for OctoGen"""

import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from octogen.utils.secrets import load_secret
from octogen.models.config_models import (
    OctoGenConfig, NavidromeConfig, OctoFiestaConfig, AIConfig,
    LastFMConfig, ListenBrainzConfig, AudioMuseConfig,
    PerformanceConfig, SchedulingConfig, MonitoringConfig,
    WebUIConfig, LoggingConfig
)


logger = logging.getLogger(__name__)


def load_config_from_env() -> Dict:
    """Load configuration from environment variables.
    
    Returns:
        Configuration dictionary compatible with original octogen.py format
    """
    logger.info("Loading configuration from environment variables...")

    # Check required variables
    required_vars = [
        "NAVIDROME_URL",
        "NAVIDROME_USER",
        "NAVIDROME_PASSWORD",
        "OCTOFIESTA_URL"
    ]

    missing = [var for var in required_vars if not load_secret(var)]
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
            "url": load_secret("NAVIDROME_URL"),
            "username": load_secret("NAVIDROME_USER"),
            "password": load_secret("NAVIDROME_PASSWORD"),
        },
        "octofiesta": {
            "url": load_secret("OCTOFIESTA_URL"),
        },
        "ai": {
            "api_key": load_secret("AI_API_KEY"),
            "model": os.getenv("AI_MODEL", "gemini-2.5-flash"),
            "backend": os.getenv("AI_BACKEND", "gemini"),
            "base_url": os.getenv("AI_BASE_URL"),
            "max_context_songs": int(os.getenv("AI_MAX_CONTEXT_SONGS", "500")),
            "max_output_tokens": int(os.getenv("AI_MAX_OUTPUT_TOKENS", "65535")),
        },
        "lastfm": {
            "enabled": os.getenv("LASTFM_ENABLED", "false").lower() == "true",
            "api_key": load_secret("LASTFM_API_KEY"),
            "username": os.getenv("LASTFM_USERNAME"),
        },
        "listenbrainz": {
            "enabled": os.getenv("LISTENBRAINZ_ENABLED", "false").lower() == "true",
            "username": os.getenv("LISTENBRAINZ_USERNAME"),
            "token": load_secret("LISTENBRAINZ_TOKEN"),
        },
        "audiomuse": {
            "enabled": os.getenv("AUDIOMUSE_ENABLED", "false").lower() == "true",
            "url": os.getenv("AUDIOMUSE_URL"),
            "ai_provider": os.getenv("AUDIOMUSE_AI_PROVIDER", "gemini"),
            "ai_model": os.getenv("AUDIOMUSE_AI_MODEL", "gemini-2.5-flash"),
            "ai_api_key": load_secret("AUDIOMUSE_AI_API_KEY"),
        },
        "spotify": {
            "enabled": os.getenv("SPOTIFY_IMPORT_ENABLED", "false").lower() == "true",
            "client_id": load_secret("SPOTIFY_CLIENT_ID"),
            "client_secret": load_secret("SPOTIFY_CLIENT_SECRET"),
            "playlist_urls": os.getenv("SPOTIFY_PLAYLIST_URLS", ""),
        },
        "deezer": {
            "enabled": os.getenv("DEEZER_IMPORT_ENABLED", "false").lower() == "true",
            "playlist_urls": os.getenv("DEEZER_PLAYLIST_URLS", ""),
        },
        "performance": {
            "album_batch_size": int(os.getenv("ALBUM_BATCH_SIZE", "500")),
            "max_albums_scan": int(os.getenv("MAX_ALBUMS_SCAN", "10000")),
            "scan_timeout": int(os.getenv("SCAN_TIMEOUT", "60")),
            "download_delay_seconds": int(os.getenv("DOWNLOAD_DELAY_SECONDS", "10")),
            "post_scan_delay_seconds": int(os.getenv("POST_SCAN_DELAY_SECONDS", "30")),
            "download_batch_size": int(os.getenv("DOWNLOAD_BATCH_SIZE", "5")),
            "download_concurrency": int(os.getenv("DOWNLOAD_CONCURRENCY", "3")),
        },
        "scheduling": {
            "enabled": os.getenv("SCHEDULE_ENABLED", "false").lower() == "true",
            "cron_expression": os.getenv("SCHEDULE_CRON"),
        },
        "monitoring": {
            "metrics_enabled": os.getenv("METRICS_ENABLED", "true").lower() == "true",
            "metrics_port": int(os.getenv("METRICS_PORT", "9090")),
            "circuit_breaker_threshold": int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5")),
            "circuit_breaker_timeout": int(os.getenv("CIRCUIT_BREAKER_TIMEOUT", "60")),
        },
        "webui": {
            "enabled": os.getenv("WEB_UI_ENABLED", "false").lower() == "true",
            "port": int(os.getenv("WEB_UI_PORT", "5000")),
        },
        "logging": {
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "format": os.getenv("LOG_FORMAT", "text"),
            "show_progress": os.getenv("SHOW_PROGRESS", "true").lower() == "true",
        },
    }

    return config


def validate_config(config: Dict) -> Optional[OctoGenConfig]:
    """Validate configuration using Pydantic models.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Validated OctoGenConfig or None if validation fails
    """
    try:
        # Build Pydantic models
        validated_config = OctoGenConfig(
            navidrome=NavidromeConfig(**config["navidrome"]),
            octofiesta=OctoFiestaConfig(**config["octofiesta"]),
            ai=AIConfig(**config["ai"]) if config["ai"]["api_key"] else None,
            lastfm=LastFMConfig(**config["lastfm"]) if config["lastfm"]["enabled"] else None,
            listenbrainz=ListenBrainzConfig(**config["listenbrainz"]) if config["listenbrainz"]["enabled"] else None,
            audiomuse=AudioMuseConfig(**config["audiomuse"]) if config["audiomuse"]["enabled"] else None,
            performance=PerformanceConfig(**config["performance"]),
            scheduling=SchedulingConfig(**config["scheduling"]),
            monitoring=MonitoringConfig(**config["monitoring"]),
            webui=WebUIConfig(**config["webui"]),
            logging=LoggingConfig(**config["logging"]),
        )
        
        logger.info("✓ Configuration validation passed")
        return validated_config
        
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        return None


def get_data_dir() -> Path:
    """Get data directory path.
    
    Returns:
        Path to data directory
    """
    data_dir = Path(os.getenv("OCTOGEN_DATA_DIR", Path.cwd()))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
