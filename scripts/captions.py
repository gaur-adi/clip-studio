#!/usr/bin/env python3
"""Word-timed captions with whisper.cpp (offline, free) burned in with Pillow PNG overlays
(this Homebrew ffmpeg has no libass/drawtext, so we don't use the subtitles filter).
Also writes <out>.srt (import into Kdenlive: Project > Subtitles) and <out>.words.json.
  captions.py in.mp4 out.mp4 [--title "your own commentary"] [--lang en] [--srt-only]
"""
import argparse, json, os, re, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
W, H = 1080, 1920
ap = argparse.ArgumentParser()
ap.add_argument("inp"); ap.add_argument("out")
def _model():
    for m in (os.environ.get("WHISPER_MODEL"), os.path.join(ROOT, "models", "ggml-large-v3-turbo.bin"), os.path.join(ROOT, "models", "ggml-small.bin"), os.path.join(ROOT, "models", "ggml-base.en.bin")):
        if m and os.path.exists(m): return m
    return os.path.join(ROOT, "models", "ggml-base.en.bin")
ap.add_argument("--model", default=_model())
ap.add_argument("--title", default="", help="your own commentary/context line shown at top the whole clip")
ap.add_argument("--words", type=int, default=3, help="max words per caption chunk")
ap.add_argument("--y", type=float, default=0.70, help="caption vertical position 0-1")
ap.add_argument("--size", type=int, default=92)
ap.add_argument("--srt-only", action="store_true")
ap.add_argument("--layout", help="layout json written by reframe.py (caption anchor, face box)")
ap.add_argument("--banner-secs", type=float, default=None, help="show the opening context line only for this many seconds (default from config; <0 = whole video, 0 = never)")
ap.add_argument("--words-file", help="reuse the word list already transcribed for the AI score (live moments)")
ap.add_argument("--game-subs", action="store_true", help="also caption the game's own English dialogue (light-blue), not only the streamer")
ap.add_argument("--lang", default=os.environ.get("WHISPER_LANG", "auto"), help="auto | hi | en ... (force Hindi on Hinglish streams)")
ap.add_argument("--reuse-words", action="store_true", help="skip whisper if <out>.words.json exists (e.g. after hand-editing it)")
a = ap.parse_args()
FONT = next((p for p in [os.path.join(ROOT, "assets", "fonts", "Anton-Regular.ttf"), "/System/Library/Fonts/Supplemental/Impact.ttf",
                         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"] if os.path.exists(p)), None)
if not FONT: sys.exit("no usable font found (assets/fonts/Anton-Regular.ttf missing)")
tmp = tempfile.mkdtemp(prefix="caps_", dir=os.path.join(ROOT, "work"))
wjson = a.out + ".words.json"

def asr_words(wav):
    """Qwen3-ASR service (this Mac, auto language incl. Hindi<->English switching, word timestamps). None -> use whisper.cpp"""
    import urllib.request
    url = os.environ.get("ASR_URL", "http://127.0.0.1:8770")
    try:
        if not json.loads(urllib.request.urlopen(url + "/health", timeout=1).read()).get("ready"): return None
        req = urllib.request.Request(url + "/transcribe", json.dumps({"path": wav, "language": None}).encode(), {"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=300).read()); return d.get("words") or None
    except Exception: return None

def transcribe():
    wav = os.path.join(tmp, "a.wav")
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", a.inp, "-vn", "-ac", "1", "-ar", "16000", wav])
    qw = asr_words(wav)
    if qw: return [x for x in qw if x["w"].strip() and x["e"] >= x["s"]]
    subprocess.check_call(["whisper-cli", "-m", a.model, "-f", wav, "-ml", "1", "-sow", "-ojf", "-of", os.path.join(tmp, "w"), "-np", "-mc", "0", "-nth", "0.6"] + (["-l", a.lang] if ".en." not in a.model else []),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    d = json.loads(open(os.path.join(tmp, "w.json"), encoding="utf-8", errors="surrogateescape").read())   # whisper can split a Devanagari letter across tokens: keep raw bytes, re-join below
    words = []
    gwords = []
    if a.game_subs and ".en." not in a.model and a.lang not in ("en",):
        subprocess.run(["whisper-cli", "-m", a.model, "-f", wav, "-ml", "1", "-sow", "-ojf", "-of", os.path.join(tmp, "g"), "-np", "-mc", "0", "-nth", "0.6", "-l", "en"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for sg in json.loads(open(os.path.join(tmp, "g.json"), encoding="utf-8", errors="surrogateescape").read())["transcription"]:
                t_ = sg["text"]
                if re.fullmatch(r"\s*[\[\(].*[\]\)]\s*", t_) or not t_.strip() or not re.search(r"[A-Za-z]", t_): continue
                if t_.startswith(" ") or not gwords: gwords.append({"w": t_.strip(), "s": sg["offsets"]["from"]/1000, "e": sg["offsets"]["to"]/1000, "g": True})
                else: gwords[-1]["w"] += t_.strip(); gwords[-1]["e"] = sg["offsets"]["to"]/1000
        except Exception: pass
    skip = False   # drop [MUSIC PLAYING] / (laughs) style annotations, which -sow splits into several tokens
    for s in d["transcription"]:
        t = s["text"]
        if "[" in t or "(" in t: skip = True
        if skip or not t.strip():
            if "]" in t or ")" in t: skip = False
            continue
        if t.strip() in ("-", "--", "\u2013"): continue
        st, en = s["offsets"]["from"]/1000, s["offsets"]["to"]/1000
        if t.startswith(" ") or not words: words.append({"w": t.strip(), "s": st, "e": en})
        else: words[-1]["w"] += t.strip(); words[-1]["e"] = en
    # keep the game's English words only where the streamer is NOT speaking
    for g in gwords:
        if not any(min(g["e"], w["e"]) - max(g["s"], w["s"]) > 0.05 for w in words): words.append(g)
    words.sort(key=lambda w: w["s"])
    for w in words: w["w"] = w["w"].encode("utf-8", "surrogateescape").decode("utf-8", "replace").replace("\ufffd", "")      # halves of a split letter are joined; any truly broken byte is dropped
    return words

PROF = re.compile(r"(fuck|shit|bitch|cunt|dick|asshole|nigg|retard|madarchod|bhenchod|behenchod|chutiya|gaand|harami|मादरचोद|भोसड़ी|भोसडी|चूतिया|बहनचोद|गांड|हरामी)\w*", re.I)
def mask(t):   # keep first + last letter: f*****s  (ad-friendly captions)
    return PROF.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 2) + m.group(0)[-1] if len(m.group(0)) > 2 else m.group(0), t)
def dehallucinate(ws):   # whisper sometimes loops a word/phrase over music or silence: keep at most 2 repeats in a row (phrases of 1-8 words)
    out = list(ws)
    for n in range(1, 9):
        i = 0
        while i + 3 * n <= len(out):
            seq = [x["w"] for x in out[i:i + n]]
            if [x["w"] for x in out[i + n:i + 2 * n]] == seq and [x["w"] for x in out[i + 2 * n:i + 3 * n]] == seq:
                del out[i + 2 * n:i + 3 * n]          # drop the 3rd repeat (and keep checking from the same place)
            else: i += 1
    return out
if a.words_file and os.path.exists(a.words_file): words = dehallucinate(json.load(open(a.words_file))); json.dump(words, open(wjson, "w"), indent=1)
elif a.reuse_words and os.path.exists(wjson): words = json.load(open(wjson))
else: words = dehallucinate(transcribe()); json.dump(words, open(wjson, "w"), indent=1)
for w_ in words: w_["w"] = mask(w_["w"])
print(f"{len(words)} words", file=sys.stderr)

# chunks of <=N words, split on sentence punctuation or pauses
chunks, cur = [], []
for w in words:
    if cur and (len(cur) >= a.words or w["s"] - cur[-1]["e"] > 0.7): chunks.append(cur); cur = []
    cur.append(w)
    if re.search(r"[.!?।]$", w["w"]): chunks.append(cur); cur = []
if cur: chunks.append(cur)

def ts(t): return f"{int(t//3600):02d}:{int(t%3600//60):02d}:{int(t%60):02d},{int(t*1000)%1000:03d}"
with open(a.out + ".srt", "w") as f:
    for i, c in enumerate(chunks, 1):
        f.write(f"{i}\n{ts(c[0]['s'])} --> {ts(c[-1]['e'])}\n{' '.join(x['w'] for x in c)}\n\n")
if a.srt_only: sys.exit(0)

sys.path.insert(0, os.path.join(ROOT, "app")); import config as C
cfg = C.load(); safe = cfg["safe_area"]
layout = json.load(open(a.layout)) if a.layout and os.path.exists(a.layout) else None
CAP_Y = (layout or {}).get("caption", {}).get("y") or int(H * a.y); MAX_W = (layout or {}).get("caption", {}).get("max_width") or (W - safe["left"] - safe["right"])
X_C = (layout or {}).get("caption", {}).get("x_center") or (safe["left"] + MAX_W / 2); FACE = (layout or {}).get("face_box")
BANNER_S = cfg["framing"]["banner_secs"] if a.banner_secs is None else a.banner_secs
FONT_HI = os.path.join(ROOT, "assets", "fonts", "Hind-Bold.ttf")
DEV = re.compile(r"[\u0900-\u097F]")
_fc = {}
def fnt(text, size):
    hi = bool(DEV.search(text)) and os.path.exists(FONT_HI); size = int(size); k = (hi, size)
    if k not in _fc: _fc[k] = ImageFont.truetype(FONT_HI, int(size * 1.15), layout_engine=ImageFont.Layout.RAQM) if hi else ImageFont.truetype(FONT, size)
    return _fc[k]
_probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
def tw(t, size): return _probe.textlength(t, font=fnt(t, size))

def wrap(texts, max_w, size, max_lines=2):
    """greedy wrap by MEASURED width. A word wider than the line shrinks the font (down to 44 px), then is split by characters. -> (lines of text, size)"""
    sp_ = lambda sz: tw(" ", sz)
    while True:
        lines, cur, w_ = [], [], 0.0; fits = True
        for t in texts:
            wt = tw(t, size)
            if wt > max_w: fits = False; break
            add = wt + (sp_(size) if cur else 0)
            if cur and w_ + add > max_w: lines.append(cur); cur, w_ = [t], wt
            else: cur.append(t); w_ += add
        if cur: lines.append(cur)
        if fits and len(lines) <= max_lines: return [" ".join(l) for l in lines], size
        if size > 44: size *= 0.9; continue
        out, cur = [], ""                                                       # last resort: break long words by characters
        for t in texts:
            for ch in t:
                if tw(cur + ch, size) > max_w and cur: out.append(cur); cur = ch
                else: cur += ch
            cur += " "
        out.append(cur.strip()); return out[:max_lines + 1], size

dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.inp]))
words = [dict(w_, e=min(w_["e"], dur)) for w_ in words if w_["s"] < dur - 0.05]             # nothing past the end of the edit
chunks, cur = [], []
for w in words:
    if cur and (len(cur) >= a.words or w["s"] - cur[-1]["e"] > 0.7): chunks.append(cur); cur = []
    cur.append(w)
    if re.search(r"[.!?।]$", w["w"]): chunks.append(cur); cur = []
if cur: chunks.append(cur)

def draw_caption(d, chunk, active):
    """-> bounding box [x0,y0,x1,y1]. Words are measured, wrapped inside the safe width, centred on the safe-area centre, and pushed off the face if needed."""
    texts = [(plain(x["w"]) or x["w"]).upper() for x in chunk]; idx = []; k = 0
    lines, size = wrap(texts, MAX_W, a.size)
    # map each rendered line back to word indices (only possible when no char-splitting happened)
    pos = 0
    for ln in lines:
        n = len(ln.split()); idx.append(list(range(pos, min(pos + n, len(texts))))); pos += n
    lh = size * 1.28; y = CAP_Y - (len(lines) - 1) * lh / 2; sw_ = max(4, int(size * 0.1)); boxes = []
    if FACE:                                                                       # keep the whole block clear of the facecam
        top = y - lh / 2; bot = y + (len(lines) - 1) * lh + lh / 2
        if not (bot < FACE["y"] or top > FACE["y"] + FACE["h"]) and top - 0 > 0: y -= (bot - FACE["y"]) + 14
    ext = [d.textbbox((0, 0), t, font=fnt(t, size), anchor="lm", stroke_width=sw_) for ln in lines for t in ln.split()]      # real glyph extents (ascenders, matras, stroke)
    up, dn = (-min(b[1] for b in ext), max(b[3] for b in ext)) if ext else (lh / 2, lh / 2)
    lo_lim, hi_lim = safe["top"] + 4, H - safe["bottom"] - 4                      # the whole block must stay inside the phone-safe band
    bot = y + (len(lines) - 1) * lh + dn
    if bot > hi_lim: y -= bot - hi_lim
    if y - up < lo_lim: y += lo_lim - (y - up)
    for li, ln in enumerate(lines):
        widths = [tw(t, size) for t in ln.split()]; sp = tw(" ", size); total = sum(widths) + sp * (len(widths) - 1)
        x = max(X_C - total / 2, safe["left"]); yy = y + li * lh
        for wi, t in enumerate(ln.split()):
            gi = idx[li][wi] if li < len(idx) and wi < len(idx[li]) else -1
            col = (255, 224, 0, 255) if gi == active else ((150, 215, 255, 255) if gi >= 0 and chunk[gi].get("g") else (255, 255, 255, 255))
            d.text((x, yy), t, font=fnt(t, size), fill=col, anchor="lm", stroke_width=sw_, stroke_fill=(0, 0, 0, 255))
            boxes.append(d.textbbox((x, yy), t, font=fnt(t, size), anchor="lm", stroke_width=sw_)); x += widths[wi] + sp
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]

EMOJI = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F\u200D\u2B50\u2B06\u2934\u3030]+")
def plain(t): return re.sub(r"\s+", " ", EMOJI.sub("", t)).strip()      # burned-in fonts have no emoji glyphs (they would print as empty boxes); the title keeps them

def draw_banner(d):
    """short opening context line: wrapped by measured width, inside the safe area, top region only"""
    texts = plain(a.title).split(); lines, size = wrap(texts, MAX_W - 40, 56, 3); lh = size * 1.3; h = len(lines) * lh + 30
    y0 = (layout or {}).get("banner", {}).get("y") or safe["top"] + 40; x0 = safe["left"]; x1 = safe["left"] + MAX_W
    d.rounded_rectangle((x0, y0, x1, y0 + h), 26, fill=(0, 0, 0, 175))
    for i, l in enumerate(lines): d.text(((x0 + x1) / 2, y0 + 15 + lh * i + lh / 2), l, font=fnt(l, size), fill="white", anchor="mm")
    return [x0, y0, x1, y0 + h]

def render(chunk, active, with_banner, path):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im); boxes = {}
    if with_banner and plain(a.title): boxes["banner"] = draw_banner(d)
    if chunk: boxes["caption"] = draw_caption(d, chunk, active)
    im.save(path); return boxes

frames, ev_log, t, n = [], [], 0.0, 0                                          # frames: (png, duration); ev_log: caption/banner events with boxes
blank = os.path.join(tmp, "blank.png"); render(None, -1, False, blank)
banner_png = os.path.join(tmp, "banner.png"); bb = render(None, -1, True, banner_png) if (plain(a.title) and BANNER_S != 0) else None
B = dur if BANNER_S < 0 else min(BANNER_S, dur)
def push(png, st, en, boxes, kind):
    global t
    en = min(en, dur)
    if en - st < 0.03: return
    if st > t + 1e-3:
        if bb and t < B < st: frames.append((banner_png, B - t)); frames.append((blank, st - B))
        else: frames.append((blank if t >= B or not bb else banner_png, st - t))
    frames.append((png, en - st)); t = en
    if kind == "caption": ev_log.append({"start": round(st, 3), "end": round(en, 3), "kind": "caption", "box": [round(v, 1) for v in boxes["caption"]]})
# banner-only stretch before / between captions is handled by the blank frames above; captions carry the banner while t < B
for c in chunks:
    for i, w in enumerate(c):
        st = max(w["s"] if i else w["s"], t); en = c[i + 1]["s"] if i + 1 < len(c) else w["e"] + 0.15
        en = max(en, st + 0.04)
        for (a0, a1) in ([(st, min(en, B)), (max(st, B), en)] if st < B < en and bb else [(st, en)]):
            if a1 - a0 < 0.03: continue
            p = os.path.join(tmp, f"c{n}.png"); n += 1; bx = render(c, i, bool(bb) and a0 < B, p); push(p, a0, a1, bx, "caption")
if t < dur:
    if bb and t < B < dur: frames.append((banner_png, B - t)); frames.append((blank, dur - B))
    else: frames.append((blank if t >= B or not bb else banner_png, dur - t))
if bb and B > 0:                                                               # the banner event itself (for the QA gate)
    ev_log.insert(0, {"start": 0.0, "end": round(B, 3), "kind": "banner_ok", "box": [round(v, 1) for v in bb["banner"]]})
# a banner that should outlast the first caption: splice banner frames over the leading stretch
lst = os.path.join(tmp, "list.txt")
with open(lst, "w") as f:
    for p, d_ in frames: f.write(f"file '{p}'\nduration {max(d_, 0.02):.3f}\n")
    f.write(f"file '{frames[-1][0]}'\n")
fc = "[1:v]fps=30,format=rgba[ov];[0:v][ov]overlay=0:0:eof_action=pass,format=yuv420p[v]"
subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", a.inp, "-f", "concat", "-safe", "0", "-i", lst,
    "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "16", "-preset", "veryfast", "-c:a", "copy", "-t", f"{dur:.3f}", a.out])
json.dump({"duration": dur, "banner_secs": B if bb else 0, "events": ev_log, "layout": a.layout}, open(a.out + ".events.json", "w"), indent=1)
import shutil; shutil.rmtree(tmp, ignore_errors=True)
