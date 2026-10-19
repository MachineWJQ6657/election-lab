"""Small, dependency-free election forecasting prototype."""

from .model import ForecastConfig, StateForecast, forecast_states, simulate_election

__all__ = [
    "ForecastConfig",
    "StateForecast",
    "forecast_states",
    "simulate_election",
]
