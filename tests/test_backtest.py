import numpy as np
import pandas as pd
import pytest

from election_forecast import backtest as module
from election_forecast.backtest import _candidate_evidence_ml_blend
from election_forecast.features import MODEL_FEATURES


def test_candidate_evidence_blend_retires_ml_only_for_deep_new_matchups():
    rows = pd.DataFrame(
        {
            "pollster_count": [4, 8, 12, 12],
            "candidate_continuity": [0.0, 0.0, 0.0, 1.0],
        }
    )
    ridge = np.zeros(4)
    direct_rule = np.full(4, 4.0)
    result = _candidate_evidence_ml_blend(rows, ridge, direct_rule)
    assert np.allclose(result, [2.0, 3.0, 4.0, 2.0])


@pytest.mark.parametrize(
    "champion,expected",
    [
        ("weighted_poll", set()),
        ("quality_candidate_blend", set()),
        ("ridge", {"ridge"}),
        ("candidate_evidence_ml_blend", {"ridge"}),
        ("ensemble", {"ridge", "hist_gradient_boosting"}),
        ("residual_ensemble", {"ridge_residual", "hist_gradient_boosting_residual"}),
    ],
)
def test_live_inference_fits_only_selected_model_dependencies(monkeypatch, champion, expected):
    calls = []

    class Model:
        def __init__(self, name):
            self.name = name

        def fit(self, x, y):
            calls.append(self.name)
            return self

        def predict(self, x):
            return np.ones(len(x))

    monkeypatch.setattr(
        module,
        "make_models",
        lambda: {name: Model(name) for name in ("ridge", "hist_gradient_boosting")},
    )
    monkeypatch.setattr(
        module,
        "make_residual_models",
        lambda: {
            name: Model(name) for name in ("ridge_residual", "hist_gradient_boosting_residual")
        },
    )
    frame = pd.DataFrame({name: [0.0, 0.0] for name in MODEL_FEATURES})
    for name, values in {
        "race_id": ["A", "B"],
        "cycle": [2026, 2026],
        "office": ["senate", "senate"],
        "location": ["TX", "OH"],
        "as_of_date": ["2026-10-19"] * 2,
        "dem_candidate": ["A", "B"],
        "rep_candidate": ["C", "D"],
        "poll_count": [2, 2],
        "pollster_count": [2, 2],
        "horizon": [14, 14],
        "actual_margin": [1.0, -1.0],
        "weighted_margin": [2.0, -2.0],
        "house_effect_adjusted_margin": [2.0, -2.0],
        "quality_adjusted_margin": [2.0, -2.0],
        "previous_national_margin": [0.0, 0.0],
        "environment_adjusted_prior": [0.0, 0.0],
    }.items():
        frame[name] = values
    result = module.fit_and_predict_latest(frame, frame, champion=champion)
    assert set(calls) == expected
    assert result["dem_win_probability"].between(0, 1).all()
