"""Lidarr bridge — pushes missing-track artists to Lidarr.

Used by OctoGen when the Lidarr bridge is enabled. Failures during mid-run
add operations are caught at the call site and never block playlist generation.
"""

import logging
from typing import Optional

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

        # Resolved during validate()
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
        return folders[0]["path"]

    def _ensure_tag(self, label: str) -> int:
        resp = self.session.get(f"{self.url}/api/v1/tag", timeout=10)
        resp.raise_for_status()
        for t in resp.json():
            if t.get("label") == label:
                return t["id"]
        # Create it
        resp = self.session.post(
            f"{self.url}/api/v1/tag", json={"label": label}, timeout=10
        )
        resp.raise_for_status()
        return resp.json()["id"]
