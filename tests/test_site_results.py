import json
from pathlib import Path

from scripts.export_site_results import OUTPUT, build_payload

ROOT = Path(__file__).resolve().parents[1]


def test_committed_results_payload_matches_export():
    committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(build_payload(), ensure_ascii=False))


def test_results_payload_keeps_frozen_forecast_and_labels_projections():
    payload = build_payload()
    forecast = json.loads((ROOT / "site/lib/forecast-data.json").read_text(encoding="utf-8"))
    chambers = {chamber["office"]: chamber for chamber in payload["chambers"]}

    assert payload["frozen_at"] == forecast["final_release"]["frozen_at"]
    assert chambers["House"]["forecast"]["p95"] == forecast["control"]["house"]["p95_dem_seats"]
    assert (
        chambers["Senate"]["forecast"]["median"]
        == forecast["control"]["senate"]["median_dem_seats"]
    )
    assert chambers["Senate"]["result"]["within_90"] == "inside"
    assert chambers["House"]["result"]["within_90"] == "above"
    assert payload["status_counts"].get("certified", 0) == 0
    assert "not certified" in payload["scope"]
    # Every listed miss is a scored race whose forecast favorite lost.
    for race in payload["misses"]:
        assert race["winner"]
        assert race["forecast_dem_probability"] < 0.5
