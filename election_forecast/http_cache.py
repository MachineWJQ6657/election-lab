"""HTTP client with transparent on-disk snapshots and provenance metadata."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .settings import Settings, settings


class CachedHTTPClient:
    def __init__(self, project_settings: Settings = settings) -> None:
        self.settings = project_settings
        self.settings.ensure_directories()
        self.request_log: list[dict] = []

    def _paths(self, url: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        suffix = Path(urlparse(url).path).suffix or ".html"
        payload = self.settings.cache_dir / f"{digest}{suffix}"
        return payload, payload.with_suffix(payload.suffix + ".json")

    def get_cached(self, url: str) -> bytes:
        """Read a verified older snapshot explicitly; never imply it is fresh."""
        payload_path, metadata_path = self._paths(url)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        content = payload_path.read_bytes()
        if (
            metadata.get("url") != url
            or metadata.get("sha256") != hashlib.sha256(content).hexdigest()
        ):
            raise ValueError("Cached snapshot failed provenance verification")
        self._archive(payload_path, content, metadata)
        return content

    def _archive(self, payload_path: Path, content: bytes, metadata: dict) -> None:
        digest = hashlib.sha256(content).hexdigest()
        if metadata.get("sha256") != digest:
            raise ValueError("Cannot archive a corrupted response")
        directory = self.settings.raw_dir / "http_snapshots" / payload_path.stem
        directory.mkdir(parents=True, exist_ok=True)
        archived = directory / f"{digest}{payload_path.suffix}"
        if not archived.exists():
            archived.write_bytes(content)
            archived.with_suffix(archived.suffix + ".json").write_text(
                json.dumps(metadata, indent=2), encoding="utf-8"
            )
        # A -> B -> A must replay A at the third observation, not B. Blobs
        # alone retain content but lose the sequence in which it was observed.
        observed = datetime.fromisoformat(metadata["fetched_at"])
        if observed.tzinfo is None:
            raise ValueError("Observation timestamp must include a timezone")
        observations = directory / "observations"
        observations.mkdir(exist_ok=True)
        stamp = observed.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        record = observations / f"{stamp}_{digest[:16]}.json"
        if not record.exists():
            record.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def get_as_of(self, url: str, cutoff: datetime) -> tuple[bytes, dict]:
        """Replay an observed version with no network fallback or future data."""
        if cutoff.tzinfo is None:
            raise ValueError("As-of cutoff must include a timezone")
        payload_path, metadata_path = self._paths(url)
        if payload_path.exists() and metadata_path.exists():
            self.get_cached(url)  # Import pre-archive cache files using their original timestamp.
        directory = self.settings.raw_dir / "http_snapshots" / payload_path.stem
        candidates = []
        metadata_files = list(directory.glob("*.json"))
        metadata_files.extend((directory / "observations").glob("*.json"))
        for metadata_file in metadata_files:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            observed_at = datetime.fromisoformat(metadata["fetched_at"])
            if metadata.get("url") == url and observed_at <= cutoff:
                candidates.append((observed_at, metadata_file, metadata))
        if not candidates:
            raise FileNotFoundError(
                f"No observed source snapshot on or before {cutoff.isoformat()}"
            )
        _, _, metadata = max(candidates, key=lambda entry: entry[0])
        content = (directory / f"{metadata['sha256']}{payload_path.suffix}").read_bytes()
        if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
            raise ValueError("Archived snapshot failed integrity verification")
        return content, metadata

    def get(self, url: str, *, refresh: bool = False, ttl_hours: int | None = None) -> bytes:
        """Record successful cache/network reads and failures without hiding exceptions."""
        try:
            content, origin, metadata = self._get(url, refresh=refresh, ttl_hours=ttl_hours)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            self.request_log.append(
                {
                    "url": url,
                    "checked_at": datetime.now(UTC).isoformat(),
                    "status": "failed",
                    "error_class": type(exc).__name__,
                    "http_status": (
                        exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                    ),
                }
            )
            raise
        self.request_log.append(
            {
                "url": url,
                "checked_at": datetime.now(UTC).isoformat(),
                "status": origin,
                "observed_at": metadata["fetched_at"],
                "sha256": metadata["sha256"],
                "http_status": metadata.get("status_code"),
            }
        )
        return content

    def _get(
        self, url: str, *, refresh: bool, ttl_hours: int | None
    ) -> tuple[bytes, str, dict]:
        payload_path, metadata_path = self._paths(url)
        ttl = timedelta(hours=ttl_hours if ttl_hours is not None else self.settings.cache_ttl_hours)
        if payload_path.exists() and metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(metadata["fetched_at"])
            cached = self.get_cached(url)
            if not refresh and datetime.now(UTC) - fetched_at <= ttl:
                return cached, "cache", metadata

        with httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(60.0),
            headers={"User-Agent": self.settings.user_agent, "Accept": "*/*"},
        ) as client:
            response = client.get(url)
            response.raise_for_status()
        content = response.content
        now = datetime.now(UTC)
        self._archive(
            payload_path,
            content,
            {
                "url": url,
                "fetched_at": now.isoformat(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "final_url": str(response.url),
            },
        )
        payload_path.write_bytes(content)
        metadata = {
            "url": url,
            "final_url": str(response.url),
            "fetched_at": now.isoformat(),
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "etag": response.headers.get("etag"),
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return content, "network", metadata
