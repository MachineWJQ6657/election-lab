"""Check a reproducible sample of original poll links without inferring authenticity."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
AGGREGATORS = {
    "pollingsource.com",
    "www.pollingsource.com",
    "www.270towin.com",
    "270towin.com",
    "docs.google.com",
    "drive.google.com",
}


def main() -> None:
    frame = pd.read_parquet(ROOT / "data/processed/polls_latest.parquet")
    frame = frame[
        frame.source_url.fillna("").map(lambda url: urlparse(url).netloc not in AGGREGATORS)
    ]
    # Newest survey in each state/office; fixed sorting makes the sample repeatable.
    sample = frame.sort_values(["end_date", "office", "location"], ascending=[False, True, True])
    sample = sample.drop_duplicates(["office", "location"]).drop_duplicates("source_url").head(24)

    def inspect(row: dict) -> dict:
        url = row["source_url"]
        result = {
            "office": row["office"],
            "location": row["location"],
            "pollster": row["pollster"],
            "end_date": str(row["end_date"]),
            "url": url,
        }
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=25,
                headers={"User-Agent": "elex-forecast/0.3 (public source audit)"},
            ) as client:
                response = client.get(url)
            result.update(
                {
                    "status": response.status_code,
                    "final_url": str(response.url),
                    "content_type": response.headers.get("content-type", ""),
                    "bytes": len(response.content),
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                    "reachable": 200 <= response.status_code < 300,
                }
            )
            if result["reachable"] and "html" in result["content_type"]:
                soup = BeautifulSoup(response.content, "html.parser")
                result["page_title"] = soup.title.get_text(" ", strip=True) if soup.title else ""
        except httpx.HTTPError as exc:
            result.update({"reachable": False, "error": type(exc).__name__})
        return result

    with ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(pool.map(inspect, sample.to_dict("records")))
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "sample_size": len(checks),
        "reachable": sum(row["reachable"] for row in checks),
        "checks": checks,
        "scope": "Network availability and response fingerprint only. A reachable page "
        "does not verify interviews, methodology or transcription. A failed request "
        "may reflect blocking or a changed URL, not fabricated polling.",
    }
    path = ROOT / "artifacts/source_link_availability_20261019.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Original-source availability: {report['reachable']}/{len(checks)} reachable -> {path}")


if __name__ == "__main__":
    main()
