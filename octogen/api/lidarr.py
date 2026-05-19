"""Lidarr bridge — pushes missing-track artists to Lidarr.

Used by OctoGen when the Lidarr bridge is enabled. Failures during mid-run
add operations are caught at the call site and never block playlist generation.
"""

import logging
from typing import Optional, Tuple

import requests
from requests.exceptions import RequestException


logger = logging.getLogger(__name__)


class LidarrClient:
    """Client for Lidarr's REST API (artist add + lookup)."""

    def __init__(
        self,
        url: str,
        api_key: str,
        quality_profile: str,
        metadata_profile: str,
        tag: str,
        monitored: bool,
        dry_run: bool = False,
    ):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.quality_profile_name = quality_profile
        self.metadata_profile_name = metadata_profile
        self.tag = tag
        self.monitored = monitored
        self.dry_run = dry_run

        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key})

        self.quality_profile_id: Optional[int] = None
        self.metadata_profile_id: Optional[int] = None
        self.root_folder_path: Optional[str] = None
        self.tag_id: Optional[int] = None

    # -- validation ---------------------------------------------------------

    def validate(self) -> None:
        """Resolve profile names → IDs, pick a root folder, ensure tag exists.

        Raises RuntimeError on any failure.
        """
        try:
            self.quality_profile_id = self._resolve_profile(
                "qualityprofile", self.quality_profile_name, "LIDARR_QUALITY_PROFILE"
            )
            self.metadata_profile_id = self._resolve_profile(
                "metadataprofile", self.metadata_profile_name, "LIDARR_METADATA_PROFILE"
            )
            self.root_folder_path = self._pick_root_folder()
            if self.tag:
                self.tag_id = self._ensure_tag(self.tag)
        except RequestException as e:
            raise RuntimeError(f"Lidarr unreachable at {self.url}: {e}") from e
        except (KeyError, ValueError, IndexError) as e:
            raise RuntimeError(
                f"Lidarr returned unexpected response shape: {type(e).__name__}: {e}"
            ) from e

    def _resolve_profile(self, kind: str, name: str, env_name: str) -> int:
        resp = self.session.get(f"{self.url}/api/v1/{kind}", timeout=10)
        resp.raise_for_status()
        profiles = resp.json()
        for p in profiles:
            if p.get("name") == name:
                return p["id"]
        available = ", ".join(p.get("name", "?") for p in profiles)
        raise RuntimeError(
            f"{env_name}={name!r} not found in Lidarr. Available: [{available}]"
        )

    def _pick_root_folder(self) -> str:
        resp = self.session.get(f"{self.url}/api/v1/rootfolder", timeout=10)
        resp.raise_for_status()
        folders = resp.json()
        if not folders:
            raise RuntimeError(
                "Lidarr has no root folder configured — add one in Lidarr settings"
            )
        path = folders[0]["path"]
        if len(folders) > 1:
            logger.info(
                "Lidarr: %d root folders configured, using %s", len(folders), path,
            )
        return path

    def _ensure_tag(self, label: str) -> int:
        resp = self.session.get(f"{self.url}/api/v1/tag", timeout=10)
        resp.raise_for_status()
        for t in resp.json():
            if t.get("label") == label:
                return t["id"]
        resp = self.session.post(
            f"{self.url}/api/v1/tag", json={"label": label}, timeout=10
        )
        resp.raise_for_status()
        return resp.json()["id"]

    # -- add artist ---------------------------------------------------------

    def add_artist(self, artist_name: str) -> Tuple[bool, str]:
        """Look up artist in MusicBrainz via Lidarr, then add it.

        Returns (success, message). Never raises — call sites treat this as
        a side effect of playlist generation.
        """
        missing = [
            name for name, value in (
                ("quality_profile_id", self.quality_profile_id),
                ("metadata_profile_id", self.metadata_profile_id),
                ("root_folder_path", self.root_folder_path),
            )
            if value is None
        ]
        if missing:
            return False, f"validate() not called or incomplete: missing {', '.join(missing)}"

        if self.dry_run:
            logger.info(
                "Lidarr (dry-run): would add %s (monitored=%s, tag=%s)",
                artist_name, self.monitored, self.tag,
            )
            return True, "dry-run"

        try:
            resp = self.session.get(
                f"{self.url}/api/v1/artist/lookup",
                params={"term": artist_name},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json()
            if not results:
                logger.warning("Lidarr: artist %r not found in MusicBrainz", artist_name)
                return False, f"not found: {artist_name}"
            match = results[0]

            payload = {
                "foreignArtistId": match["foreignArtistId"],
                "artistName": match.get("artistName", artist_name),
                "qualityProfileId": self.quality_profile_id,
                "metadataProfileId": self.metadata_profile_id,
                "rootFolderPath": self.root_folder_path,
                "monitored": self.monitored,
                "tags": [self.tag_id] if self.tag_id else [],
                "addOptions": {
                    "monitor": "all" if self.monitored else "none",
                    "searchForMissingAlbums": False,
                },
            }
            resp = self.session.post(
                f"{self.url}/api/v1/artist", json=payload, timeout=15
            )
            if resp.status_code == 409:
                logger.info("Lidarr: %s already exists", artist_name)
                return True, "already exists"
            if not resp.ok:
                logger.warning(
                    "Lidarr add %s failed (%d): %s",
                    artist_name, resp.status_code, resp.text[:200],
                )
                return False, f"HTTP {resp.status_code}"
            logger.info("Lidarr: added %s", artist_name)
            return True, "added"

        except (RequestException, ValueError, KeyError) as e:
            logger.warning(
                "Lidarr add %s error: %s", artist_name, e, exc_info=True,
            )
            return False, str(e)
