"""Checks on the data step: resampling, pauses, missing fields, the window pick and the readout.

Run from the repo root: uv run --with fitdecode python -m unittest discover tests
"""
import datetime
import importlib.util
import os
import unittest
from unittest import mock

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


T0 = datetime.datetime(2026, 11, 15, 16, 0, 0, tzinfo=datetime.timezone.utc)
SEMI = 2**31 / 180  # degrees to FIT semicircles


def rec(sec, **fields):
    """A FIT record at clip second `sec` (the fake clip starts at T0)."""
    return dict(timestamp=T0 + datetime.timedelta(seconds=sec), **fields)


class Build(unittest.TestCase):
    """build() end to end, with the clip's start and length faked: the spans come from the whole FIT."""

    def build(self, records, duration=9.0):
        # duration 9.0 gives samples for clip seconds 0..9.
        with mock.patch.object(ride_data, "clip_start", return_value=(T0, duration)):
            ride, _ = ride_data.build(None, "clip.mp4", records=records)
        return ride

    def test_fields_start_and_stop_on_their_own(self):
        # Heart rate pairs at second 2, power wakes at 4, and the head unit stops at 6.
        records = [rec(s, heart_rate=130 + s, power=(200 if s >= 4 else None), enhanced_speed=5.0) for s in range(2, 7)]
        ride = self.build(records)
        self.assertEqual(ride["hr"], [None, None, 132, 133, 134, 135, 136, None, None, None])
        self.assertEqual(ride["power"], [None] * 4 + [200, 200, 200] + [None] * 3)
        self.assertEqual([v is None for v in ride["mph"]], [True, True] + [False] * 5 + [True] * 3)

    def test_clip_ending_in_a_pause_holds(self):
        # The head unit auto-paused at second 3 and resumed at 100, long after this clip ended.
        # The FIT carries on, so the last reading holds to the end of the clip instead of blanking.
        records = [rec(s, power=150, heart_rate=150) for s in range(0, 4)] + [rec(100, power=300, heart_rate=170)]
        ride = self.build(records)
        self.assertEqual(ride["power"], [150] * 10)
        self.assertEqual(ride["hr"], [150] * 10)

    def test_clip_starting_in_a_pause_holds(self):
        # Paused from second -50 to 6 of this clip: the value before the pause holds, as on a head unit.
        # Heart rate, not power, so the 3 s power average doesn't blur the edge.
        records = [rec(-50, heart_rate=120), rec(-49, heart_rate=120)] + [rec(s, heart_rate=150) for s in range(6, 10)]
        self.assertEqual(self.build(records)["hr"], [120] * 6 + [150] * 4)

    def test_pause_start_holds_each_fields_own_reading(self):
        # The last record before the pause has power but no heart rate: heart rate still holds
        # its own last reading, not the one after the restart.
        records = [rec(-50, heart_rate=120), rec(-49, power=0)] + [rec(s, heart_rate=150, power=300) for s in range(6, 10)]
        ride = self.build(records)
        self.assertEqual(ride["hr"], [120] * 6 + [150] * 4)
        self.assertEqual(ride["power"][:6], [0] * 6)

    def test_old_enhanced_speed_does_not_hide_basic_speed(self):
        # Enhanced speed only before the clip, basic speed during it: speed shows from basic.
        records = [rec(-7, enhanced_speed=4.0), rec(-6, enhanced_speed=4.0)] + [rec(s, speed=5.0) for s in range(10)]
        self.assertEqual(self.build(records)["mph"], [11.18] * 10)

    def test_speed_fields_fill_each_other_per_second(self):
        records = [rec(s, enhanced_speed=4.0) for s in range(0, 5)] + [rec(s, speed=5.0) for s in range(5, 10)]
        self.assertEqual(self.build(records)["mph"], [8.95] * 5 + [11.18] * 5)

    def test_route_blank_outside_the_fit(self):
        records = [rec(s, position_lat=round((40.0 + s * 1e-4) * SEMI), position_long=round(-73.0 * SEMI), power=100) for s in range(3, 8)]
        ride = self.build(records)
        for key in ("x", "y", "len"):
            self.assertEqual(len(ride[key]), 10, key)
            self.assertEqual([v is None for v in ride[key]], [True] * 3 + [False] * 5 + [True] * 2, key)
        self.assertEqual((ride["len"][3], ride["len"][7]), (0.0, 1.0))


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
        self.assertEqual(reel.expected(ride, 0, {}), "no ride numbers (the FIT isn't recording here)")
        self.assertEqual(reel.expected(ride, 1, {}), "100 W, 140 bpm, 8.0 km/h")

    def test_blank_seconds_with_the_timer_on(self):
        # The timer keeps running on a blank frame; the readout only promises no ride numbers.
        ride = {"seconds": 1, "power": [None, 100], "hr": None, "cadence": None, "mph": None}
        self.assertEqual(reel.expected(ride, 0, {"showTime": True}), "no ride numbers (the FIT isn't recording here)")


if __name__ == "__main__":
    unittest.main()
