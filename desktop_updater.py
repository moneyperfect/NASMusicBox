from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from app_meta import GITHUB_LATEST_RELEASE_API, GITHUB_RELEASES_URL


@dataclass(slots=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int = 0
    content_type: str = ""


@dataclass(slots=True)
class ReleaseInfo:
    tag_name: str
    version: str
    title: str
    html_url: str
    published_at: str
    body: str
    installer_asset: ReleaseAsset | None = None
    portable_asset: ReleaseAsset | None = None

    @property
    def preferred_asset(self) -> ReleaseAsset | None:
        return self.installer_asset or self.portable_asset


def _version_key(value: str) -> tuple[int, ...]:
    normalized = (value or "").strip().lower().lstrip("v")
    parts = re.findall(r"\d+", normalized)
    if not parts:
        return (0,)
    return tuple(int(part) for part in parts)


def is_newer_version(candidate: str, current: str) -> bool:
    return _version_key(candidate) > _version_key(current)


def _release_headers() -> dict[str, str]:
    token = os.environ.get("NAS_UPDATE_TOKEN") or os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "NASMusicBox-Updater"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _asset_priority(asset_name: str) -> tuple[int, int]:
    name = (asset_name or "").lower()
    suffix = Path(name).suffix
    if suffix == ".exe":
        return (0 if "setup" in name or "installer" in name else 1, 0)
    if suffix == ".msi":
        return (2, 0)
    if suffix == ".zip":
        return (3 if "portable" in name else 4, 0)
    return (9, 0)


def _select_assets(payload: dict[str, Any]) -> tuple[ReleaseAsset | None, ReleaseAsset | None]:
    installer: ReleaseAsset | None = None
    portable: ReleaseAsset | None = None

    assets = sorted(payload.get("assets") or [], key=lambda asset: _asset_priority(asset.get("name", "")))
    for raw_asset in assets:
        name = raw_asset.get("name") or ""
        download_url = raw_asset.get("browser_download_url") or ""
        if not name or not download_url:
            continue

        asset = ReleaseAsset(
            name=name,
            download_url=download_url,
            size=int(raw_asset.get("size") or 0),
            content_type=raw_asset.get("content_type") or "",
        )
        suffix = Path(name).suffix.lower()

        if suffix in {".exe", ".msi"} and installer is None:
            installer = asset
            continue
        if suffix == ".zip" and portable is None:
            portable = asset

    return installer, portable


def parse_release(payload: dict[str, Any]) -> ReleaseInfo | None:
    tag_name = (payload.get("tag_name") or "").strip()
    if not tag_name:
        return None

    installer_asset, portable_asset = _select_assets(payload)
    return ReleaseInfo(
        tag_name=tag_name,
        version=tag_name.lstrip("v"),
        title=(payload.get("name") or tag_name).strip(),
        html_url=(payload.get("html_url") or GITHUB_RELEASES_URL).strip(),
        published_at=(payload.get("published_at") or "").strip(),
        body=(payload.get("body") or "").strip(),
        installer_asset=installer_asset,
        portable_asset=portable_asset,
    )


def fetch_latest_release(timeout: int = 8) -> ReleaseInfo | None:
    response = requests.get(GITHUB_LATEST_RELEASE_API, headers=_release_headers(), timeout=timeout)
    response.raise_for_status()
    return parse_release(response.json())


def download_release_asset(asset: ReleaseAsset, destination_dir: Path, timeout: int = 30) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    target_path = destination_dir / asset.name

    with requests.get(asset.download_url, headers=_release_headers(), stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(target_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=128 * 1024):
                if chunk:
                    handle.write(chunk)

    return target_path
