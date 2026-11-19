"""Turn a ride's FIT file into per-second overlay data for one camera clip.

Usage: uv run --with fitdecode python -I ride_data.py <ride.fit> <clip.mp4> <out ride.js>

The clip's start comes from its creation_time tag, which cameras like the Insta360 GO Ultra write
in UTC. Use it, not the file name: the name is local time, and around a daylight-saving change it
can be an hour off while the tag stays right. Samples are resampled to one per clip second,
starting at clip second 0. Power is a 3 s average, like a head unit. Across a gap (head units
auto-pause at stops and record nothing) the last value is held rather than ramped. Seconds before
the FIT's first sample of a field or after its last (the head unit wasn't recording yet, or had
stopped) are null, and the overlay leaves that line blank there rather than holding the nearest
value. A field the FIT doesn't record at all (no heart-rate strap, no power meter, no GPS) is
written as null, and the overlay leaves that line out. The route is normalized to a unit square
(north up) for a map.
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


def resample(recs, key, n, scale=1.0, cover=None):
    """One value of `key` per second for seconds 0..n-1, from (clip seconds, record) pairs.

    Interpolates between records a second or two apart and holds the last value across a longer
    gap (an auto-pause). Returns None if no record has the field.

    cover is (first, last): the clip seconds of the field's first and last sample in the whole
    FIT. A second more than half a second outside it is None, because the head unit wasn't
    recording yet or had stopped. Without cover, the nearest value is held at both ends.
    """
    pts = [(t, d[key]) for t, d in recs if d.get(key) is not None]
    if not pts:
        return None
    lo, hi = cover or (-math.inf, math.inf)
    vals, j = [], 0
    for s in range(n):
        if s < lo - 0.5 or s > hi + 0.5:
            vals.append(None)
            continue
        while j + 1 < len(pts) and pts[j + 1][0] <= s:
            j += 1
        (ta, va), (tb, vb) = pts[j], pts[min(j + 1, len(pts) - 1)]
        f = 0 if tb == ta or tb - ta > 2 else max(0, min(1, (s - ta) / (tb - ta)))
        vals.append((va + (vb - va) * f) * scale)
    return vals


def average3(vals):
    """A 3 s trailing average, like a head unit's power, skipping empty seconds; None stays None."""
    out = []
    for i, v in enumerate(vals):
        recent = [x for x in vals[max(0, i - 2) : i + 1] if x is not None]
        out.append(None if v is None else sum(recent) / len(recent))
    return out


def build(fit, clip, offset=0.0, records=None):
    """Return the ride dict for the clip (one sample per clip second) and the FIT record count.

    offset (seconds) corrects a camera clock: it's added to the clip's recorded start.
    Pass records (from load_fit) to avoid re-reading the FIT for every clip.
    """
    t0, duration = clip_start(clip)
    t0 += datetime.timedelta(seconds=offset)
    n = int(math.ceil(duration)) + 1
    allrecs = records if records is not None else load_fit(fit)
    # recs: the clip's window. before: each field's last sample ahead of the window, so a clip
    # that starts inside an auto-pause holds the reading from before the pause, field by field,
    # rather than the first one after the rider set off again.
    recs, before = [], {}
    for d in allrecs:
        t = (d["timestamp"] - t0).total_seconds()
        if -5 <= t <= n + 5:
            recs.append((t, d))
        elif t < -5:
            for key, v in d.items():
                if v is not None and (key not in before or t > before[key][0]):
                    before[key] = (t, d)
    if len(recs) < 2:
        sys.exit(f"FIT has no records inside the clip ({t0.isoformat()}, {n} s): wrong file or unsynced camera clock")

    def field(key, scale=1.0):
        """resample() limited to the seconds the whole FIT has this field, so it's blank outside them."""
        ts = [(d["timestamp"] - t0).total_seconds() for d in allrecs if d.get(key) is not None]
        lead = [before[key]] if key in before else []
        return resample(lead + recs, key, n, scale, (min(ts), max(ts)) if ts else None)

    def either(a, b):
        """Per second, a's value where it has one, else b's: an all-blank a mustn't hide b."""
        if a is None or b is None:
            return a if b is None else b
        return [x if x is not None else y for x, y in zip(a, b)]

    def rounded(vals, nd):
        return None if vals is None else [None if v is None else round(v, nd) for v in vals]

    semi = 180 / 2**31
    lat = field("position_lat", semi)
    lon = field("position_long", semi)
    x = y = length = None
    have = [i for i in range(n) if lat and lon and lat[i] is not None and lon[i] is not None]
    if have:
        k = math.cos(math.radians(sum(lat[i] for i in have) / len(have)))
        xs, ys = [lon[i] * k for i in have], [-lat[i] for i in have]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1
        ox = (1 - (max(xs) - min(xs)) / span) / 2
        oy = (1 - (max(ys) - min(ys)) / span) / 2
        x, y, length = [None] * n, [None] * n, [None] * n
        for i, vx, vy in zip(have, xs, ys):
            x[i] = round(ox + (vx - min(xs)) / span, 4)
            y[i] = round(oy + (vy - min(ys)) / span, 4)
        cum, total = {have[0]: 0.0}, 0.0
        for a, b in zip(have, have[1:]):
            total += math.hypot(x[b] - x[a], y[b] - y[a])
            cum[b] = total
        for i in have:
            length[i] = round(cum[i] / (total or 1), 5)

    pw = field("power")
    ride = {
        "start": t0.isoformat(),
        "seconds": n - 1,
        "mph": rounded(either(field("enhanced_speed", 2.23694), field("speed", 2.23694)), 2),
        "power": rounded(None if pw is None else average3(pw), 1),
        "cadence": rounded(field("cadence"), 1),
        "hr": rounded(field("heart_rate"), 1),
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
