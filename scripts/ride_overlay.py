"""Folder mode: point the ride overlay at a folder of ride clips and a FIT.

Usage:
  uv run --with fitdecode python -I ride_overlay.py <folder> [--full | --layer] [--start CLIP@S]
      [--seconds 30] [--fields hr,speed] [--units kmh|mph] [--offset S] [--dry-run]

Finds the FIT files and the camera clips in the folder (not its subfolders), matches each clip to
a ride by its recorded start time, and reports what it found. Then, by default, it makes a Reel
of the hardest --seconds (highest average power) across every clip; with --start it uses that
clip and second instead (CLIP is any unique part of the file name, e.g. 100@764). --full renders
each clip whole with the overlay, in its own shape (slow for 4K landscape: about 4-5x the clip's
length). --layer renders a transparent overlay layer for each landscape clip, for an editor.

Outputs go to <folder>/renders/; the HyperFrames projects stay in <folder>/ride-overlay/, where
`npx hyperframes@0.8.207 preview` opens one for tweaks. --fields picks the lines after power
(default hr,speed; cadence and time are the others). --units mph switches speed. --offset adds
seconds to every clip's recorded start, for a camera whose clock is wrong. --dry-run stops after
the report.
"""
import argparse
import bisect
import datetime
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reel = load("reel")
layer = load("layer")
ride_data = reel.ride_data

VIDEO = (".mp4", ".mov")
FIELD_NAMES = {"power": "power", "hr": "heart rate", "cadence": "cadence", "mph": "speed"}


def clock(t):
    return t.astimezone().strftime("%H:%M:%S %Z")


def mmss(s):
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def fit_summary(records):
    times = [d["timestamp"] for d in records if d.get("timestamp")]
    has = {
        "power": any(d.get("power") is not None for d in records),
        "hr": any(d.get("heart_rate") is not None for d in records),
        "cadence": any(d.get("cadence") is not None for d in records),
        "mph": any(d.get("enhanced_speed") is not None or d.get("speed") is not None for d in records),
    }
    return min(times), max(times), has


def scan(folder, offset):
    """FITs with their records and range, and each clip with its probe and best-matching FIT.

    A clip's coverage is the share of its seconds that have a FIT record (head units record once a
    second), not just whether it falls between the ride's first and last record: head units
    auto-pause at stops and record nothing, so a clip shot while standing still has no data.
    """
    names = sorted(n for n in os.listdir(folder) if not n.startswith("."))
    fits = {}
    for n in names:
        if n.lower().endswith(".fit"):
            records = ride_data.load_fit(os.path.join(folder, n))
            if records:
                fits[os.path.join(folder, n)] = (records, *fit_summary(records))
    stamps = {fit: sorted(d["timestamp"] for d in v[0] if d.get("timestamp")) for fit, v in fits.items()}
    clips = []
    for n in names:
        if not n.lower().endswith(VIDEO):
            continue
        path = os.path.join(folder, n)
        info = reel.probe(path)
        clip = {"path": path, "name": n, "info": info, "fit": None, "coverage": 0.0, "in_span": False}
        if info["created"]:
            t0 = datetime.datetime.fromisoformat(info["created"].replace("Z", "+00:00")) + datetime.timedelta(seconds=offset)
            clip["t0"] = t0
            t1 = t0 + datetime.timedelta(seconds=info["duration"])
            for fit, (_, first, last, _) in fits.items():
                if t0 < last and t1 > first:
                    clip["in_span"] = True
                ts = stamps[fit]
                count = bisect.bisect_right(ts, t1) - bisect.bisect_left(ts, t0)
                share = min(1.0, count / max(1.0, info["duration"]))
                if count >= 2 and share > clip["coverage"]:
                    clip["fit"], clip["coverage"] = fit, share
        clips.append(clip)
    return fits, clips


def report(folder, fits, clips, fields):
    print(f"Folder: {folder}")
    if not fits:
        print("No FIT file found. Add the head unit's file (or Strava's Export original).")
    for fit, (_, first, last, has) in fits.items():
        got = [FIELD_NAMES[k] for k, v in has.items() if v]
        lacks = [FIELD_NAMES[k] for k, v in has.items() if not v]
        print(f"FIT  {os.path.basename(fit)}: {clock(first)} to {clock(last)} ({mmss((last - first).total_seconds())})")
        print(f"     records {', '.join(got)}" + (f"; no {', '.join(lacks)}, so that line is left out" if lacks else ""))
    print(f"Clips ({len(clips)}):")
    for c in clips:
        i = c["info"]
        shape = "portrait" if i["h"] > i["w"] else "landscape"
        start = clock(c["t0"]) if "t0" in c else "no recorded start"
        if c["fit"]:
            where = "in the ride" if c["coverage"] >= 0.9 else f"in the ride, but only {c['coverage']:.0%} of it has data (paused, or partly outside)"
            if len(fits) > 1:
                where += f" ({os.path.basename(c['fit'])})"
        elif c["in_span"]:
            where = "during a pause in the recording: no ride data, skipped"
        elif "t0" in c:
            where = "outside every ride (filmed off the bike, or the camera clock is off: try --offset)"
        else:
            where = "skipped: no recorded start time"
        print(f"  {c['name']:<32} {shape:<9} {i['w']}x{i['h']:<5} {mmss(i['duration']):>7}  starts {start}  {where}")
    shown = ["power"] + [f for f in ("hr", "cadence", "speed", "time") if f in fields]
    print("Lines: " + ", ".join({"hr": "heart rate"}.get(f, f) for f in shown) + " (any the FIT lacks are left out)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="render each clip whole with the overlay")
    mode.add_argument("--layer", action="store_true", help="a transparent overlay layer per landscape clip")
    ap.add_argument("--start", help="CLIP@SECONDS for the Reel, e.g. 100@764 (default: the hardest window)")
    ap.add_argument("--seconds", type=int, default=30, help="Reel length (default 30)")
    ap.add_argument("--fields", default="hr,speed", help="lines after power: any of hr, speed, cadence, time")
    ap.add_argument("--units", choices=["kmh", "mph"], default="kmh")
    ap.add_argument("--offset", type=float, default=0.0, help="seconds to add to every clip's recorded start")
    ap.add_argument("--dry-run", action="store_true", help="report what's in the folder and stop")
    a = ap.parse_args()

    folder = os.path.abspath(os.path.expanduser(a.folder))
    fields = {f.strip() for f in a.fields.split(",") if f.strip()}
    unknown = fields - {"hr", "speed", "cadence", "time"}
    if unknown:
        sys.exit(f"unknown field(s): {', '.join(sorted(unknown))}")
    values = {"showHr": "hr" in fields, "showSpeed": "speed" in fields, "showCadence": "cadence" in fields, "showTime": "time" in fields, "units": a.units}

    fits, clips = scan(folder, a.offset)
    report(folder, fits, clips, fields)
    usable = [c for c in clips if c["fit"]]
    if not usable:
        sys.exit("Nothing to render: no clip falls inside a ride.")
    if a.dry_run:
        return

    rides = {}
    for c in list(usable):
        try:
            rides[c["path"]], _ = ride_data.build(c["fit"], c["path"], a.offset, fits[c["fit"]][0])
        except SystemExit as e:  # build() exits on a clip with no records; skip it, don't stop
            print(f"skipping {c['name']}: {e}")
            usable.remove(c)
    renders = os.path.join(folder, "renders")
    projects = os.path.join(folder, "ride-overlay")
    outputs = []

    def stem(c):
        return os.path.splitext(c["name"])[0]

    def note(c, what):
        return f"{stem(c)}, {what}, from {os.path.basename(c['fit'])}."

    if a.layer:
        todo = [c for c in usable if c["info"]["w"] > c["info"]["h"]]
        if not todo:
            sys.exit("--layer is for landscape clips, and there are none here. Portrait clips make Reels.")
        print(f"\nRendering {len(todo)} layer(s), about {mmss(sum(c['info']['duration'] for c in todo))} of render time.")
        for c in todo:
            out = os.path.join(renders, f"{stem(c)}-layer.mov")
            count = layer.make_layer(c["path"], rides[c["path"]], c["info"], out, os.path.join(projects, f"{stem(c)}-layer"), values, note=note(c, "whole clip"))
            outputs.append((out, f"{count} frames, {os.path.getsize(out) / 1e9:.2f} GB", []))
    elif a.full:
        est = sum(c["info"]["duration"] * (1 if c["info"]["h"] > c["info"]["w"] else 4.5) for c in usable)
        print(f"\nRendering {len(usable)} clip(s) whole, about {mmss(est)} of render time.")
        for c in usable:
            framing = "portrait" if c["info"]["h"] > c["info"]["w"] else "landscape"
            out = os.path.join(renders, f"{stem(c)}-overlay.mp4")
            checks = reel.render(c["path"], rides[c["path"]], c["info"], 0, c["info"]["duration"], framing, out, os.path.join(projects, f"{stem(c)}-full"), values, note(c, "whole clip"))
            outputs.append((out, framing, checks))
    else:
        if a.start:
            name, _, sec = a.start.rpartition("@")
            matches = [c for c in usable if name in c["name"]]
            if len(matches) != 1 or not sec.isdigit():
                sys.exit(f"--start {a.start}: need CLIP@SECONDS naming exactly one clip in the ride")
            c, start = matches[0], int(sec)
            if start + a.seconds > rides[c["path"]]["seconds"]:
                sys.exit(f"{c['name']} is {mmss(c['info']['duration'])} long, so {start}+{a.seconds} s runs past its end")
        else:
            best = None
            for c in usable:
                power = rides[c["path"]]["power"]
                peak = power and reel.peak_window(power, a.seconds, rides[c["path"]]["seconds"])
                if peak and (best is None or peak[1] > best[2]):
                    best = (c, peak[0], peak[1])
            if best is None:
                sys.exit(f"No power to rank by, or no clip is {a.seconds} s long. Pick the moment with --start CLIP@SECONDS.")
            c, start, avg = best
            print(f"\nHardest {a.seconds} s: {avg:.0f} W average, {c['name']} at {mmss(start)} ({start} s)")
        framing = "portrait" if c["info"]["h"] > c["info"]["w"] else "square"
        out = os.path.join(renders, f"{stem(c)}-reel-{start}s.mp4")
        checks = reel.render(c["path"], rides[c["path"]], c["info"], start, a.seconds, framing, out, os.path.join(projects, f"{stem(c)}-{start}s"), values, note(c, f"clip {start}-{start + a.seconds} s"))
        outputs.append((out, f"{framing} Reel", checks))

    print("\nDone:")
    for out, what, checks in outputs:
        print(f"  {out} ({what})")
        for png, should in checks:
            print(f"    check {png}: should read {should}")


if __name__ == "__main__":
    main()
