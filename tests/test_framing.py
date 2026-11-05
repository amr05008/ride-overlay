"""Checks on the framing: a clip comes out in the shape it was shot in, unless --square asks otherwise.

Run from the repo root: uv run --with fitdecode python -m unittest discover tests
"""
import contextlib
import datetime
import importlib.util
import io
import os
import subprocess
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reel = load("reel")
ride_overlay = load("ride_overlay")

LANDSCAPE = {"w": 2688, "h": 1520, "duration": 80.0}
PORTRAIT = {"w": 1520, "h": 2688, "duration": 109.0}


class FramingFor(unittest.TestCase):
    def test_landscape_stays_16_9(self):
        framing = reel.framing_for(LANDSCAPE)
        self.assertEqual(framing, "landscape")
        w, h = reel.FRAMES[framing]
        self.assertAlmostEqual(w / h, 16 / 9)

    def test_portrait_stays_9_16(self):
        framing = reel.framing_for(PORTRAIT)
        self.assertEqual(framing, "portrait")
        w, h = reel.FRAMES[framing]
        self.assertAlmostEqual(w / h, 9 / 16)

    def test_square_is_opt_in(self):
        self.assertEqual(reel.framing_for(LANDSCAPE, square=True), "square")

    def test_square_leaves_portrait_alone(self):
        self.assertEqual(reel.framing_for(PORTRAIT, square=True), "portrait")


class Report(unittest.TestCase):
    def rows(self, **kw):
        t0 = datetime.datetime(2026, 11, 4, 18, 0, tzinfo=datetime.timezone.utc)
        base = {"fit": "ride.fit", "coverage": 1.0, "in_span": True, "t0": t0}
        clips = [dict(base, name="wide.mp4", info=LANDSCAPE), dict(base, name="tall.mp4", info=PORTRAIT)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ride_overlay.report("folder", {}, clips, {"hr", "speed"}, **kw)
        lines = out.getvalue().splitlines()
        return next(l for l in lines if "wide.mp4" in l), next(l for l in lines if "tall.mp4" in l)

    def test_says_what_each_clip_renders_as(self):
        wide, tall = self.rows()
        self.assertIn("renders as 16:9 (3840x2160)", wide)
        self.assertIn("renders as 9:16 (1080x1920)", tall)

    def test_says_when_square_was_asked_for(self):
        wide, tall = self.rows(square=True)
        self.assertIn("renders as square on 9:16 (1080x1920)", wide)
        self.assertIn("renders as 9:16 (1080x1920)", tall)

    def test_layers_get_no_shape_note(self):
        wide, tall = self.rows(layer=True)
        self.assertNotIn("renders as", wide)
        self.assertNotIn("renders as", tall)

    def test_a_clip_with_no_ride_data_gets_no_shape_note(self):
        t0 = datetime.datetime(2026, 11, 4, 18, 0, tzinfo=datetime.timezone.utc)
        clip = {"fit": None, "coverage": 0.0, "in_span": False, "t0": t0, "name": "off-bike.mp4", "info": LANDSCAPE}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ride_overlay.report("folder", {}, [clip], {"hr", "speed"})
        self.assertNotIn("renders as", out.getvalue())


class Flags(unittest.TestCase):
    def test_square_is_only_for_a_reel(self):
        for other in ("--full", "--layer"):
            run = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "ride_overlay.py"), "folder", "--square", other],
                capture_output=True,
                text=True,
            )
            self.assertEqual(run.returncode, 2, run.stderr)
            self.assertIn("not allowed", run.stderr)


if __name__ == "__main__":
    unittest.main()
