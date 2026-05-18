"""AudioMuse-AI client for sonic analysis-based playlist generation"""

import logging
import requests
from typing import List, Dict, Optional


logger = logging.getLogger(__name__)


class AudioMuseClient:
    """Client for interacting with AudioMuse-AI API"""

    def __init__(self, base_url: str, ai_provider: str, ai_model: str,
                 api_key: Optional[str] = None,
                 audiomuse_api_token: Optional[str] = None):
        """Initialize AudioMuse-AI client

        Args:
            base_url: AudioMuse-AI server URL
            ai_provider: AI provider (gemini, openai, ollama, mistral)
            ai_model: AI model name
            api_key: Optional API key for the AI provider (sent in JSON body
                so AudioMuse can call the LLM on our behalf)
            audiomuse_api_token: Optional Bearer token for authenticating to
                AudioMuse-AI itself (required when AudioMuse-AI runs with
                AUTH_ENABLED=true and an API_TOKEN configured). Sent as
                ``Authorization: Bearer <token>`` on every request.
        """
        self.base_url = base_url.rstrip('/')
        self.ai_provider = ai_provider.upper()  # Normalize to uppercase for consistent comparison
        self.ai_model = ai_model
        self.api_key = api_key
        self.audiomuse_api_token = audiomuse_api_token

    def _auth_headers(self) -> Dict[str, str]:
        """Return Authorization header dict if a token is configured."""
        if self.audiomuse_api_token:
            return {"Authorization": f"Bearer {self.audiomuse_api_token}"}
        return {}

    def generate_playlist(self, user_request: str, num_songs: int = 25) -> List[Dict]:
        """Generate playlist using AudioMuse-AI chat API

        Args:
            user_request: Natural language request for playlist
            num_songs: Number of songs to request

        Returns:
            List of song dictionaries with keys: title, artist, item_id
        """
        endpoint = f"{self.base_url}/chat/api/chatPlaylist"

        payload = {
            "userInput": user_request,
            "ai_provider": self.ai_provider,
            "ai_model": self.ai_model,
            "get_songs": num_songs
        }

        # Add API key if provided (case-sensitive comparison with normalized uppercase provider)
        if self.api_key:
            if self.ai_provider == "GEMINI":
                payload["gemini_api_key"] = self.api_key
            elif self.ai_provider == "OPENAI":
                payload["openai_api_key"] = self.api_key
            elif self.ai_provider == "MISTRAL":
                payload["mistral_api_key"] = self.api_key
        payload = {k: v for k, v in payload.items() if v is not None and str(v).lower() != "null"}

        try:
            logger.debug(f"AudioMuse API request: {endpoint}")
            logger.debug(f"Requesting {num_songs} songs with provider {self.ai_provider}")
            response = requests.post(endpoint, json=payload, headers=self._auth_headers(), timeout=60)
            response.raise_for_status()

            data = response.json()
            response_data = data.get('response', data)
            songs = response_data.get('query_results') or []

            logger.info(f"AudioMuse-AI returned {len(songs)} songs for request: '{user_request}'")
            if len(songs) < num_songs:
                logger.debug(f"AudioMuse returned fewer songs than requested ({len(songs)}/{num_songs})")
            return songs

        except requests.exceptions.Timeout as e:
            logger.error(f"AudioMuse-AI API timeout after 60s: {e}")
            return []
        except requests.exceptions.HTTPError as e:
            logger.error(f"AudioMuse-AI HTTP error {e.response.status_code}: {e}")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"AudioMuse-AI API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in AudioMuse-AI request: {e}")
            return []

    def check_health(self) -> bool:
        """Check if AudioMuse-AI server is accessible

        Returns:
            True if server is healthy, False otherwise
        """
        try:
            logger.debug(f"Checking AudioMuse-AI health at {self.base_url}")
            response = requests.get(f"{self.base_url}/api/config", headers=self._auth_headers(), timeout=5)
            is_healthy = response.status_code == 200
            if is_healthy:
                logger.debug("AudioMuse-AI health check passed")
            else:
                logger.debug(f"AudioMuse-AI health check failed with status {response.status_code}")
            return is_healthy
        except requests.exceptions.Timeout:
            logger.debug("AudioMuse-AI health check timeout")
            return False
        except Exception as e:
            logger.debug(f"AudioMuse-AI health check error: {e}")
            return False
