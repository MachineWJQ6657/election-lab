"""Archive configured public result sources; never infer certification from turnout."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/results_2026_sources.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", nargs="+", help="Fetch only these configured source IDs")
    args = parser.parse_args()
    config = json.loads(args.config.read_text("utf-8"))
    args.output.mkdir(parents=True, exist_ok=False)
    raw = args.output / "raw"
    raw.mkdir()
    sources = []
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for source in config["feeds"]:
            if args.only and source["id"] not in args.only:
                continue
            record = dict(source)
            try:
                response = client.get(source["url"])
                record.update(
                    retrieved_at=datetime.now(UTC).isoformat(),
                    http_status=response.status_code,
                    final_url=str(response.url),
                )
                response.raise_for_status()
                path = raw / (source["id"] + source.get("extension", ".html"))
                path.write_bytes(response.content)
                record.update(
                    path=path.relative_to(args.output).as_posix(),
                    sha256=hashlib.sha256(response.content).hexdigest(),
                )
                print(source["id"], response.status_code, len(response.content))
            except httpx.HTTPError as exc:
                record["error"] = str(exc)
                record.setdefault("retrieved_at", datetime.now(UTC).isoformat())
                print(source["id"], "FAILED", str(exc))
            sources.append(record)
    (args.output / "sources.json").write_text(
        json.dumps({"schema_version": 1, "sources": sources}, indent=2) + "\n", "utf-8"
    )


if __name__ == "__main__":
    main()
