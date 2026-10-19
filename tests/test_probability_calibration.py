import numpy as np
import pandas as pd

from election_forecast.probability_calibration import (
    apply_calibration,
    fit_probability_calibrator,
    fit_validated_probability_calibrator,
    walk_forward_calibrate_predictions,
)


def _predictions() -> pd.DataFrame:
    rows = []
    for cycle in (2012, 2014, 2016, 2018):
        for index in range(50):
            probability = 0.8 if index % 2 else 0.2
            # Deliberately less polarized outcomes than the raw probabilities.
            actual_margin = 1.0 if index % 5 in (1, 3, 4) else -1.0
            rows.append(
                {
                    "race_id": f"{cycle}:senate:{index}",
                    "cycle": cycle,
                    "office": "senate",
                    "horizon": 30,
                    "model": "test_model",
                    "actual_margin": actual_margin,
                    "dem_win_probability": probability,
                }
            )
    return pd.DataFrame(rows)


def test_calibrator_compresses_deliberately_overconfident_probabilities():
    data = _predictions().rename(columns={"dem_win_probability": "raw_dem_win_probability"})
    fit = fit_probability_calibrator(data, model="test_model", office="senate")
    calibrated = apply_calibration(np.array([0.2, 0.8]), fit)
    assert fit.slope < 1.0
    assert calibrated[0] > 0.2
    assert calibrated[1] < 0.8


def test_walk_forward_calibration_never_uses_current_cycle():
    output = walk_forward_calibrate_predictions(_predictions())
    first = output[output["cycle"] == 2012]
    assert (first["dem_win_probability"] == first["raw_dem_win_probability"]).all()
    assert (first["probability_calibration_scope"] == "identity_insufficient_history").all()


def test_temporal_gate_rejects_calibration_without_later_cycle_gain():
    data = _predictions().rename(columns={"dem_win_probability": "raw_dem_win_probability"})
    # Make the two latest cycles already perfectly calibrated; a transform learned
    # from the earlier overconfident cycles must therefore be rejected.
    latest = data["cycle"].isin([2016, 2018])
    data.loc[latest & (data["actual_margin"] > 0), "raw_dem_win_probability"] = 0.99
    data.loc[latest & (data["actual_margin"] < 0), "raw_dem_win_probability"] = 0.01
    fit = fit_validated_probability_calibrator(data, model="test_model", office="senate")
    assert fit.scope == "identity_no_calibration_gain"
