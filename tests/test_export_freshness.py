import json

import pytest

from election_forecast.lineage import fingerprint
from scripts import export_site_data as exporter


def test_export_never_reuses_a_different_horizon_research_headline(tmp_path, monkeypatch):
    monkeypatch.setattr(exporter, "ARTIFACTS", tmp_path)
    directory = tmp_path / "research_audit_latest"
    directory.mkdir()
    report = {"engine_key": "same-model", "target_horizon": 15}
    path = directory / "report.json"
    path.write_text(json.dumps(report))
    assert exporter._matching_research(directory.name, "same-model", horizon=7) is None
    report["target_horizon"] = 7
    path.write_text(json.dumps(report))
    assert exporter._matching_research(directory.name, "same-model", horizon=7) == report
    assert exporter._matching_research(directory.name, "new-model", horizon=7) is None


def test_link_availability_is_bound_to_the_exported_poll_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(exporter, "ARTIFACTS", tmp_path)
    monkeypatch.setattr(exporter, "PROCESSED", tmp_path)
    assert exporter._load_source_link_audit() is None
    polls = tmp_path / "polls_latest.parquet"
    polls.write_bytes(b"snapshot A")
    report = {"dataset_sha256": {"polls_latest": fingerprint(polls)}}
    (tmp_path / "source_link_availability_latest.json").write_text(json.dumps(report))
    assert exporter._load_source_link_audit() == report
    polls.write_bytes(b"snapshot B")
    with pytest.raises(ValueError, match="snapshot mismatch"):
        exporter._load_source_link_audit()
