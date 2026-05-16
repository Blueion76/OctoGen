"""Service health checking module for OctoGen dashboard"""

import logging
import os
import requests
from typing import Dict, Any, Optional
from pathlib import Path
import json
from datetime import datetime, timezone

from octogen.utils.secrets import load_secret

logger = logging.getLogger(__name__)


def write_health_status(data_dir: Path, status: str, message: str = "") -> None:
    """Write health status for monitoring.
    
    Args:
        data_dir: Data directory where health.json should be written
        status: Status string (e.g., 'healthy', 'running', 'scheduled')
        message: Optional message
    """
    health_file = data_dir / "health.json"
    try:
        with open(health_file, 'w') as f:
            json.dump({
                "status": status,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid()
            }, f, indent=2)
    except Exception as e:
        logger.warning("Could not write health status: %s", str(e))


def check_navidrome() -> Dict[str, Any]:
    """Check Navidrome connection and get library stats.
    
    Returns:
        Dict with status, message, and optional stats
    """
    try:
        url = os.getenv("NAVIDROME_URL")
        user = os.getenv("NAVIDROME_USER")
        password = os.getenv("NAVIDROME_PASSWORD")
        
        if not all([url, user, password]):
            return {
                "status": "error",
                "message": "Missing configuration",
                "healthy": False
            }
        
        # Try to ping the server
        from octogen.utils.auth import subsonic_auth_params
        params = subsonic_auth_params(user, password)
        params["f"] = "json"
        
        response = requests.get(
            f"{url}/rest/ping",
            params=params,
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("subsonic-response", {}).get("status") == "ok":
                # Try to get some stats
                try:
                    stats_response = requests.get(
                        f"{url}/rest/getAlbumList2",
                        params={**params, "type": "random", "size": 1},
                        timeout=5
                    )
                    return {
                        "status": "healthy",
                        "message": "Connected",
                        "healthy": True
                    }
                except:
                    return {
                        "status": "healthy",
                        "message": "Connected",
                        "healthy": True
                    }
            
        return {
            "status": "warning",
            "message": f"HTTP {response.status_code}",
            "healthy": False
        }
        
    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "message": "Connection timeout",
            "healthy": False
        }
    except requests.exceptions.ConnectionError:
        return {
            "status": "error",
            "message": "Connection refused",
            "healthy": False
        }
    except Exception as e:
        logger.error(f"Error checking Navidrome: {e}")
        return {
            "status": "error",
            "message": str(e),
            "healthy": False
        }


def check_octofiesta() -> Dict[str, Any]:
    """Check Octo-Fiesta connection.
    
    Returns:
        Dict with status and message
    """
    try:
        url = os.getenv("OCTOFIESTA_URL")
        
        if not url:
            return {
                "status": "error",
                "message": "Missing configuration",
                "healthy": False
            }
        
        # Try to ping the root endpoint (simple health check)
        response = requests.get(
            f"{url}/",  # Changed from /api/healthz to /
            timeout=5
        )
        
        if response.status_code == 200:
            # OctoFiesta returns {"status": "ok"}
            try:
                data = response.json()
                if data.get("status") == "ok":
                    return {
                        "status": "healthy",
                        "message": "Connected",
                        "healthy": True
                    }
            except:
                pass
            
            # If JSON parsing fails but got 200, still consider healthy
            return {
                "status": "healthy",
                "message": "Connected",
                "healthy": True
            }
        
        return {
            "status": "warning",
            "message": f"HTTP {response.status_code}",
            "healthy": False
        }
        
    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "message": "Connection timeout",
            "healthy": False
        }
    except requests.exceptions.ConnectionError:
        return {
            "status": "error",
            "message": "Connection refused",
            "healthy": False
        }
    except Exception as e:
        logger.error(f"Error checking Octo-Fiesta: {e}")
        return {
            "status": "error",
            "message": str(e),
            "healthy": False
        }

def check_ai() -> Dict[str, Any]:
    """Check AI backend status.
    
    Returns:
        Dict with status, backend, model, and message
    """
    try:
        backend = os.getenv("AI_BACKEND", "gemini").lower()
        model = os.getenv("AI_MODEL", "gemini-2.5-flash")
        api_key = os.getenv("AI_API_KEY")
        
        if not api_key:
            return {
                "status": "disabled",
                "message": "No API key configured",
                "backend": backend,
                "model": model,
                "healthy": False
            }
        
        # Check if we can verify the connection
        # For now, just check configuration
        return {
            "status": "configured",
            "message": f"{backend} - {model}",
            "backend": backend,
            "model": model,
            "healthy": True
        }
        
    except Exception as e:
        logger.error(f"Error checking AI: {e}")
        return {
            "status": "error",
            "message": str(e),
            "backend": "unknown",
            "model": "unknown",
            "healthy": False
        }


def check_audiomuse() -> Dict[str, Any]:
    """Check AudioMuse-AI service.
    
    Returns:
        Dict with status and message
    """
    try:
        enabled = os.getenv("AUDIOMUSE_ENABLED", "false").lower() in ("true", "yes", "1", "on")
        
        if not enabled:
            return {
                "status": "disabled",
                "message": "Not enabled",
                "healthy": False
            }
        
        url = os.getenv("AUDIOMUSE_URL")
        if not url:
            return {
                "status": "error",
                "message": "Missing configuration",
                "healthy": False
            }
        
        api_token = load_secret("AUDIOMUSE_API_TOKEN", "")
        headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}

        # Try to check health using /api/config endpoint
        response = requests.get(
            f"{url}/api/config",  # Changed from /health to /api/config
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            return {
                "status": "healthy",
                "message": "Connected",
                "healthy": True
            }
        
        return {
            "status": "warning",
            "message": f"HTTP {response.status_code}",
            "healthy": False
        }
        
    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "message": "Connection timeout",
            "healthy": False
        }
    except requests.exceptions.ConnectionError:
        return {
            "status": "error",
            "message": "Connection refused",
            "healthy": False
        }
    except Exception as e:
        logger.error(f"Error checking AudioMuse: {e}")
        return {
            "status": "error",
            "message": str(e),
            "healthy": False
        }


def check_lastfm() -> Dict[str, Any]:
    """Check Last.fm service status.
    
    Returns:
        Dict with status and message
    """
    try:
        enabled = os.getenv("LASTFM_ENABLED", "false").lower() in ("true", "yes", "1", "on")
        
        if not enabled:
            return {
                "status": "disabled",
                "message": "Not enabled",
                "healthy": False
            }
        
        api_key = os.getenv("LASTFM_API_KEY")
        username = os.getenv("LASTFM_USERNAME")
        
        if not all([api_key, username]):
            return {
                "status": "error",
                "message": "Missing configuration",
                "healthy": False
            }
        
        # Last.fm is configured
        return {
            "status": "configured",
            "message": f"User: {username}",
            "healthy": True
        }
        
    except Exception as e:
        logger.error(f"Error checking Last.fm: {e}")
        return {
            "status": "error",
            "message": str(e),
            "healthy": False
        }


def check_listenbrainz() -> Dict[str, Any]:
    """Check ListenBrainz service status.
    
    Returns:
        Dict with status and message
    """
    try:
        enabled = os.getenv("LISTENBRAINZ_ENABLED", "false").lower() in ("true", "yes", "1", "on")
        
        if not enabled:
            return {
                "status": "disabled",
                "message": "Not enabled",
                "healthy": False
            }
        
        token = os.getenv("LISTENBRAINZ_TOKEN")
        username = os.getenv("LISTENBRAINZ_USERNAME")
        
        if not all([token, username]):
            return {
                "status": "error",
                "message": "Missing configuration",
                "healthy": False
            }
        
        # ListenBrainz is configured
        return {
            "status": "configured",
            "message": f"User: {username}",
            "healthy": True
        }
        
    except Exception as e:
        logger.error(f"Error checking ListenBrainz: {e}")
        return {
            "status": "error",
            "message": str(e),
            "healthy": False
        }


def get_all_services() -> Dict[str, Dict[str, Any]]:
    """Get status of all services.
    
    Returns:
        Dict mapping service names to their status info
    """
    return {
        "navidrome": check_navidrome(),
        "octofiesta": check_octofiesta(),
        "ai": check_ai(),
        "audiomuse": check_audiomuse(),
        "lastfm": check_lastfm(),
        "listenbrainz": check_listenbrainz()
    }


def get_system_stats(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Get system statistics.
    
    Args:
        data_dir: Data directory path
        
    Returns:
        Dict with system statistics
    """
    if data_dir is None:
        data_dir = Path(os.getenv("OCTOGEN_DATA_DIR", Path.cwd()))
    
    stats = {
        "cache_size": 0,
        "songs_rated": 0,
        "low_rated_count": 0,
        "last_run": None,
        "next_run": None,
        "playlists_created": 0
    }
    
    try:
        # Check cache database
        cache_db = data_dir / "octogen_cache.db"
        if cache_db.exists():
            import sqlite3
            conn = sqlite3.connect(str(cache_db))
            cursor = conn.cursor()
            
            # Count total ratings
            cursor.execute("SELECT COUNT(*) FROM ratings")
            stats["songs_rated"] = cursor.fetchone()[0]
            
            # Count low-rated songs (1-2 stars)
            cursor.execute("SELECT COUNT(*) FROM ratings WHERE rating BETWEEN 1 AND 2")
            stats["low_rated_count"] = cursor.fetchone()[0]
            
            conn.close()
            
            # Get file size
            stats["cache_size"] = cache_db.stat().st_size
        
        # Check last run info
        last_run_file = data_dir / "octogen_last_run.json"
        if last_run_file.exists():
            with open(last_run_file, 'r') as f:
                data = json.load(f)
                stats["last_run"] = data.get("last_run_timestamp")
                stats["next_run"] = data.get("next_scheduled_run")
                
                # Count successful playlists
                services = data.get("services", {})
                for service_name, service_data in services.items():
                    if service_data.get("success"):
                        playlists = service_data.get("playlists", 0)
                        stats["playlists_created"] += playlists
        
    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
    
    return stats
