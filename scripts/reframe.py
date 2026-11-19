#!/usr/bin/env python3
"""Reframe a 16:9 stream clip to 1080x1920 and (optionally) cut it into edit segments.
presets (reviewed, all use stable constant crops - no jittery tracking):
  context          full-width 16:9 picture (keeps HUD/minimap), centred in the safe area over a blurred copy of itself        [old name: blur]
  gameplay         gameplay-focused crop (default 9:10) large, captions sit below it                                         [legacy: center]
  gameplay_facecam gameplay panel on top + facecam panel below (detected or --face); falls back to `gameplay` if no facecam    [legacy: stack/auto]
  stack | center | blur | auto   legacy aliases kept so the old manual path still works
--segments "a,b;c,d"   source-relative seconds, concatenated in order (audio gets 30 ms fades at seams) instead of --ss/--t
--layout-out FILE      writes the regions / caption anchor used, so captions and the QA gate know where things are
--gx 0.5|auto          horizontal centre of the gameplay crop (auto = stable motion centroid of the clip)"""
import argparse, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "app"))
import config as C
W, H = 1080, 1920
ap = argparse.ArgumentParser()
ap.add_argument("inp"); ap.add_argument("out")
ap.add_argument("--mode", default=None, help="preset (see above)"); ap.add_argument("--face", help="facecam rect x,y,w,h as 0-1 fractions of the source")
ap.add_argument("--gx", default="0.5"); ap.add_argument("--split", type=float, default=0.58, help="legacy stack only")
ap.add_argument("--ss"); ap.add_argument("--t"); ap.add_argument("--segments"); ap.add_argument("--layout-out"); ap.add_argument("--fps", type=int, default=30)
a = ap.parse_args(); cfg = C.load(); safe = cfg["safe_area"]; fr = cfg["framing"]

def probe(p):
    d = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", p]))["streams"][0]
    return int(d["width"]), int(d["height"])
sw, sh = probe(a.inp)
mode = {"blur": "context", "center": "gameplay", "auto": "gameplay_facecam", "stack": "legacy_stack", None: fr["default"]}.get(a.mode, a.mode)
legacy = mode in ("legacy_stack",)
fallback = None; face = None
if a.face: face = [float(v) for v in a.face.split(",")]

def even(x): return int(x) // 2 * 2
def gx_value():
    if a.gx == "auto":
        import visual
        return visual.motion_center_x(a.inp, 0, 20)
    return float(a.gx)
def crop_x(cw, gx): return even(min(max(sw * gx - cw / 2, 0), sw - cw))
BG = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},scale=270:480,boxblur=12:3,scale={W}:{H},eq=brightness=-0.08")
usable_top, usable_bot = safe["top"], H - safe["bottom"]; fmt = f"fps={a.fps},format=yuv420p[v]"
layout = {"preset": mode, "canvas": {"w": W, "h": H}, "safe": safe, "regions": {"gameplay": None, "facecam": None}, "face_box": None, "caption": {}, "banner": {"y": safe["top"] + 40}}

if mode == "gameplay_facecam" and not face:
    import visual
    d = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.inp]))
    fc_ = visual.detect_facecam(a.inp, d); face = list(fc_) if fc_ else None
    if not face: mode = "gameplay"; fallback = "no facecam detected: used the gameplay preset"; layout["preset"] = mode
if mode == "context":
    fgh = even(W * sh / sw); y = even(min(max((usable_top + usable_bot) / 2 - fgh / 2, 0), H - fgh))
    fc = f"{{SRC}}split[a][b];[a]{BG}[bg];[b]scale={W}:{fgh}[fg];[bg][fg]overlay=0:{y},{fmt}"
    layout["regions"]["gameplay"] = {"x": 0, "y": y, "w": W, "h": fgh}; layout["caption"] = {"y": min(y + fgh + 110, usable_bot - 60)}
elif mode == "gameplay":
    ar = float(fr["gameplay_aspect"]); cw = even(min(sw, sh * ar)); ph = even(W * sh / cw); gx = gx_value(); cx = crop_x(cw, gx); y = even(max(usable_top + 20, 0))
    fc = f"{{SRC}}split[a][b];[a]{BG}[bg];[b]crop={cw}:{sh}:{cx}:0,scale={W}:{ph}[g];[bg][g]overlay=0:{y},{fmt}"
    layout["regions"]["gameplay"] = {"x": 0, "y": y, "w": W, "h": ph}; layout["gx"] = round(cx / max(sw - cw, 1), 3); layout["caption"] = {"y": min(y + ph + 95, usable_bot - 60)}
elif mode == "gameplay_facecam":
    ch = even(fr["facecam_panel_h"]); gh = even(usable_bot + 20 - usable_top - ch); cw = even(min(sw, sh * W / gh)); gh = even(W * sh / cw); gx = gx_value(); cx = crop_x(cw, gx)
    fx, fy, fw, fh = face; y0 = usable_top
    fc = (f"{{SRC}}split=3[a][b][c];[a]{BG}[bg];[b]crop={cw}:{sh}:{cx}:0,scale={W}:{gh}[g];"
          f"[c]crop=iw*{fw}:ih*{fh}:iw*{fx}:ih*{fy},scale={W}:{ch}:force_original_aspect_ratio=increase,crop={W}:{ch}[f];[bg][g]overlay=0:{y0}[t];[t][f]overlay=0:{y0 + gh},{fmt}")
    layout["regions"]["gameplay"] = {"x": 0, "y": y0, "w": W, "h": gh}; layout["regions"]["facecam"] = {"x": 0, "y": y0 + gh, "w": W, "h": ch}
    layout["face_box"] = {"x": int(W * 0.22), "y": y0 + gh + int(ch * 0.10), "w": int(W * 0.56), "h": int(ch * 0.85)}       # the face sits in the middle of the cam panel
    layout["caption"] = {"y": y0 + gh - 95}                                                                                 # bottom of the gameplay panel, clear of the face
elif mode == "legacy_stack":
    if not face: sys.exit("stack mode needs --face x,y,w,h")
    fx, fy, fw, fh = face; gh = even(H * a.split); ch = H - gh; gx = gx_value()
    fc = (f"{{SRC}}split[g][f];[g]scale=-2:{gh}:force_original_aspect_ratio=increase,crop={W}:{gh}:'min(max(iw*{gx}-{W}/2,0),iw-{W})':0[top];"
          f"[f]crop=iw*{fw}:ih*{fh}:iw*{fx}:ih*{fy},scale={W}:{ch}:force_original_aspect_ratio=increase,crop={W}:{ch}[bot];[top][bot]vstack,{fmt}")
    layout["regions"]["gameplay"] = {"x": 0, "y": 0, "w": W, "h": gh}; layout["regions"]["facecam"] = {"x": 0, "y": gh, "w": W, "h": ch}; layout["caption"] = {"y": gh - 95}
else: sys.exit(f"unknown preset {mode!r}")
layout["caption"]["max_width"] = W - safe["left"] - safe["right"]; layout["caption"]["x_center"] = safe["left"] + layout["caption"]["max_width"] / 2
layout["fallback_reason"] = fallback
if a.layout_out: json.dump(layout, open(a.layout_out, "w"), indent=1)

cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stats"]
if a.segments:
    segs = [tuple(float(v) for v in s.split(",")) for s in a.segments.split(";")]; parts, vs, as_ = [], [], []
    for i, (s, e) in enumerate(segs):
        if not e > s: sys.exit(f"bad segment {s},{e}")
        f = min(0.03, (e - s) / 4)
        parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}];[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS,afade=t=in:d={f},afade=t=out:st={e - s - f:.3f}:d={f}[a{i}]")
        vs.append(f"[v{i}][a{i}]")
    parts.append("".join(vs) + f"concat=n={len(segs)}:v=1:a=1[src][aout]"); pre = ";".join(parts) + ";"
    fc = pre + fc.replace("{SRC}", "[src]"); amap = "[aout]"; cmd += ["-i", a.inp]
else:
    fc = "[0:v]null[src];" + fc.replace("{SRC}", "[src]"); amap = "0:a?"
    if a.ss: cmd += ["-ss", a.ss]
    cmd += ["-i", a.inp]
    if a.t: cmd += ["-t", a.t]
cmd += ["-filter_complex", fc, "-map", "[v]", "-map", amap, "-c:v", "libx264", "-crf", "16", "-preset", "veryfast", "-c:a", "aac", "-b:a", "192k", a.out]
sys.exit(subprocess.call(cmd))
