import pandas as pd

from election_forecast.history import merge_historical_sources
from election_forecast.sources.fte_archive import normalize_generic_archive


def test_history_replaces_only_covered_office_cycles_and_applies_minimum_after_merge():
    ratings = pd.DataFrame(
        [
            {"source": "ratings", "source_id": str(i), "cycle": cycle, "office": office}
            for i, (cycle, office) in enumerate(
                [
                    (2016, "generic_ballot"),
                    (2022, "generic_ballot"),
                    (2024, "senate"),
                    (2024, "governor"),
                ]
            )
        ]
    )
    archive = pd.DataFrame(
        [
            {"source": "archive", "source_id": str(i), "cycle": cycle, "office": office}
            for i, (cycle, office) in enumerate(
                [
                    (2018, "senate"),
                    (2022, "generic_ballot"),
                    (2024, "generic_ballot"),
                    (2024, "senate"),
                ]
            )
        ]
    )
    merged = merge_historical_sources(ratings, archive, min_cycle=2022)
    assert len(merged) == 4
    assert len(merged.loc[merged.office.eq("generic_ballot") & merged.cycle.eq(2022)]) == 1
    assert len(merged.loc[merged.office.eq("generic_ballot") & merged.cycle.eq(2024)]) == 1
    assert merged.loc[merged.office.eq("governor"), "source"].iloc[0] == "ratings"
    assert merged.cycle.min() == 2022


def test_generic_archive_keeps_population_preference_waves_links_and_2024_outcomes():
    base = {
        "poll_id": 1,
        "question_id": 10,
        "cycle": 2024,
        "state": None,
        "stage": "general",
        "end_date": "10/19/24",
        "election_date": "11/5/24",
        "pollster": "Example",
        "population": "rv",
        "sample_size": 1000,
        "dem": 47,
        "rep": 46,
        "url": "https://example.org/topline.pdf",
        "archive_url": "https://web.archive.org/example.csv",
        "created_at": "11/20/24",
        "methodology": "Online",
        "partisan": None,
    }
    raw = pd.DataFrame(
        [
            base,
            dict(base, question_id=11, population="lv", sample_size=800, dem=48),
            dict(base, question_id=12, end_date="10/20/24"),
            dict(base, poll_id=2, question_id=13, state="TX"),
            dict(base, poll_id=3, question_id=14, end_date="11/6/24"),
        ]
    )
    result = normalize_generic_archive(
        raw, pd.DataFrame([{"cycle": 2024, "generic_house_margin": -2.62}])
    )
    assert len(result) == 2
    assert set(result.source_id) == {"generic:11", "generic:12"}
    assert result.actual_margin.tolist() == [-2.62, -2.62]
    assert result.iloc[0].population == "lv"
    assert result.iloc[0].margin == 2
    assert result.iloc[0].source_url == base["url"]
    # Backfill metadata is retained, not misrepresented as observed release time.
    assert result.iloc[0].source_created_at == "11/20/24"
