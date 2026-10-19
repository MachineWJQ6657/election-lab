import pandas as pd
import pytest

from election_forecast.diagnostics import paired_cycle_bootstrap, probability_diagnostics


def fixture():
    return pd.DataFrame(
        [
            {
                "cycle": cycle,
                "office": "senate",
                "race_id": f"{cycle}:{i}",
                "horizon": 14,
                "actual_margin": 3 if i == 0 else -3,
                "predicted_margin": 2 if i == 0 else -2,
                "dem_win_probability": 0.7 if i == 0 else 0.3,
            }
            for cycle in (2018, 2020, 2022)
            for i in (0, 1)
        ]
    )


def test_diagnostics_and_cluster_comparison_use_same_races():
    frame = fixture()
    score = probability_diagnostics(frame)
    assert score["winner_accuracy"] == 1
    assert score["brier"] == pytest.approx(0.09)
    result = paired_cycle_bootstrap(frame, frame, draws=100)
    assert result["common_races"] == 6
    assert result["independent_cycle_clusters"] == 3
    assert result["exploratory_95pct_cycle_interval"] == [0, 0]
    with_metadata = frame.assign(dem_win_probability_baseline=0.5)
    assert (
        paired_cycle_bootstrap(with_metadata, frame, draws=100)["selected_minus_baseline_brier"]
        == 0
    )
    with pytest.raises(ValueError, match="one prediction"):
        paired_cycle_bootstrap(pd.concat([frame, frame]), frame)
