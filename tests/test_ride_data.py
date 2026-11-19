"""Checks on the data step: resampling, pauses, missing fields, the window pick and the readout.

Run from the repo root: uv run --with fitdecode python -m unittest discover tests
"""
import importlib.util
import os
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ride_data = load("ride_data")
reel = load("reel")


class Resample(unittest.TestCase):
    def test_one_value_per_second(self):
        recs = [(0, {"power": 100}), (1, {"power": 200}), (2, {"power": 300})]
        self.assertEqual(ride_data.resample(recs, "power", 3), [100, 200, 300])

    def test_interpolates_records_off_the_second(self):
        recs = [(-0.5, {"power": 100}), (0.5, {"power": 200})]
        self.assertEqual(ride_data.resample(recs, "power", 1), [150])

    def test_holds_across_a_pause(self):
        # A head unit auto-paused for 10 s: hold the last value, don't ramp to the restart.
        recs = [(0, {"enhanced_speed": 0.1}), (10, {"enhanced_speed": 3.0})]
        vals = ride_data.resample(recs, "enhanced_speed", 11)
        self.assertEqual(vals[:10], [0.1] * 10)
        self.assertEqual(vals[10], 3.0)

    def test_missing_field_is_none(self):
        recs = [(0, {"power": 100}), (1, {"power": 120})]
        self.assertIsNone(ride_data.resample(recs, "heart_rate", 2))

    def test_skips_empty_samples(self):
        recs = [(0, {"heart_rate": 140}), (1, {"heart_rate": None}), (2, {"heart_rate": 150})]
        self.assertEqual(ride_data.resample(recs, "heart_rate", 3), [140, 145, 150])

    def test_scale(self):
        recs = [(0, {"enhanced_speed": 10.0}), (1, {"enhanced_speed": 10.0})]
        self.assertAlmostEqual(ride_data.resample(recs, "enhanced_speed", 1, 2.23694)[0], 22.3694)

    def test_blank_before_and_after_the_fit(self):
        # The camera rolled before the head unit started (a race grid) and after it stopped:
        # those seconds are empty, not the first or last reading held.
        recs = [(2, {"power": 180}), (3, {"power": 300}), (4, {"power": 250})]
        self.assertEqual(ride_data.resample(recs, "power", 7, cover=(2, 4)), [None, None, 180, 300, 250, None, None])

    def test_cover_still_holds_across_a_pause(self):
        # The clip ends inside an auto-pause and the FIT carries on afterwards: still a hold.
        recs = [(0, {"enhanced_speed": 0.1}), (1, {"enhanced_speed": 0.1})]
        self.assertEqual(ride_data.resample(recs, "enhanced_speed", 5, cover=(0, 500)), [0.1] * 5)

    def test_cover_within_half_a_second(self):
        # Records land on whole UTC seconds and clips don't: a sample 0.4 s from the first one counts.
        recs = [(1.4, {"heart_rate": 133}), (2.4, {"heart_rate": 135})]
        self.assertEqual(ride_data.resample(recs, "heart_rate", 3, cover=(1.4, 2.4))[:2], [None, 133])


class Average3(unittest.TestCase):
    def test_three_second_average(self):
        self.assertEqual(ride_data.average3([100, 200, 300, 400]), [100, 150, 200, 300])

    def test_empty_seconds_stay_empty(self):
        self.assertEqual(ride_data.average3([None, None, 100, 200, None]), [None, None, 100, 150, None])


class PeakWindow(unittest.TestCase):
    def test_finds_the_hardest_window(self):
        power = [100] * 20 + [400] * 5 + [100] * 20
        start, avg = reel.peak_window(power, 5, len(power) - 1)
        self.assertEqual((start, avg), (20, 400))

    def test_clip_too_short(self):
        self.assertIsNone(reel.peak_window([100] * 10, 30, 9))

    def test_skips_windows_outside_the_fit(self):
        # The window that would win if empty seconds counted as zero still can't include them.
        power = [None, 900, 900, 100, 100, 100]
        self.assertEqual(reel.peak_window(power, 3, len(power) - 1), (1, 1900 / 3))

    def test_no_full_window(self):
        self.assertIsNone(reel.peak_window([None, 100, None, 100], 2, 3))


class Readout(unittest.TestCase):
    ride = {"seconds": 2, "power": [100.4, 200.6, 300], "hr": None, "cadence": [80, 81, 82], "mph": [0.2, 10, 20]}

    def test_defaults_drop_missing_heart_rate_and_zero_a_stop(self):
        self.assertEqual(reel.expected(self.ride, 0, {}), "100 W, 0.0 km/h")

    def test_fields_and_units(self):
        self.assertEqual(reel.expected(self.ride, 1.5, {"units": "mph", "showCadence": True}), "201 W, 81 rpm, 10.0 mph")

    def test_speed_off(self):
        self.assertEqual(reel.expected(self.ride, 2, {"showSpeed": False}), "300 W")

    def test_blank_seconds(self):
        ride = {"seconds": 1, "power": [None, 100], "hr": [None, 140], "cadence": None, "mph": [None, 5]}
        self.assertEqual(reel.expected(ride, 0, {}), "no numbers (the FIT isn't recording here)")
        self.assertEqual(reel.expected(ride, 1, {}), "100 W, 140 bpm, 8.0 km/h")


if __name__ == "__main__":
    unittest.main()
