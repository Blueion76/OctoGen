"""Pydantic models for configuration validation"""

import logging
import re
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator


logger = logging.getLogger(__name__)


class NavidromeConfig(BaseModel):
    """Navidrome server configuration"""
    url: str = Field(..., description="Navidrome server URL")
    username: str = Field(..., description="Username")
    password: str = Field(..., description="Password")
    
    @field_validator('url')
    @classmethod
    def validate_url(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        return v.rstrip('/')
    
    @field_validator('username', 'password')
    @classmethod
    def validate_not_empty(cls, v):
        if not v or v.strip() == '':
            raise ValueError('Field cannot be empty')
        return v


class OctoFiestaConfig(BaseModel):
    """Octo-Fiesta server configuration"""
    enabled: bool = Field(True, description="Enable Octo-Fiesta downloads")
    url: Optional[str] = Field(default=None, description="Octo-Fiesta server URL")

    @field_validator('url')
    @classmethod
    def validate_url(cls, v):
        if v is None:
            return v
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        return v.rstrip('/')

    @model_validator(mode='after')
    def url_required_when_enabled(self):
        if self.enabled and not self.url:
            raise ValueError('OCTOFIESTA_URL is required when OCTOFIESTA_ENABLED=true')
        return self


class AIConfig(BaseModel):
    """AI service configuration"""
    api_key: Optional[str] = Field(None, description="API key")
    model: str = Field(..., description="Model name")
    backend: str = Field("gemini", description="AI backend")
    base_url: Optional[str] = None
    request_timeout: int = Field(300, ge=30, description="Request timeout in seconds")
    
    @field_validator('api_key')
    @classmethod
    def validate_api_key(cls, v):
        if v and v in ['your-api-key-here', 'placeholder', 'changeme']:
            raise ValueError('API key appears to be a placeholder')
        return v
    
    @field_validator('backend')
    @classmethod
    def validate_backend(cls, v):
        allowed = ['gemini', 'openai', 'ollama', 'groq', 'mistral']
        if v.lower() not in allowed:
            raise ValueError(f'Backend must be one of: {", ".join(allowed)}')
        return v.lower()


class LastFMConfig(BaseModel):
    """Last.fm configuration"""
    enabled: bool = Field(False, description="Enable Last.fm")
    api_key: Optional[str] = None
    username: Optional[str] = None


class ListenBrainzConfig(BaseModel):
    """ListenBrainz configuration"""
    enabled: bool = Field(False, description="Enable ListenBrainz")
    username: Optional[str] = None
    token: Optional[str] = None


class AudioMuseConfig(BaseModel):
    """AudioMuse configuration"""
    enabled: bool = Field(False, description="Enable AudioMuse")
    url: Optional[str] = None
    ai_provider: str = Field("gemini", description="AI provider")
    ai_model: str = Field("gemini-2.5-flash", description="AI model")
    ai_api_key: Optional[str] = None


class SpotifyConfig(BaseModel):
    """Spotify import configuration"""
    enabled: bool = Field(False, description="Enable Spotify playlist import")
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    playlist_urls: str = Field("", description="Comma-separated playlist URLs")


class DeezerConfig(BaseModel):
    """Deezer import configuration"""
    enabled: bool = Field(False, description="Enable Deezer playlist import")
    playlist_urls: str = Field("", description="Comma-separated playlist URLs")


class PerformanceConfig(BaseModel):
    """Performance configuration"""
    album_batch_size: int = Field(500, ge=1, le=5000)
    max_albums_scan: int = Field(10000, ge=100)
    scan_timeout: int = Field(60, ge=10)
    download_delay_seconds: int = Field(10, ge=0)
    post_scan_delay_seconds: int = Field(3, ge=0)
    download_batch_size: int = Field(5, ge=1, le=50)
    download_concurrency: int = Field(3, ge=1, le=20)


class SchedulingConfig(BaseModel):
    """Scheduling configuration"""
    enabled: bool = Field(False, description="Enable scheduling")
    cron_expression: Optional[str] = None
    
    @field_validator('cron_expression')
    @classmethod
    def validate_cron(cls, v):
        if v:
            # Basic cron validation - should have 5 fields
            parts = v.split()
            if len(parts) != 5:
                raise ValueError('Cron expression must have 5 fields')
        return v


class MonitoringConfig(BaseModel):
    """Monitoring configuration"""
    metrics_enabled: bool = Field(True, description="Enable Prometheus metrics")
    metrics_port: int = Field(9090, ge=1024, le=65535)
    circuit_breaker_threshold: int = Field(5, ge=1)
    circuit_breaker_timeout: int = Field(60, ge=10)


class WebUIConfig(BaseModel):
    """Web UI configuration"""
    enabled: bool = Field(False, description="Enable web UI")
    port: int = Field(5000, ge=1024, le=65535)


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: str = Field("INFO", description="Log level")
    format: str = Field("text", description="Log format (text or json)")
    show_progress: bool = Field(True, description="Show progress indicators")
    
    @field_validator('level')
    @classmethod
    def validate_level(cls, v):
        allowed = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in allowed:
            raise ValueError(f'Log level must be one of: {", ".join(allowed)}')
        return v.upper()
    
    @field_validator('format')
    @classmethod
    def validate_format(cls, v):
        if v.lower() not in ['text', 'json']:
            raise ValueError('Log format must be "text" or "json"')
        return v.lower()


class LidarrConfig(BaseModel):
    """Lidarr bridge configuration"""
    enabled: bool = False
    url: Optional[str] = None
    api_key: Optional[str] = None
    min_missing: int = Field(default=3, ge=1)
    add_monitored: bool = False
    tag: str = "octogen"
    quality_profile: Optional[str] = None
    metadata_profile: Optional[str] = None

    @field_validator('url')
    @classmethod
    def validate_url(cls, v):
        if v is None:
            return v
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        return v.rstrip('/')

    @model_validator(mode='after')
    def required_when_enabled(self):
        if self.enabled:
            missing = [name for name, val in [
                ("LIDARR_URL", self.url),
                ("LIDARR_API_KEY", self.api_key),
                ("LIDARR_QUALITY_PROFILE", self.quality_profile),
                ("LIDARR_METADATA_PROFILE", self.metadata_profile),
            ] if not val]
            if missing:
                raise ValueError(
                    f"Lidarr bridge enabled but missing: {', '.join(missing)}"
                )
        return self


class OctoGenConfig(BaseModel):
    """Main OctoGen configuration"""
    navidrome: NavidromeConfig
    octofiesta: OctoFiestaConfig
    ai: Optional[AIConfig] = None
    lastfm: Optional[LastFMConfig] = None
    lidarr: Optional[LidarrConfig] = None
    listenbrainz: Optional[ListenBrainzConfig] = None
    audiomuse: Optional[AudioMuseConfig] = None
    spotify: Optional[SpotifyConfig] = None
    deezer: Optional[DeezerConfig] = None
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    scheduling: SchedulingConfig = Field(default_factory=SchedulingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    webui: WebUIConfig = Field(default_factory=WebUIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    
    @model_validator(mode='after')
    def validate_config(self):
        """Validate overall configuration"""
        # At least one music source must be configured
        has_ai = self.ai is not None and self.ai.api_key
        has_lastfm = self.lastfm is not None and self.lastfm.enabled
        has_listenbrainz = self.listenbrainz is not None and self.listenbrainz.enabled
        has_audiomuse = self.audiomuse is not None and self.audiomuse.enabled
        has_spotify = self.spotify is not None and self.spotify.enabled
        has_deezer = self.deezer is not None and self.deezer.enabled
        
        if not any([has_ai, has_lastfm, has_listenbrainz, has_audiomuse, has_spotify, has_deezer]):
            logger.warning("No music recommendation source configured (AI, Last.fm, ListenBrainz, AudioMuse, Spotify, or Deezer)")
        
        return self
