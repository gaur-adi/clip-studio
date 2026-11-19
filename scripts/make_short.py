#!/usr/bin/env python3
"""One-shot pipeline: cut (edit segments) -> reframe 1080x1920 -> timed captions + short opening line -> optional music -> MP4 (+ <out>.render.json report).
  make_short.py SRC.mp4 --plan plan.json  [--mode context|gameplay|gameplay_facecam] [--words-file source_words.json] [-o out.mp4]
  make_short.py SRC.mp4 --segments "23.4,37.8"        (several: "10,15;21,34" - captions are remapped through the same map)
  make_short.py SRC.mp4 --start 0:41 --dur 32         (legacy single window)
Words in --words-file are SOURCE-relative; they are remapped through the exact segment map used for the cut. Without a words file the edited clip is transcribed."""
import argparse, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app")); import config as C, editplan as E
py = sys.executable
ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("--start", default=None); ap.add_argument("--dur", type=float); ap.add_argument("--segments"); ap.add_argument("--plan")
ap.add_argument("--title", default="", help="short opening context line (shown for the first seconds only)"); ap.add_argument("--banner-secs", type=float, default=None)
ap.add_argument("--music"); ap.add_argument("--music-db", default="-21"); ap.add_argument("--music-start", default="0")
ap.add_argument("--mode", default=None); ap.add_argument("--face"); ap.add_argument("--gx", default="0.5")
ap.add_argument("--lang", default="auto"); ap.add_argument("--game-subs", action="store_true"); ap.add_argument("--words-file"); ap.add_argument("--no-captions", action="store_true")
ap.add_argument("--stage", choices=["reframed", "captioned", "final"], default="final"); ap.add_argument("-o", "--out"); ap.add_argument("--work")
a = ap.parse_args(); cfg = C.load()
def secs(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    p = [float(x) for x in str(v).split(":")]; return sum(x * 60 ** i for i, x in enumerate(reversed(p)))
duration = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.src]))
if a.plan: plan = json.load(open(a.plan)); segs = plan["segments"]; a.title = a.title or plan.get("opening_text") or ""
elif a.segments: segs = [{"start": float(x.split(",")[0]), "end": float(x.split(",")[1])} for x in a.segments.split(";")]
elif a.dur is not None: s0 = secs(a.start) or 0.0; segs = [{"start": s0, "end": s0 + a.dur}]
else: sys.exit("give --plan, --segments or --start/--dur")
try: segs = E.validate_segments(segs, duration, cfg)
except E.PlanError as e: sys.exit(f"invalid edit: {e}")
name = os.path.splitext(os.path.basename(a.src))[0]
work = a.work or os.path.join(ROOT, "work"); os.makedirs(work, exist_ok=True); out = a.out or os.path.join(ROOT, "out", f"{name}_short.mp4"); os.makedirs(os.path.dirname(out), exist_ok=True)
def run(*c): print("+", " ".join(map(str, c))); subprocess.check_call([str(x) for x in c])
offs, total = E.segment_offsets(segs); seg_arg = ";".join(f"{g['start']},{g['end']}" for g in segs)
r1 = os.path.join(work, f"{name}_1_reframed.mp4"); layout = os.path.join(work, f"{name}.layout.json")
cmd = [py, f"{HERE}/reframe.py", a.src, r1, "--segments", seg_arg, "--gx", a.gx, "--layout-out", layout]
if a.mode: cmd += ["--mode", a.mode]
if a.face: cmd += ["--face", a.face]
run(*cmd); cur = r1
report = {"source": a.src, "source_duration": round(duration, 3), "segments": segs, "edited_duration": round(total, 3), "layout": layout, "captions_events": None, "words_dropped_at_cuts": 0}
if a.stage != "reframed" and not a.no_captions:
    r2 = os.path.join(work, f"{name}_2_captioned.mp4"); ccmd = [py, f"{HERE}/captions.py", cur, r2, "--title", a.title, "--lang", a.lang, "--layout", layout]
    if a.banner_secs is not None: ccmd += ["--banner-secs", a.banner_secs]
    if a.game_subs: ccmd += ["--game-subs"]
    if a.words_file and os.path.exists(a.words_file):
        src_words = E.clean_words(json.load(open(a.words_file))); mapped, dropped = E.remap_words(src_words, segs)        # SAME segment map as the cut
        mf = os.path.join(work, f"{name}_remapped.words.json"); json.dump(mapped, open(mf, "w"), ensure_ascii=False); ccmd += ["--words-file", mf]; report["words_dropped_at_cuts"] = dropped
        report["selected_words"] = mapped
    run(*ccmd); cur = r2; report["captions_events"] = r2 + ".events.json"
if a.stage == "reframed" or a.stage == "captioned": print("->", cur)
if a.stage == "final":
    if a.music: run(py, f"{HERE}/mix_music.py", cur, a.music, out, "--music-db", a.music_db, "--music-start", a.music_start)
    else: run("ffmpeg", "-y", "-loglevel", "error", "-i", cur, "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out)
    json.dump(report, open(out + ".render.json", "w"), indent=1, ensure_ascii=False); print("DONE ->", out)
