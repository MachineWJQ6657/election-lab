import numpy as np
import pandas as pd
import pytest

from election_forecast.simulation import _simulate_wins, simulate_2026_control


@pytest.mark.parametrize(
    "national,office", [(-0.1, 0.1), (0.1, -0.1), (np.nan, 0.1), (0, np.inf), (0.5, 0.5)]
)
def test_invalid_correlations_are_rejected_before_generating_false_losses(national, office):
    with pytest.raises(ValueError, match="correlation"):
        simulate_2026_control(
            pd.DataFrame(),
            pd.DataFrame(),
            simulations=10,
            national_correlation=national,
            office_correlation=office,
        )


@pytest.mark.parametrize("simulations", [0, -1, True, 3.5])
def test_invalid_draw_counts_are_rejected(simulations):
    with pytest.raises(ValueError, match="positive integer"):
        simulate_2026_control(pd.DataFrame(), pd.DataFrame(), simulations=simulations)


def test_copula_preserves_marginals_including_certain_events():
    probabilities = [0.0, 0.1, 0.5, 0.9, 1.0]
    frame = pd.DataFrame(
        {
            "office": [f"race{i}" for i in range(5)],
            "dem_win_probability": probabilities,
        }
    )
    result = _simulate_wins(
        frame, simulations=100000, seed=10, national_correlation=0.18, office_correlation=0.12
    )
    for i, probability in enumerate(probabilities):
        assert result[f"race{i}"].mean() == pytest.approx(probability, abs=0.005)
    assert not result["race0"].any()
    assert result["race4"].all()


@pytest.mark.parametrize("probability", [np.nan, -0.1, 1.1, np.inf])
def test_invalid_probabilities_do_not_silently_become_losses(probability):
    frame = pd.DataFrame({"office": ["senate"], "dem_win_probability": [probability]})
    with pytest.raises(ValueError, match="Race probabilities"):
        _simulate_wins(
            frame, simulations=10, seed=1, national_correlation=0.18, office_correlation=0.12
        )
