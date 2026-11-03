import json
from datetime import UTC, datetime

import pytest

from election_forecast.lineage import fingerprint
from scripts import export_site_data as exporter
from scripts.freeze_final_forecast import require_fresh_observations


def test_closing_forecast_rejects_old_cached_or_future_observations():
    start = datetime(2026, 11, 3, 6, 43, tzinfo=UTC)
    end = datetime(2026, 11, 3, 7, tzinfo=UTC)
    require_fresh_observations(["2026-11-03T06:50:00+00:00"], start, end)
    for values in [
        [],
        ["2026-10-27T20:00:00+00:00"],
        ["2026-11-03T08:00:00+00:00"],
        ["2026-11-03T06:50:00"],
    ]:
        with pytest.raises(ValueError):
            require_fresh_observations(values, start, end)


def test_final_badge_cannot_decorate_modified_forecast_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(exporter, "ARTIFACTS", tmp_path)
    monkeypatch.setattr(exporter, "PROCESSED", tmp_path)
    (tmp_path / "polls.parquet").write_bytes(b"locked input")
    output = tmp_path / "prediction.csv"
    output.write_bytes(b"locked forecast")
    forecast = {"as_of": "2026-11-03", "engine_sha256": {"model": "version"}}
    release = {
        **forecast,
        "input_table_sha256": {"polls": fingerprint(tmp_path / "polls.parquet")},
        "forecast_output_sha256": {"prediction.csv": fingerprint(output)},
    }
    (tmp_path / "final_release.json").write_text(json.dumps(release))
    assert exporter._final_release_snapshot(forecast) == release
    output.write_bytes(b"later revision")
    with pytest.raises(ValueError, match="changed after sealing"):
        exporter._final_release_snapshot(forecast)
