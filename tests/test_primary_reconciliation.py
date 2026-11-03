import hashlib
import json

import httpx
import pandas as pd
import pytest

from election_forecast.sources.merge import merge_current_polls
from election_forecast.sources.primary_reconciliation import reconcile_primary_releases


@pytest.mark.parametrize("unavailable", [False, True])
def test_verified_document_corrects_versions_without_double_counting(tmp_path, unavailable):
    payload = b"reviewed primary report"
    rule = {
        "url": "https://pollster.example/report.pdf",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "location": "TX",
        "start_date": "2026-10-01",
        "end_date": "2026-10-20",
        "sample_size": 601,
        "population": "lv",
        "pollster": "Example",
        "sample_size_basis": "Published sample",
        "offices": {"senate": {"dem_pct": 47.6, "rep_pct": 45.2}},
    }
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"reviewed_as_of": "2026-10-27", "releases": [rule]}))
    rows = pd.DataFrame(
        [
            {
                "source": "a",
                "source_id": "a",
                "source_url": rule["url"] + "?tracking=x",
                "office": "senate",
                "location": "TX",
                "pollster": "Example",
                "end_date": "2026-10-20",
                "sample_size": 969,
                "population": "lv",
                "dem_pct": 48,
                "rep_pct": 45,
                "dem_candidate": "Jane",
                "rep_candidate": "John",
            },
            {
                "source": "b",
                "source_id": "b",
                "source_url": rule["url"],
                "office": "senate",
                "location": "TX",
                "pollster": "Example",
                "end_date": "2026-10-23",
                "sample_size": 601,
                "population": "lv",
                "dem_pct": 48,
                "rep_pct": 45,
                "dem_candidate": "Jane",
                "rep_candidate": "John",
            },
        ]
    )

    class Client:
        def get(self, url):
            if unavailable:
                httpx.Response(403, request=httpx.Request("GET", url)).raise_for_status()
            return payload

        def get_cached(self, url):
            return payload

    corrected, audit = reconcile_primary_releases(rows, client=Client(), rules_path=path)
    assert len(audit[0]["upstream_rows"]) == 2
    assert audit[0]["verification_origin"] == (
        "archived_review_source_unavailable" if unavailable else "current_response"
    )
    assert corrected.sample_size.tolist() == [601, 601]
    assert corrected.end_date.tolist() == ["2026-10-20", "2026-10-20"]
    assert len(merge_current_polls(corrected)) == 1
    assert rows.sample_size.tolist() == [969, 601]  # Input is not overwritten.
    rule["sha256"] = "0" * 64
    path.write_text(json.dumps({"reviewed_as_of": "2026-10-27", "releases": [rule]}))
    with pytest.raises(ValueError, match="document changed"):
        reconcile_primary_releases(rows, client=Client(), rules_path=path)
