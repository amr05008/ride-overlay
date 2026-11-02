"""Cut a Reel from a ride clip with the overlay on it.

Usage:
  uv run --with fitdecode python -I reel.py <clip.mp4> <ride.fit> [--start S] [--seconds 30]
      [--vars '{"showTime":true}'] [--offset S] [--out <reel.mp4>] [--work <dir>]

Without --start it takes the window with the highest average power. Pass the camera original,
not an Insta360 Studio export: its creation_time is what lines it up with the FIT. For a whole
folder (several clips, the moment picked across all of them) use ride_overlay.py instead; it
calls render() here.

render() steps: cut the window with ffmpeg (which applies the camera's rotation and avoids
HyperFrames proxying a multi-GB HEVC file); write a HyperFrames project in one of three framings
(portrait: a portrait clip fills a 1080x1920 frame; square: a landscape clip as a square centre
crop on a blurred, darkened copy of itself, 1080x1920; landscape: a landscape clip filling a 4K
frame); lint it; render it with the clip's sound; then save three check frames and work out
what the overlay should read in each.

Defaults: <clip dir>/renders/<clip>-reel-<start>s.mp4, project in <clip dir>/ride-overlay/.
"""
import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
HF = ["npx", "-y", "hyperframes@0.8.207"]
ENV = dict(os.environ, DO_NOT_TRACK="1")  # no HeyGen telemetry, ever
FRAMES = {"portrait": (1080, 1920), "square": (1080, 1920), "landscape": (3840, 2160)}
BITRATE = {"portrait": "16M", "square": "16M", "landscape": "45M"}

spec = importlib.util.spec_from_file_location("ride_data", os.path.join(HERE, "ride_data.py"))
ride_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ride_data)


def probe(clip):
    """Display size (rotation applied), frame rate, duration, sound and recorded start of a clip."""
    info = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", clip],
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    )
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    rot = 0
    for sd in v.get("side_data_list", []):
        if "rotation" in sd:
            rot = int(sd["rotation"])
    w, h = (v["height"], v["width"]) if rot % 180 else (v["width"], v["height"])
    return {
        "w": w,
        "h": h,
        "fps": v["r_frame_rate"],
        "duration": float(info["format"]["duration"]),
        "created": info["format"].get("tags", {}).get("creation_time"),
        "audio": any(s["codec_type"] == "audio" for s in info["streams"]),
    }


def write_project(work, width, height, index, name):
    """Write a HyperFrames project around index.html, with the overlay template sized to the frame."""
    with open(os.path.join(SKILL, "template", "overlay.html")) as fh:
        overlay = fh.read().replace("__W__", str(width)).replace("__H__", str(height))
    files = {
        "compositions/overlay.html": overlay,
        "index.html": index,
        "hyperframes.json": json.dumps({"paths": {"blocks": "compositions", "assets": "assets"}, "media": {"autoProxy": True}}, indent=2) + "\n",
        "package.json": json.dumps({"name": name, "private": True, "type": "module"}, indent=2) + "\n",
    }
    for rel, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(work, rel)), exist_ok=True)
        with open(os.path.join(work, rel), "w") as fh:
            fh.write(text)


def lint(work):
    """hyperframes check; exit with its errors if it fails."""
    check = subprocess.run(HF + ["check", "--json"], cwd=work, env=ENV, capture_output=True, text=True)
    report = json.loads(check.stdout[check.stdout.index("{") :])
    errors = [f for sec in report.values() if isinstance(sec, dict) for f in sec.get("findings", []) if f.get("severity") == "error"]
    if not report.get("ok") or errors:
        for f in errors:
            print("check error:", f.get("code"), f.get("message"))
        sys.exit("hyperframes check failed; project left in " + work)


def peak_window(power, seconds, length):
    """Start second and average of the window with the highest average power, or None if too short."""
    last = int(length - seconds)
    if last < 0:
        return None
    sums = [sum(power[i : i + seconds]) for i in range(last + 1)]
    best = max(range(len(sums)), key=sums.__getitem__)
    return best, sums[best] / seconds


def expected(ride, t, v):
    """What the overlay shows at window time t, mirroring the template's formatting."""
    s = min(int(t), ride["seconds"])
    out = []
    if ride["power"]:
        out.append(f"{round(ride['power'][s])} W")
    if v.get("showHr", True) and ride["hr"]:
        out.append(f"{round(ride['hr'][s])} bpm")
    if v.get("showCadence", False) and ride["cadence"]:
        out.append(f"{round(ride['cadence'][s])} rpm")
    if v.get("showSpeed", True) and ride["mph"]:
        mph = ride["mph"][s]
        kmh = v.get("units", "kmh") == "kmh"
        val = 0 if mph < 0.3 else mph * 1.609344 if kmh else mph
        out.append(f"{val:.1f} {'km/h' if kmh else 'mph'}")
    return ", ".join(out)


def index_html(framing, seconds, values):
    W, H = FRAMES[framing]
    fg = {
        "portrait": f"top: 0; height: {H}px; object-fit: cover;",
        "square": f"top: {(H - W) // 2}px; height: {W}px; object-fit: cover;",
        "landscape": f"top: 0; height: {H}px; object-fit: cover;",
    }[framing]
    media = f'src="assets/clip.mp4" data-start="0" data-duration="{seconds}"'
    bg = f'<video id="bg" class="clip" {media} data-track-index="0" muted playsinline></video>' if framing == "square" else ""
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={W}, height={H}" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <script src="assets/ride.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {W}px; height: {H}px; overflow: hidden; background: #000000; }}
      #root {{ width: 100%; height: 100%; }}
      #bg {{
        position: absolute; left: 0; top: 0; width: {W}px; height: {H}px; object-fit: cover;
        filter: blur(36px) brightness(0.55); transform: scale(1.12); z-index: 0;
      }}
      #fg {{ position: absolute; left: 0; width: {W}px; {fg} z-index: 1; }}
      #overlay {{ position: absolute; left: 0; top: 0; width: {W}px; height: {H}px; z-index: 2; }}
    </style>
  </head>
  <body>
    <!-- Generated by ride-overlay/scripts/reel.py ({framing}). -->
    <div id="root" data-composition-id="main" data-start="0" data-duration="{seconds}" data-width="{W}" data-height="{H}">
      {bg}
      <video id="fg" class="clip" {media} data-track-index="1" data-has-audio="true" playsinline></video>
      <div id="overlay" data-composition-id="overlay" data-composition-src="compositions/overlay.html"
        data-variable-values='{json.dumps(values, separators=(",", ":"))}' data-start="0" data-duration="{seconds}"
        data-track-index="2" data-track-kind="graphics" data-width="{W}" data-height="{H}"></div>
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
"""


def render(clip, ride, info, start, seconds, framing, out, work, values, note):
    """Render clip seconds start..start+seconds with the overlay. Returns [(check png, expected)]."""
    W, H = FRAMES[framing]
    stem = os.path.splitext(os.path.basename(clip))[0]
    for d in (os.path.dirname(out), os.path.join(work, "assets"), os.path.join(work, "check")):
        os.makedirs(d, exist_ok=True)

    # The window's footage, rotation applied. Portrait is sized to the frame; landscape for a
    # square is cut at 1080 tall, so the crop is 1080x1080 with no upscaling; landscape for a
    # 4K frame keeps its own size and the page scales it.
    vf = {
        "portrait": f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}",
        "square": "scale=-2:1080:flags=lanczos",
        "landscape": "scale=trunc(iw/2)*2:trunc(ih/2)*2",
    }[framing]
    cut = ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(seconds), "-i", clip, "-vf", vf]
    cut += ["-c:v", "libx264", "-crf", "16", "-preset", "medium" if seconds <= 120 else "veryfast", "-pix_fmt", "yuv420p"]
    cut += (["-c:a", "aac", "-b:a", "192k"] if info["audio"] else ["-an"]) + ["-movflags", "+faststart", os.path.join(work, "assets", "clip.mp4")]
    subprocess.run(cut, check=True)

    n = math.ceil(seconds)
    window = {k: (v[start : start + n + 1] if isinstance(v, list) else v) for k, v in ride.items()}
    window["seconds"] = n
    ride_data.write_js(window, os.path.join(work, "assets", "ride.js"), note)
    write_project(work, W, H, index_html(framing, round(seconds, 3), values), f"{stem.lower()}-{framing}")
    lint(work)

    cmd = HF + ["render", "--fps", info["fps"], "--video-bitrate", BITRATE[framing], "--output", out]
    result = subprocess.run(cmd, cwd=work, env=ENV, capture_output=True, text=True)
    if result.returncode:
        print((result.stdout + result.stderr)[-3000:])
        sys.exit("hyperframes render failed; project left in " + work)
    checks = []
    for frac in (0.2, 0.5, 0.8):
        t = round(seconds * frac, 1)
        png = os.path.join(work, "check", f"at-{t}s.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", out, "-frames:v", "1", png], check=True)
        checks.append((png, expected(window, t, values)))
    return checks


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("clip")
    ap.add_argument("fit")
    ap.add_argument("--start", type=int, help="window start, in clip seconds (default: highest average power)")
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--vars", default="{}", help="overlay variables as JSON, e.g. {\"showTime\":true}")
    ap.add_argument("--offset", type=float, default=0.0, help="seconds to add to the camera's clock")
    ap.add_argument("--out")
    ap.add_argument("--work")
    a = ap.parse_args()
    clip = os.path.abspath(a.clip)
    stem = os.path.splitext(os.path.basename(clip))[0]
    values = json.loads(a.vars)

    info = probe(clip)
    framing = "portrait" if info["h"] > info["w"] else "square"
    ride, nrecs = ride_data.build(a.fit, clip, a.offset)
    print(f"{stem}: {info['w']}x{info['h']} ({framing}), {ride['seconds']} s;", nrecs, "FIT records")
    if ride_data.missing(ride):
        print("not in this FIT, so the overlay drops it:", ", ".join(ride_data.missing(ride)))

    if a.start is None:
        if not ride["power"]:
            sys.exit("no power in this FIT, so pass --start")
        peak = peak_window(ride["power"], a.seconds, ride["seconds"])
        if peak is None:
            sys.exit(f"clip is shorter than {a.seconds} s")
        start, avg = peak
        print(f"highest {a.seconds} s average power: {avg:.0f} W at clip {start}-{start + a.seconds} s")
    else:
        start = a.start
    if start + a.seconds > ride["seconds"]:
        sys.exit(f"window {start}-{start + a.seconds} s runs past the clip ({ride['seconds']} s)")

    base = os.path.dirname(clip)
    out = os.path.abspath(a.out or os.path.join(base, "renders", f"{stem}-reel-{start}s.mp4"))
    work = os.path.abspath(a.work or os.path.join(base, "ride-overlay", f"{stem}-{start}s"))
    note = f"{stem}, clip {start}-{start + a.seconds} s, from {os.path.basename(a.fit)}."
    checks = render(clip, ride, info, start, a.seconds, framing, out, work, values, note)
    print("wrote", out)
    for png, should in checks:
        print(f"check {png}: should read {should}")


if __name__ == "__main__":
    main()
