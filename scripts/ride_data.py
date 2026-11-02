"""Turn a ride's FIT file into per-second overlay data for one camera clip.

Usage: uv run --with fitdecode python -I ride_data.py <ride.fit> <clip.mp4> <out ride.js>

The clip's start comes from its creation_time tag, which cameras like the Insta360 GO Ultra write
in UTC. Use it, not the file name: the name is local time, and around a daylight-saving change it
can be an hour off while the tag stays right. Samples are resampled to one per clip second,
starting at clip second 0. Power is a 3 s average, like a head unit. Across a gap (head units
auto-pause at stops and record nothing) the last value is held rather than ramped. A field the
FIT doesn't record (no heart-rate strap, no power meter, no GPS) is written as null, and the
overlay leaves that line out. The route is normalized to a unit square (north up) for a map.
"""
import datetime
import json
import math
import subprocess
import sys

import fitdecode

FIELDS = ("power", "hr", "cadence", "mph")


def clip_start(clip):
    """The clip's UTC start and duration in seconds, from ffprobe."""
    probe = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags=creation_time", "-of", "json", clip],
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    )["format"]
    t0 = datetime.datetime.fromisoformat(probe["tags"]["creation_time"].replace("Z", "+00:00"))
    return t0, float(probe["duration"])


def load_fit(fit):
    """All of a FIT's record messages, as dicts with a UTC "timestamp"."""
    with fitdecode.FitReader(fit) as fr:
        return [
            {fl.name: fl.value for fl in f.fields}
            for f in fr
            if isinstance(f, fitdecode.FitDataMessage) and f.name == "record"
        ]


def resample(recs, key, n, scale=1.0):
    """One value of `key` per second for seconds 0..n-1, from (clip seconds, record) pairs.

    Interpolates between records a second or two apart and holds the last value across a longer
    gap (an auto-pause). Returns None if no record has the field.
    """
    pts = [(t, d[key]) for t, d in recs if d.get(key) is not None]
    if not pts:
        return None
    vals, j = [], 0
    for s in range(n):
        while j + 1 < len(pts) and pts[j + 1][0] <= s:
            j += 1
        (ta, va), (tb, vb) = pts[j], pts[min(j + 1, len(pts) - 1)]
        f = 0 if tb == ta or tb - ta > 2 else max(0, min(1, (s - ta) / (tb - ta)))
        vals.append((va + (vb - va) * f) * scale)
    return vals


def build(fit, clip, offset=0.0, records=None):
    """Return the ride dict for the clip (one sample per clip second) and the FIT record count.

    offset (seconds) corrects a camera clock: it's added to the clip's recorded start.
    Pass records (from load_fit) to avoid re-reading the FIT for every clip.
    """
    t0, duration = clip_start(clip)
    t0 += datetime.timedelta(seconds=offset)
    n = int(math.ceil(duration)) + 1
    recs = []
    for d in records if records is not None else load_fit(fit):
        t = (d["timestamp"] - t0).total_seconds()
        if -5 <= t <= n + 5:
            recs.append((t, d))
    if len(recs) < 2:
        sys.exit(f"FIT has no records inside the clip ({t0.isoformat()}, {n} s): wrong file or unsynced camera clock")

    def rounded(vals, nd):
        return None if vals is None else [round(v, nd) for v in vals]

    semi = 180 / 2**31
    lat = resample(recs, "position_lat", n, semi)
    lon = resample(recs, "position_long", n, semi)
    x = y = length = None
    if lat and lon:
        k = math.cos(math.radians(sum(lat) / n))
        xs, ys = [v * k for v in lon], [-v for v in lat]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1
        ox = (1 - (max(xs) - min(xs)) / span) / 2
        oy = (1 - (max(ys) - min(ys)) / span) / 2
        x = [round(ox + (v - min(xs)) / span, 4) for v in xs]
        y = [round(oy + (v - min(ys)) / span, 4) for v in ys]
        cum = [0.0]
        for i in range(1, n):
            cum.append(cum[-1] + math.hypot(x[i] - x[i - 1], y[i] - y[i - 1]))
        length = [round(v / (cum[-1] or 1), 5) for v in cum]

    pw = resample(recs, "power", n)
    power = None if pw is None else [sum(pw[max(0, i - 2) : i + 1]) / len(pw[max(0, i - 2) : i + 1]) for i in range(n)]
    ride = {
        "start": t0.isoformat(),
        "seconds": n - 1,
        "mph": rounded(resample(recs, "enhanced_speed", n, 2.23694) or resample(recs, "speed", n, 2.23694), 2),
        "power": rounded(power, 1),
        "cadence": rounded(resample(recs, "cadence", n), 1),
        "hr": rounded(resample(recs, "heart_rate", n), 1),
        "x": x,
        "y": y,
        "len": length,
    }
    return ride, len(recs)


def missing(ride):
    return [k for k in FIELDS if ride[k] is None]


def write_js(ride, path, note):
    with open(path, "w") as fh:
        fh.write(f"// {note} Power is a 3 s average.\n")
        fh.write("window.RIDE = " + json.dumps(ride, separators=(",", ":")) + ";\n")


if __name__ == "__main__":
    fit, clip, out = sys.argv[1:4]
    ride, nrecs = build(fit, clip)
    write_js(ride, out, "Generated by ride_data.py from " + fit.rsplit("/", 1)[-1] + ".")
    print(f"{nrecs} FIT records, {ride['seconds'] + 1} samples from {ride['start']}, wrote {out}")
    if missing(ride):
        print("not in this FIT, so the overlay drops it:", ", ".join(missing(ride)))
