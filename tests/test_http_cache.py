import json
from datetime import UTC, datetime

import httpx
import pytest

from election_forecast.http_cache import CachedHTTPClient
from election_forecast.settings import Settings


def test_refresh_preserves_old_response_and_checks_cached_integrity(tmp_path, monkeypatch):
    real_client = httpx.Client
    replies = iter([b"first snapshot", b"second snapshot"])
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=next(replies)))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs)
    )
    client = CachedHTTPClient(
        Settings(data_dir=tmp_path / "data", artifact_dir=tmp_path / "artifacts")
    )
    url = "https://example.org/counts.csv"
    assert client.get(url, refresh=True) == b"first snapshot"
    assert client.get(url, refresh=True) == b"second snapshot"
    archived = sorted(client.settings.raw_dir.glob("http_snapshots/*/*.csv"))
    assert {path.read_bytes() for path in archived} == {b"first snapshot", b"second snapshot"}
    assert client.get_cached(url) == b"second snapshot"
    payload, _ = client._paths(url)
    payload.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="verification"):
        client.get_cached(url)


def test_point_in_time_replay_imports_old_cache_without_backdating(tmp_path):
    client = CachedHTTPClient(
        Settings(data_dir=tmp_path / "data", artifact_dir=tmp_path / "artifacts")
    )
    url = "https://example.org/polls.csv"
    payload, metadata = client._paths(url)
    payload.write_bytes(b"observed data")
    import hashlib

    metadata.write_text(
        json.dumps(
            {
                "url": url,
                "fetched_at": "2026-10-05T12:00:00+00:00",
                "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
            }
        )
    )
    with pytest.raises(FileNotFoundError):
        client.get_as_of(url, datetime(2026, 10, 5, 11, tzinfo=UTC))
    content, provenance = client.get_as_of(url, datetime(2026, 10, 5, 13, tzinfo=UTC))
    assert content == b"observed data"
    assert provenance["fetched_at"] == "2026-10-05T12:00:00+00:00"
    with pytest.raises(ValueError, match="timezone"):
        client.get_as_of(url, datetime(2026, 10, 5))


def test_replay_retains_content_reversions_in_observation_order(tmp_path):
    import hashlib

    client = CachedHTTPClient(
        Settings(data_dir=tmp_path / "data", artifact_dir=tmp_path / "artifacts")
    )
    url = "https://example.org/revised.csv"
    payload, _ = client._paths(url)
    for day, content in [(5, b"A"), (10, b"B"), (15, b"A")]:
        client._archive(
            payload,
            content,
            {
                "url": url,
                "fetched_at": datetime(2026, 10, day, tzinfo=UTC).isoformat(),
                "sha256": hashlib.sha256(content).hexdigest(),
            },
        )
    assert client.get_as_of(url, datetime(2026, 10, 8, tzinfo=UTC))[0] == b"A"
    assert client.get_as_of(url, datetime(2026, 10, 12, tzinfo=UTC))[0] == b"B"
    assert client.get_as_of(url, datetime(2026, 10, 17, tzinfo=UTC))[0] == b"A"
