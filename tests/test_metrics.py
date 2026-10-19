import unittest

from election_forecast.metrics import brier_score, calibration_bins, mean_absolute_error


class MetricsTests(unittest.TestCase):
    def test_mae(self):
        self.assertAlmostEqual(mean_absolute_error([1.0, -1.0], [0.0, -3.0]), 1.5)

    def test_brier(self):
        self.assertAlmostEqual(brier_score([1, 0], [0.8, 0.1]), 0.025)

    def test_calibration_bins(self):
        bins = calibration_bins([0, 1, 1], [0.1, 0.7, 0.8], bins=2)
        self.assertEqual([item["count"] for item in bins], [1, 2])


if __name__ == "__main__":
    unittest.main()
