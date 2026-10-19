from datetime import date

import pandas as pd
import pytest

from election_forecast.features import build_race_snapshots


def test_identity_ablation_changes_only_the_requested_components():
    rows = []
    for cycle in (2020, 2026):
        for index, (name, margin) in enumerate(
            [("YouGov", 10), ("CBS News/YouGov", 10), ("Example", -10)]
        ):
            rows.append(
                {
                    "source": "test",
                    "source_id": f"{cycle}:{index}",
                    "race_id": f"{cycle}:senate:TX",
                    "cycle": cycle,
                    "office": "senate",
                    "location": "TX",
                    "pollster": name,
                    "election_date": f"{cycle}-11-03",
                    "end_date": f"{cycle}-10-15",
                    "margin": margin,
                    "actual_margin": 0 if cycle == 2020 else float("nan"),
                    "partisan": None,
                    "sample_size": 600,
                    "dem_candidate": "A",
                    "rep_candidate": "B",
                }
            )
    data = pd.DataFrame(rows)
    separate_race = data.cycle.eq(2020) & data.pollster.eq("CBS News/YouGov")
    data.loc[separate_race, "location"] = "NY"
    data.loc[separate_race, "race_id"] = "2020:senate:NY"

    def snapshot(pooling=()):
        return build_race_snapshots(
            data, (14,), target_cycles=(2026,), pollster_pooling=pooling
        ).iloc[0]

    baseline = snapshot()
    count = snapshot(("counts",))
    frequency = snapshot(("frequency",))
    bias = snapshot(("house_effects",))
    assert baseline.pollster_count == 3
    assert baseline.reported_pollster_count == 3
    assert baseline.normalized_pollster_count == 2
    assert count.pollster_count == 2
    assert count.weighted_margin == baseline.weighted_margin
    assert count.house_effect_adjusted_margin == baseline.house_effect_adjusted_margin
    assert frequency.pollster_count == 3
    assert frequency.weighted_margin < baseline.weighted_margin
    assert bias.pollster_count == 3
    assert bias.weighted_margin == baseline.weighted_margin
    assert bias.mean_pollster_house_effect != baseline.mean_pollster_house_effect
    before = snapshot(("frequency", "counts", "house_effects"))
    data.loc[data.cycle.eq(2026), "actual_margin"] = 40
    after = snapshot(("frequency", "counts", "house_effects"))
    assert before.house_effect_adjusted_margin == after.house_effect_adjusted_margin
    assert before.quality_adjusted_margin == after.quality_adjusted_margin
    with pytest.raises(ValueError, match="Unknown pollster pooling"):
        snapshot(("unrecognized",))


def test_quality_weighting_never_learns_from_target_cycle_results():
    rows = []
    for cycle in (2018, 2022, 2024):
        for pollster, margin in (("Emerson College", 2), ("Siena College", 4)):
            rows.append(
                {
                    "source": "test",
                    "source_id": f"{cycle}:{pollster}",
                    "race_id": f"{cycle}:governor:TX",
                    "cycle": cycle,
                    "office": "governor",
                    "location": "TX",
                    "pollster": pollster,
                    "election_date": f"{cycle}-11-05",
                    "end_date": f"{cycle}-10-15",
                    "margin": margin,
                    "actual_margin": 3,
                    "partisan": None,
                    "sample_size": 600,
                    "dem_candidate": "A",
                    "rep_candidate": "B",
                }
            )
    data = pd.DataFrame(rows)
    before = build_race_snapshots(data, horizons=(14,))
    selected = build_race_snapshots(data, horizons=(14,), target_cycles=(2024,))
    pd.testing.assert_frame_equal(
        before[before.cycle.eq(2024)].reset_index(drop=True), selected.reset_index(drop=True)
    )
    data.loc[data.cycle == 2024, "actual_margin"] = -40
    after = build_race_snapshots(data, horizons=(14,))
    assert before.loc[before.cycle == 2024, "quality_adjusted_margin"].tolist() == (
        after.loc[after.cycle == 2024, "quality_adjusted_margin"].tolist()
    )


def test_same_family_successor_does_not_inherit_candidate_continuity():
    old = {
        "source": "test",
        "source_id": "past",
        "race_id": "2020:senate:SC",
        "cycle": 2020,
        "office": "senate",
        "location": "SC",
        "pollster": "Example",
        "election_date": "2020-11-03",
        "end_date": "2020-10-01",
        "sample_size": 800,
        "partisan": None,
        "margin": -9,
        "actual_margin": -10,
        "dem_candidate": "Jaime Harrison",
        "rep_candidate": "Lindsey Graham",
    }
    current = dict(
        old,
        source_id="current",
        race_id="2026:senate:SC",
        cycle=2026,
        election_date="2026-11-03",
        end_date="2026-10-01",
        margin=-3,
        actual_margin=float("nan"),
        dem_candidate="Annie Andrews",
        rep_candidate="Darline Graham",
    )
    result = build_race_snapshots(
        pd.DataFrame([old, current]), (14,), min_polls=1, target_cycles=(2026,)
    ).iloc[0]
    assert result.previous_margin == -10  # The state's prior remains relevant.
    assert result.candidate_continuity == 0  # The named candidate is not the predecessor.


def test_snapshot_excludes_polls_after_as_of_date():
    rows = [
        {
            "source": "test",
            "source_id": "old",
            "race_id": "2024:senate:X",
            "cycle": 2024,
            "office": "senate",
            "location": "X",
            "pollster": "A",
            "end_date": date(2024, 10, 1),
            "election_date": date(2024, 11, 5),
            "sample_size": 600,
            "partisan": None,
            "margin": -2.0,
            "actual_margin": 10.0,
            "dem_candidate": "D",
            "rep_candidate": "R",
        },
        {
            "source": "test",
            "source_id": "future",
            "race_id": "2024:senate:X",
            "cycle": 2024,
            "office": "senate",
            "location": "X",
            "pollster": "B",
            "end_date": date(2024, 11, 1),
            "election_date": date(2024, 11, 5),
            "sample_size": 600,
            "partisan": None,
            "margin": 20.0,
            "actual_margin": 10.0,
            "dem_candidate": "D",
            "rep_candidate": "R",
        },
    ]
    snapshot = build_race_snapshots(pd.DataFrame(rows), horizons=(14,), min_polls=1)
    assert len(snapshot) == 1
    assert snapshot.iloc[0]["weighted_margin"] == -2.0
    assert snapshot.iloc[0]["poll_count"] == 1
    delayed = build_race_snapshots(
        pd.DataFrame(rows), horizons=(34,), min_polls=1, publication_lag_days=3
    )
    assert delayed.empty


def test_verified_release_date_and_redistricting_retire_incompatible_priors():
    base = {
        "source": "test",
        "race_id": "2026:house:TX-09",
        "cycle": 2026,
        "office": "house",
        "location": "TX-09",
        "pollster": "Example",
        "election_date": "2026-11-03",
        "end_date": "2026-10-07",
        "sample_size": 677,
        "partisan": None,
        "margin": -6,
        "actual_margin": float("nan"),
        "dem_candidate": "Leticia Gutierrez",
        "rep_candidate": "Alex Mealer",
        "publication_date": "2026-10-14",
        "district_boundary_changed": True,
        "source_id": "new-district",
    }
    old = dict(
        base,
        source_id="old-district",
        race_id="2024:house:TX-09",
        cycle=2024,
        election_date="2024-11-05",
        end_date="2024-10-01",
        publication_date=None,
        district_boundary_changed=False,
        actual_margin=40,
        margin=38,
    )
    data = pd.DataFrame([old, base])
    before_release = build_race_snapshots(data, (21,), min_polls=1, target_cycles=(2026,))
    assert before_release.empty
    current = build_race_snapshots(data, (14,), min_polls=1, target_cycles=(2026,)).iloc[0]
    assert pd.isna(current.previous_margin)
    assert pd.isna(current.previous_national_margin)
    assert current.candidate_continuity == 0
    assert current.has_previous_margin == 0
    assert current.is_redistricting_cycle == 1
    assert current.weighted_margin == -6


def test_repeated_pollster_is_capped():
    common = {
        "source": "test",
        "race_id": "2024:governor:X",
        "cycle": 2024,
        "office": "governor",
        "location": "X",
        "election_date": date(2024, 11, 5),
        "sample_size": 600,
        "partisan": None,
        "actual_margin": 0.0,
        "dem_candidate": "D",
        "rep_candidate": "R",
    }
    rows = []
    for index in range(4):
        rows.append(
            common
            | {
                "source_id": f"a{index}",
                "pollster": "A",
                "end_date": date(2024, 10, 10 + index),
                "margin": 10.0,
            }
        )
    rows.append(
        common
        | {
            "source_id": "b",
            "pollster": "B",
            "end_date": date(2024, 10, 13),
            "margin": -10.0,
        }
    )
    snapshot = build_race_snapshots(pd.DataFrame(rows), horizons=(14,), min_polls=1)
    assert snapshot.iloc[0]["weighted_margin"] < 7.0


def test_previous_result_is_available_without_leaking_current_outcome():
    common = {
        "source": "test",
        "office": "senate",
        "location": "PA",
        "pollster": "A",
        "sample_size": 600,
        "partisan": None,
        "dem_candidate": "D",
        "rep_candidate": "R",
    }
    rows = [
        common
        | {
            "source_id": "2020",
            "race_id": "2020:senate:PA",
            "cycle": 2020,
            "end_date": date(2020, 10, 1),
            "election_date": date(2020, 11, 3),
            "margin": 2.0,
            "actual_margin": 4.0,
        },
        common
        | {
            "source_id": "2024-other-class",
            "race_id": "2024:senate:PA",
            "cycle": 2024,
            "end_date": date(2024, 10, 1),
            "election_date": date(2024, 11, 5),
            "margin": -7.0,
            "actual_margin": -8.0,
        },
        common
        | {
            "source_id": "2026",
            "race_id": "2026:senate:PA",
            "cycle": 2026,
            "end_date": date(2026, 10, 1),
            "election_date": date(2026, 11, 3),
            "margin": 1.0,
            "actual_margin": None,
        },
    ]
    snapshots = build_race_snapshots(pd.DataFrame(rows), horizons=(14,), min_polls=1)
    current = snapshots[snapshots["cycle"] == 2026].iloc[0]
    assert current["previous_margin"] == 4.0
    assert current["has_previous_margin"] == 1
