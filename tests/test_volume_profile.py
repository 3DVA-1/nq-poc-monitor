"""Mathematical parity checks against a separate port of the supplied Pine."""
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from volume_profile import Bar, crossing, profile


def original_pine_profile(bars, rows=24, percent=70):
    """Keep original separate green/red arrays and overlap/volume operations."""
    low = min(b.low for b in bars)
    high = max(b.high for b in bars)
    step = (high - low) / rows
    if not step:
        return None
    levels = [low + step * n for n in range(rows + 1)]
    volumes = [0.0] * (rows * 2)

    def get_vol(y11, y12, y21, y22, height, volume):
        if not height:
            return 0.0  # Pine nz() makes a zero-height term zero.
        intersection = max(min(max(y11, y12), max(y21, y22))
                           - max(min(y11, y12), min(y21, y22)), 0)
        return intersection * volume / height

    for candle in reversed(bars):
        top, bottom = max(candle.open, candle.close), min(candle.open, candle.close)
        green = candle.close >= candle.open
        topwick, bottomwick, body = candle.high - top, bottom - candle.low, top - bottom
        divisor = 2 * topwick + 2 * bottomwick + body
        if divisor == 0:
            continue
        bodyvol = body * candle.volume / divisor
        topwickvol = 2 * topwick * candle.volume / divisor
        bottomwickvol = 2 * bottomwick * candle.volume / divisor
        for row in range(rows):
            bodypart = get_vol(levels[row], levels[row + 1], bottom, top, body, bodyvol)
            top_part = get_vol(levels[row], levels[row + 1], top, candle.high, topwick, topwickvol) / 2
            bottom_part = get_vol(levels[row], levels[row + 1], bottom, candle.low, bottomwick, bottomwickvol) / 2
            volumes[row] = volumes[row] + (bodypart if green else 0) + top_part + bottom_part
            volumes[row + rows] = volumes[row + rows] + (0 if green else bodypart) + top_part + bottom_part
    totals = [volumes[row] + volumes[row + rows] for row in range(rows)]
    if max(totals) <= 0:
        return None
    poc = totals.index(max(totals))
    target = sum(totals) * percent / 100
    accumulated = totals[poc]
    up = down = poc
    for _ in range(rows):
        if accumulated >= target:
            break
        upper = totals[up + 1] if up < rows - 1 else 0
        lower = totals[down - 1] if down > 0 else 0
        if upper == lower == 0:
            break
        if upper >= lower:
            up += 1
            accumulated += upper
        else:
            down -= 1
            accumulated += lower
    return {"poc": (levels[poc] + levels[poc + 1]) / 2,
            "val": levels[down], "vah": levels[up + 1], "volumes": totals}


class ProfileTests(unittest.TestCase):
    def assert_profiles_equal(self, bars, rows=24, percent=70):
        expected = original_pine_profile(bars, rows, percent)
        actual = profile(bars, rows, percent)
        if expected is None:
            self.assertIsNone(actual)
            return
        for key in ("poc", "val", "vah"):
            self.assertAlmostEqual(actual[key], expected[key], places=8, msg=key)
        for a, b in zip(actual["volumes"], expected["volumes"]):
            self.assertTrue(math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9), (a, b))

    def test_body_only_uniform_rows_and_first_tie(self):
        result = profile([Bar(0, 5, 0, 5, 100)], rows=5)
        self.assertEqual(result["volumes"], [20] * 5)
        self.assertEqual(result["poc"], 0.5)
        self.assertEqual((result["val"], result["vah"]), (0, 4))

    def test_hand_checked_wicks_get_twice_body_weight(self):
        result = profile([Bar(1, 5, 0, 4, 70)], rows=5)
        self.assertEqual(result["volumes"], [20, 10, 10, 10, 20])
        self.assertEqual(result["poc"], 0.5)
        self.assertEqual((result["val"], result["vah"]), (0, 4))

    def test_green_and_red_have_same_total_profile(self):
        green = profile([Bar(1, 5, 0, 4, 70)], rows=5)
        red = profile([Bar(4, 5, 0, 1, 70)], rows=5)
        self.assertEqual(green, red)

    def test_flat_candle_and_zero_volume_undefined(self):
        self.assertIsNone(profile([Bar(2, 2, 2, 2, 100)], rows=5))
        self.assertIsNone(profile([Bar(1, 5, 0, 4, 0)], rows=5))
        self.assert_profiles_equal([Bar(2, 2, 2, 2, 100), Bar(1, 5, 0, 4, 70)], 5)

    def test_doji_and_value_area_boundaries(self):
        bars = [Bar(2, 5, 0, 2, 100), Bar(4, 5, 1, 2, 30)]
        for percent in (0, 70, 100):
            with self.subTest(percent=percent):
                self.assert_profiles_equal(bars, 5, percent)

    def test_randomized_original_pine_parity(self):
        rng = random.Random(12345)
        for fixture in range(30):
            bars = []
            for _ in range(rng.choice((2, 10, 150, 500))):
                open_price = 20000 + rng.uniform(-100, 100)
                close = open_price + rng.uniform(-20, 20)
                bars.append(Bar(open_price, max(open_price, close) + rng.uniform(0.1, 15),
                                min(open_price, close) - rng.uniform(0.1, 15), close,
                                rng.randint(1, 2000)))
            with self.subTest(fixture=fixture):
                self.assert_profiles_equal(bars, rng.choice((5, 24, 100)), rng.choice((0, 70, 100)))

    def test_nonfinite_impossible_and_negative_volume_rejected(self):
        for bar in (Bar(1, 0, 0, 1, 10), Bar(1, 2, 0, 1, -1),
                    Bar(1, 2, 0, float("nan"), 10), Bar(1, 2, 0, 1, float("inf"))):
            with self.subTest(bar=bar), self.assertRaises(ValueError):
                profile([bar], rows=5)

    def test_crossing_uses_each_bars_own_moving_poc(self):
        self.assertEqual(crossing(100, 101, 100, 99), "up")
        self.assertEqual(crossing(100, 99, 100, 101), "down")

    def test_crossing_equality_and_missing_boundaries(self):
        self.assertEqual(crossing(100, 100, 101, 100), "up")
        self.assertEqual(crossing(100, 100, 99, 100), "down")
        self.assertIsNone(crossing(99, 100, 100, 100))
        self.assertIsNone(crossing(101, 100, 100, 100))
        self.assertIsNone(crossing(101, 100, 102, 100))
        self.assertIsNone(crossing(None, 100, 101, 100))


if __name__ == "__main__":
    unittest.main()
