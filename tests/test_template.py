"""Runs the overlay template's own script in Node, with a stub page and timeline, and checks
which lines show at each second: blank seconds hide a line, a zero still shows, and seeking
back brings lines back. Skipped where Node isn't installed.

Run from the repo root: uv run --with fitdecode python -m unittest discover tests
"""
import json
import os
import re
import shutil
import subprocess
import unittest

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "template", "overlay.html")

# A stub of the few DOM and GSAP calls the template makes. The template's script runs unchanged;
# the harness then seeks its timeline and reads back each line's visibility and text.
HARNESS = r"""
const [src, ride, times] = JSON.parse(require("fs").readFileSync(0, "utf8"));
const els = {};
const el = (id) => (els[id] ??= {
  textContent: "", style: {},
  parentElement: { style: {}, dataset: { width: "3840", height: "2160" }, classList: { names: new Set(), add(c) { this.names.add(c); } } },
});
globalThis.document = { getElementById: el };
globalThis.window = { RIDE: ride, __timelines: {} };
let tween;
globalThis.gsap = { timeline: () => ({ fromTo(target, from, to) { tween = { target, to }; return this; } }) };
new Function(src)();
const read = (id) => {
  const p = el(id).parentElement;
  // A real page turns textContent into a string; the stub keeps what was set, so convert here.
  return p.classList.names.has("ov-hidden") || p.style.visibility === "hidden" ? null : String(el(id).textContent);
};
const out = times.map((t) => {
  tween.target.t = t;
  tween.to.onUpdate();
  return { power: read("ov-power"), hr: read("ov-hr"), cadence: read("ov-cad"), speed: read("ov-speed") };
});
console.log(JSON.stringify(out));
"""


def script():
    with open(TEMPLATE) as fh:
        return re.search(r"<script>(.*?)</script>", fh.read(), re.S).group(1)


@unittest.skipUnless(shutil.which("node"), "needs node")
class Draw(unittest.TestCase):
    def frames(self, ride, times):
        run = subprocess.run(["node", "-e", HARNESS], input=json.dumps([script(), ride, times]), capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def test_blank_seconds_hide_lines_and_seeking_back_restores_them(self):
        # Head unit off, heart rate and speed only, power at zero, all three, power gone, all off.
        ride = {"seconds": 5, "power": [None, None, 0, 250, None, None], "hr": [None, 140, 141, 142, 143, None],
                "cadence": None, "mph": [None, 3, 0.1, 10, 12, None]}
        frames = self.frames(ride, [0, 1, 2, 3, 4, 5, 3.5, 0.5])
        none = {"power": None, "hr": None, "cadence": None, "speed": None}
        self.assertEqual(frames[0], none)
        self.assertEqual(frames[1], {"power": None, "hr": "140", "cadence": None, "speed": "4.8"})
        self.assertEqual(frames[2], {"power": "0", "hr": "141", "cadence": None, "speed": "0.0"})
        self.assertEqual(frames[3], {"power": "250", "hr": "142", "cadence": None, "speed": "16.1"})
        self.assertEqual(frames[4], {"power": None, "hr": "143", "cadence": None, "speed": "19.3"})
        self.assertEqual(frames[5], none)
        self.assertEqual(frames[6], frames[3])  # seeking back
        self.assertEqual(frames[7], none)

    def test_a_field_the_fit_lacks_stays_out(self):
        ride = {"seconds": 1, "power": [100, 110], "hr": None, "cadence": None, "mph": [5, 5]}
        self.assertEqual(self.frames(ride, [1]), [{"power": "110", "hr": None, "cadence": None, "speed": "8.0"}])


if __name__ == "__main__":
    unittest.main()
