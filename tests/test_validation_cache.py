import pandas as pd

from election_forecast import validation_cache as module
from election_forecast.backtest import summarize_predictions


def test_validation_cache_separates_identity_ablation_settings():
    history = pd.DataFrame({"value": [1, 2]})
    baseline = module.cache_key(history, None)
    frequency = module.cache_key(history, None, pollster_pooling=("frequency",))
    counts = module.cache_key(history, None, pollster_pooling=("counts",))
    assert len({baseline, frequency, counts}) == 3
    assert module.cache_key(history, None, pollster_pooling=("frequency", "counts")) == (
        module.cache_key(history, None, pollster_pooling=("counts", "frequency", "counts"))
    )


def test_validation_cache_reuses_only_matching_uncorrupted_inputs(tmp_path, monkeypatch):
    calls = []
    history = pd.DataFrame({"value": [1, 2]})

    def build(*args, **kwargs):
        calls.append("build")
        return pd.DataFrame({"value": [1]})

    def backtest(*args):
        return summarize_predictions(
            pd.DataFrame(
                {
                    "model": ["weighted_poll"],
                    "office": ["senate"],
                    "race_id": ["test"],
                    "actual_margin": [2.0],
                    "predicted_margin": [1.0],
                    "dem_win_probability": [0.6],
                }
            )
        )

    monkeypatch.setattr(module, "build_race_snapshots", build)
    monkeypatch.setattr(module, "run_walk_forward_backtest", backtest)
    original, result, hit = module.cached_validation(history, None, cache_dir=tmp_path)
    assert not hit
    cached, loaded, hit = module.cached_validation(history, None, cache_dir=tmp_path)
    assert hit and len(calls) == 1
    _, _, hit = module.cached_validation(history.set_axis([20, 21]), None, cache_dir=tmp_path)
    assert hit and len(calls) == 1
    pd.testing.assert_frame_equal(original, cached)
    pd.testing.assert_frame_equal(result.predictions, loaded.predictions)
    predicted_file = next(tmp_path.glob("*/predictions.parquet"))
    predicted_file.write_bytes(b"corrupt")
    _, _, hit = module.cached_validation(history, None, cache_dir=tmp_path)
    assert not hit and len(calls) == 2
    _, _, hit = module.cached_validation(pd.DataFrame({"value": [1, 3]}), None, cache_dir=tmp_path)
    assert not hit and len(calls) == 3
