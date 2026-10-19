import unittest

from election_forecast.model import (
    ForecastConfig,
    StateForecast,
    aggregate_polls,
    combine_normal_estimates,
    simulate_election,
)


class ModelTests(unittest.TestCase):
    def test_recent_poll_gets_more_weight(self):
        polls = [
            {
                "days_old": "0",
                "sample_size": "600",
                "pollster_rating": "1",
                "dem_share": "51",
                "rep_share": "49",
            },
            {
                "days_old": "42",
                "sample_size": "600",
                "pollster_rating": "1",
                "dem_share": "48",
                "rep_share": "52",
            },
        ]
        mean, sigma, count = aggregate_polls(polls, ForecastConfig())
        self.assertGreater(mean, 0.0)
        self.assertGreater(sigma, 0.0)
        self.assertEqual(count, 2)

    def test_posterior_is_between_estimates(self):
        mean, sigma = combine_normal_estimates(2.0, 4.0, -1.0, 2.0)
        self.assertGreater(mean, -1.0)
        self.assertLess(mean, 2.0)
        self.assertLess(sigma, 2.0)

    def test_simulation_is_reproducible_and_totals_are_valid(self):
        forecasts = [
            StateForecast(
                state="TEST",
                region="test",
                electoral_votes=93,
                prior_mean=0.0,
                prior_sigma=4.0,
                poll_mean=0.0,
                poll_sigma=2.0,
                posterior_mean=0.0,
                posterior_sigma=2.0,
                poll_count=1,
            )
        ]
        first = simulate_election(forecasts, simulations=1000, seed=7)
        second = simulate_election(forecasts, simulations=1000, seed=7)
        self.assertEqual(first, second)
        self.assertAlmostEqual(
            first["dem_win_probability"]
            + first["rep_win_probability"]
            + first["electoral_college_tie_probability"],
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
