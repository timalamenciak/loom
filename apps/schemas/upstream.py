"""Client for the causalmosaic GitHub Releases API — the CAMO schema's
upstream release channel (see the causalmosaic AGENTS.md release checklist).

This is an opt-in admin convenience used only by the check_schema_updates and
update_schema management commands. It must never sit on a request-serving
code path: Loom explicitly targets network-restricted deployments, so every
network call here fails soft with UpstreamCheckError rather than raising a
raw connection error.

Uses only the standard library (urllib) — no new dependency for what is,
today, a handful of infrequent admin-triggered HTTP calls.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings

_TIMEOUT_SECONDS = 10
_USER_AGENT = "loom-schema-updater"


class UpstreamCheckError(Exception):
    """The GitHub Releases API could not be reached or returned something
    Loom didn't understand. Callers must catch this and fail soft."""


@dataclass
class ReleaseAsset:
    name: str
    download_url: str


@dataclass
class ReleaseInfo:
    tag_name: str
    published_at: str
    body: str
    assets: list[ReleaseAsset]

    def schema_asset(self) -> ReleaseAsset | None:
        """The .yaml/.yml schema file attached to this release, if any."""
        for asset in self.assets:
            if asset.name.endswith((".yaml", ".yml")):
                return asset
        return None

    @property
    def version(self) -> str:
        return self.tag_name.lstrip("v")


def version_tuple(version: str) -> tuple[int, ...]:
    """Best-effort semver-ish comparison key; non-numeric parts sort last."""
    try:
        return tuple(int(part) for part in version.lstrip("v").split("."))
    except ValueError:
        return (-1,)


def _get_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise UpstreamCheckError(f"Could not reach GitHub ({url}): {exc}") from exc
    except json.JSONDecodeError as exc:
        raise UpstreamCheckError(f"GitHub returned invalid JSON from {url}") from exc


def _release_info(data: dict) -> ReleaseInfo:
    assets = [
        ReleaseAsset(name=asset["name"], download_url=asset["browser_download_url"])
        for asset in data.get("assets", [])
    ]
    return ReleaseInfo(
        tag_name=data["tag_name"],
        published_at=data.get("published_at", ""),
        body=data.get("body", "") or "",
        assets=assets,
    )


def get_latest_release(repo: str | None = None) -> ReleaseInfo:
    """Fetch the latest GitHub Release for the CAMO schema repo."""
    repo = repo or settings.CAMO_SCHEMA_GITHUB_REPO
    data = _get_json(f"https://api.github.com/repos/{repo}/releases/latest")
    return _release_info(data)


def get_release_by_tag(tag: str, repo: str | None = None) -> ReleaseInfo:
    """Fetch a specific tagged GitHub Release (tag may omit the leading 'v')."""
    repo = repo or settings.CAMO_SCHEMA_GITHUB_REPO
    if not tag.startswith("v"):
        tag = f"v{tag}"
    data = _get_json(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
    return _release_info(data)


def download_asset(asset: ReleaseAsset) -> str:
    """Download a release asset's content as text."""
    request = urllib.request.Request(
        asset.download_url, headers={"User-Agent": _USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise UpstreamCheckError(
            f"Could not download release asset {asset.name}: {exc}"
        ) from exc
