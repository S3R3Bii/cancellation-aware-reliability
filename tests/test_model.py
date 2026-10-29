import sys
from pathlib import Path
import unittest
from fractions import Fraction as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from model import resolve, convert, metrics, standardize


class CountFixtures(unittest.TestCase):
    def setUp(self):
        self.row = dict(N=100, D=20, C=5, V=5)

    def test_hand_completed_rate(self):
        self.assertEqual(metrics(self.row)["completed_ontime"], F(7, 9))

    def test_hand_scheduled_rate(self):
        self.assertEqual(metrics(self.row)["scheduled_ontime"], F(7, 10))

    def test_hand_difference(self):
        self.assertEqual(metrics(self.row)["denominator_inflation"], F(7, 90))

    def test_half_conversion(self):
        changed, moved = convert(self.row, F(1, 2))
        self.assertEqual(moved, 10)
        self.assertEqual(metrics(changed)["completed_ontime"], F(7, 8))
        self.assertEqual(metrics(changed)["scheduled_ontime"], F(7, 10))

    def test_floor_conversion(self):
        self.assertEqual(convert(dict(N=11, D=7, C=0, V=0), F(1, 4))[1], 1)

    def test_identity_conversion(self):
        self.assertEqual(convert(self.row, F(0)), (self.row, 0))

    def test_structural_bound(self):
        self.assertEqual(
            resolve(dict(N=9, D=None, C=7, V=2)),
            (dict(N=9, D=0, C=7, V=2), "logical_zero_original_null"),
        )

    def test_source_null_not_zero(self):
        self.assertEqual(
            resolve(dict(N=None, D=None, C=None, V=None)),
            (None, "unknown_source_total_or_outcome"),
        )

    def test_unresolved_delay_rejected(self):
        with self.assertRaises(ValueError):
            resolve(dict(N=9, D=None, C=3, V=2))

    def test_partition_rejected(self):
        with self.assertRaises(ValueError):
            metrics(dict(N=10, D=7, C=3, V=1))

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            metrics(dict(N=10, D=-1, C=0, V=0))

    def test_undefined_completed(self):
        got = metrics(dict(N=9, D=0, C=7, V=2))
        self.assertIsNone(got["completed_ontime"])
        self.assertEqual(got["scheduled_disruption"], 1)

    def test_standard_weights(self):
        rows = dict(A=self.row, B=dict(N=1, D=0, C=0, V=0))
        got = standardize(rows, dict(A=F(1, 4), B=F(3, 4)))
        self.assertEqual(got["scheduled_ontime"], F(37, 40))

    def test_undefined_weight_not_dropped(self):
        got = standardize(
            dict(A=self.row, B=dict(N=9, D=0, C=9, V=0)), dict(A=F(1, 2), B=F(1, 2))
        )
        self.assertIsNone(got["completed_ontime"])
        self.assertEqual(got["scheduled_ontime"], F(7, 20))

    def test_outside_fraction(self):
        with self.assertRaises(ValueError):
            convert(self.row, F(3, 2))


if __name__ == "__main__":
    unittest.main()
