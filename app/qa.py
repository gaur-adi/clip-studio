"""Quality gate: checks a rendered Short BEFORE it may enter final/. Each check -> {name, ok, detail}; passed = every non-advisory check ok."""
import json, os, re, subprocess
import config as C

def _probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,duration:format=duration", "-of", "json", path], capture_output=True, text=True)
    try: return json.loads(r.stdout)
    except Exception: return {}

def _ff(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args], capture_output=True, text=True).stderr

def run_qa(video, expected_duration=None, events_path=None, layout_path=None, meta=None, dup=None, cfg=None):
    cfg = cfg or C.load(); q = cfg["qa"]; checks = []
    def add(name, ok, detail="", advisory=False): checks.append({"name": name, "ok": bool(ok), "detail": str(detail), "advisory": advisory})
    if not video or not os.path.exists(video): add("file exists", False, str(video)); return _done(checks)
    p = _probe(video); streams = p.get("streams") or []; v = next((s for s in streams if s.get("codec_type") == "video"), None); a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    add("playable video + audio streams", bool(v and a), f"video={bool(v)} audio={bool(a)}")
    if not v: return _done(checks)
    dur = float((p.get("format") or {}).get("duration") or 0)
    add("resolution 1080x1920", (v.get("width"), v.get("height")) == (1080, 1920), f"{v.get('width')}x{v.get('height')}")
    if expected_duration: add("actual duration matches the plan", abs(dur - expected_duration) <= q["duration_tolerance"], f"actual {dur:.2f}s vs planned {expected_duration:.2f}s")
    add("duration within limits", cfg["edit"]["min_len"] - 0.5 <= dur <= cfg["edit"]["max_len"] + 1.0, f"{dur:.1f}s")
    # black opening / ending
    out = _ff(["-i", video, "-vf", "blackdetect=d=0.1:pix_th=0.12", "-an", "-f", "null", "-"]); bl = [(float(a_), float(b_)) for a_, b_ in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", out)]
    head = sum(max(0, min(e, q["max_black_secs"] * 4) - s) for s, e in bl if s < 0.05); tail = sum(max(0, e - max(s, dur - 2)) for s, e in bl if e > dur - 0.05)
    add("no black opening", head <= q["max_black_secs"], f"{head:.2f}s black at the start"); add("no black ending", tail <= q["max_black_secs"], f"{tail:.2f}s black at the end")
    # silence / loudness
    out = _ff(["-i", video, "-af", "silencedetect=n=-40dB:d=0.4,volumedetect", "-vn", "-f", "null", "-"]); sil = [(float(a_), float(b_)) for a_, b_ in re.findall(r"silence_start: ([\d.]+)[\s\S]*?silence_end: ([\d.]+)", out)]
    open_sil = next((e for s, e in sil if s < 0.1), 0.0) if sil else 0.0
    add("no excessive opening silence", open_sil <= q["max_opening_silence"], f"{open_sil:.2f}s of silence at the start")
    mv = re.search(r"max_volume: (-?[\d.]+) dB", out); mean = re.search(r"mean_volume: (-?[\d.]+) dB", out)
    add("audio is audible and not clipped", bool(mean and float(mean.group(1)) > -45 and (not mv or float(mv.group(1)) < -0.05)), f"mean {mean.group(1) if mean else '?'} dB, max {mv.group(1) if mv else '?'} dB")
    # captions + layout
    ev = None
    if events_path and os.path.exists(events_path):
        ev = json.load(open(events_path)); safe = cfg["safe_area"]; bad = []; last = 0.0
        for e in ev.get("events", []):
            if e["end"] > dur + 0.05 or e["start"] < -0.01: bad.append(f"event outside the video at {e['start']:.2f}-{e['end']:.2f}")
            if e.get("kind", "caption") == "caption":                     # captions must not overlap each other (the opening banner lives elsewhere on screen)
                if e["start"] < last - 0.02: bad.append(f"overlapping caption events at {e['start']:.2f}")
                last = max(last, e["end"])
            b = e.get("box")
            if b and (b[0] < 0 or b[2] > 1080 or b[1] < 0 or b[3] > 1920): bad.append(f"text outside the canvas at {e['start']:.2f}")
            if b and (b[2] > 1080 - safe["right"] + 1 or b[0] < safe["left"] - 1 or b[3] > 1920 - safe["bottom"] + 1 or b[1] < safe["top"] - 1) and e.get("kind") != "banner_ok": bad.append(f"text inside the Shorts UI area at {e['start']:.2f}")
        add("captions: timing, overlap, canvas and safe area", not bad, "; ".join(bad[:3]) or f"{len(ev.get('events', []))} events ok")
    else: add("captions: timing, overlap, canvas and safe area", True, "no captions (none generated)", advisory=True)
    if layout_path and os.path.exists(layout_path):
        L = json.load(open(layout_path)); g = L["regions"].get("gameplay"); share = (g["w"] * g["h"]) / (1080 * 1920) if g else 0
        add("gameplay readable on a phone", share >= q["min_gameplay_share"], f"gameplay occupies {share:.0%} of the frame ({L.get('preset')})")
        fb = L.get("face_box")
        if ev and fb:
            hit = [e for e in ev["events"] if e.get("box") and not (e["box"][2] < fb["x"] or e["box"][0] > fb["x"] + fb["w"] or e["box"][3] < fb["y"] or e["box"][1] > fb["y"] + fb["h"])]
            add("captions do not cover the face", not hit, f"{len(hit)} caption events overlap the facecam")
    else: add("framing layout recorded", False, "no layout file")
    if meta:
        add("title present and specific", bool(meta.get("title")) and len(meta["title"]) >= 6, meta.get("title", ""))
        add("language recorded", meta.get("language") in ("hi", "en"), str(meta.get("language")), advisory=True)
        if meta.get("topic") is not None and meta["topic"].get("verified") is False: add("game/topic verified", False, "unverified: neutral wording used", advisory=True)
    if dup: add("not a duplicate source moment", False, f"overlaps clip {dup.get('clip_id')} (state {dup.get('state')})")
    else: add("not a duplicate source moment", True)
    return _done(checks)

def _done(checks): return {"passed": all(c["ok"] for c in checks if not c["advisory"]), "checks": checks, "failed": [c["name"] for c in checks if not c["ok"] and not c["advisory"]]}
