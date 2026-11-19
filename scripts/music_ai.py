"""AI music picker. Profiles every track (tempo, energy, brightness, best section) and, per clip, chooses the track + start offset.
Heuristic matching always works; if an Ollama LLM is reachable (OLLAMA_HOST) it makes the final call from the shortlist.
  music_ai.py build            -> (re)profile music/**/*.mp3 into music/library.json
  music_ai.py pick DURATION MOTION "transcript"   -> demo pick"""
import glob, json, os, random, subprocess, sys, urllib.request, urllib.error
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); MUSIC = os.path.join(ROOT, "music"); LIB = os.path.join(MUSIC, "library.json")
SR = 11025

def _pcm(path):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768

def profile(path):
    x = _pcm(path); n = len(x) // SR
    if n < 5: return None
    sec = x[:n * SR].reshape(n, SR); db = 20 * np.log10(np.sqrt((sec ** 2).mean(1)) + 1e-6)
    hop = 256; fr = x[:len(x) // hop * hop].reshape(-1, hop); e = np.sqrt((fr ** 2).mean(1)); on = np.maximum(np.diff(e), 0); on -= on.mean()
    ac = np.correlate(on, on, "full")[len(on) - 1:]; best, bs = 0, -1
    for bpm in range(80, 181):
        lag = int(round(60 / bpm * SR / hop)); sc = ac[lag] + .5 * ac[min(lag * 2, len(ac) - 1)]
        if sc > bs: best, bs = bpm, sc
    lag = int(round(60 / best * SR / hop)); phase = int(np.argmax([on[ph::lag].sum() for ph in range(lag)])) * hop / SR   # where beats fall
    cents = []
    for s in range(0, n, 4):
        sp = np.abs(np.fft.rfft(sec[s] * np.hanning(SR))); fq = np.fft.rfftfreq(SR, 1 / SR); cents.append(float((sp * fq).sum() / (sp.sum() + 1e-9)))
    return {"bpm": int(best), "energy_db": round(float(db.mean()), 1), "dyn": round(float(db.std()), 1), "bright_hz": int(np.mean(cents)),
            "beat_s": round(60 / best, 4), "beat_phase": round(float(phase), 3), "seconds": int(n), "db": [round(float(v), 1) for v in db[:400]]}

def build(meta_defaults=None):
    old = {t["file"]: t for t in json.load(open(LIB))} if os.path.exists(LIB) else {}
    out = []
    for p in sorted(glob.glob(os.path.join(MUSIC, "**", "*.mp3"), recursive=True)):
        rel = os.path.relpath(p, MUSIC)
        if "test_" in rel: continue
        t = dict(old.get(rel, {})); pr = profile(p)
        if not pr: continue
        declared = t.get("bpm") if t.get("style") == "drift phonk (synthesised)" else None   # our own loops: trust the known tempo
        t.update(pr); t["file"] = rel
        if declared: t["bpm"] = declared
        synth = os.path.basename(rel).startswith("phonk_") and "/" not in rel
        t.setdefault("source", "synthesised locally (original)" if synth else "Pixabay phonk search, downloaded 2026-11-18 (Pixabay Content License)")
        t.setdefault("claim_free", bool(synth))        # Pixabay tracks can be registered in YouTube Content ID -> claims possible
        out.append(t)
    med = sorted(t["energy_db"] for t in out)[len(out) // 2] if out else 0
    for t in out: t["energy"] = "high" if t["energy_db"] >= med else "mid"      # relative to the library
    json.dump(out, open(LIB, "w"), indent=1); return out

def _best_start(t, L):
    """loudest L-second section, snapped to a bar line (4 beats) so the music begins on the downbeat; never runs past the track end"""
    db = np.array(t.get("db") or []); L = int(L)
    if len(db) <= L: return 0.0
    win = np.convolve(db, np.ones(L) / L, mode="valid"); st = float(np.argmax(win))
    bar = 4 * t.get("beat_s", 0.5); ph = t.get("beat_phase", 0.0)
    if bar > 0.5:
        st = ph + round((st - ph) / bar) * bar
        while st + L > t["seconds"] and st - bar >= 0: st -= bar
    return round(max(st, 0.0), 2)

def heuristic(lib, clip, recent):
    es = sorted(t["energy_db"] for t in lib); rank = lambda v: es.index(v) / max(len(es) - 1, 1)
    want = min(clip.get("motion", 10) / 25, 1) * .6 + min(clip.get("hype", .3), 1) * .4
    sc = []
    for t in lib:
        s = -abs(rank(t["energy_db"]) - want) - .15 * abs((t["bpm"] - (150 if want > .5 else 130)) / 30)
        if t["file"] in recent: s -= .5
        sc.append((s + random.random() * .05, t))
    return [t for _, t in sorted(sc, key=lambda z: -z[0])]

def pick(clip, claim_free_only=False, recent=(), log=lambda m: None, use_llm=True):
    lib = json.load(open(LIB)) if os.path.exists(LIB) else build()
    if claim_free_only: lib = [t for t in lib if t.get("claim_free")] or lib
    need = clip.get("dur", 40) + 2
    longer = [t for t in lib if t["seconds"] >= need]; lib = longer or lib     # avoid tracks that would have to loop
    short = heuristic(lib, clip, recent)[:6]; choice = short[0]; why = "closest energy/tempo match"
    # music AI runs on THIS Mac (its own small model), so it never waits behind the laptop's judging queue
    host = os.environ.get("MUSIC_OLLAMA_HOST", "http://127.0.0.1:11434"); model = os.environ.get("MUSIC_OLLAMA_MODEL", "qwen3:4b")
    if len(short) > 1 and use_llm:
        tr = [{"id": i, "bpm": t["bpm"], "energy": "high" if t["energy"] == "high" else "medium", "brightness": "bright" if t["bright_hz"] > 2500 else "dark",
               "dynamic": "punchy" if t["dyn"] > 6 else "steady", "source": "original" if t.get("claim_free") else "library"} for i, t in enumerate(short)]
        prompt = ("Choose the best phonk background track for a ~%ds gaming Short that plays UNDER speech at low volume. Clip: motion=%s/25, mood hints=%s, "
                  "transcript=\"%s\". Prefer energy that matches the action, but not so busy it fights the voice. Tracks: %s. Reply ONLY JSON, reason max 12 words: {\"id\":0,\"reason\":\"\"}") % (
                  int(clip.get("dur", 40)), round(clip.get("motion", 10), 1), clip.get("mood", ""), (clip.get("text") or "")[:300], json.dumps(tr))
        for think in (False, None):
            body = {"model": model, "stream": False, "format": "json", "options": {"temperature": .3, "num_predict": 300}, "messages": [{"role": "user", "content": prompt}]}
            if think is not None: body["think"] = think
            try:
                req = urllib.request.Request(host + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
                raw = json.loads(urllib.request.urlopen(req, timeout=40).read())["message"]["content"]
                try: d = json.loads(raw)
                except Exception:   # truncated reply: still take the id
                    import re as _re; m_ = _re.search(r'"id"\s*:\s*(\d+)', raw); d = {"id": int(m_.group(1)), "reason": (_re.search(r'"reason"\s*:\s*"([^"]*)', raw) or [0, ""])[1]}
                choice = short[int(d["id"])]; why = "AI (Mac): " + str(d.get("reason", ""))[:120]; break
            except urllib.error.HTTPError:
                continue
            except Exception as e:
                log(f"(music AI on the Mac not reachable, using the fast matcher: {str(e)[:50]})"); break
    start = _best_start(choice, clip.get("dur", 40))
    return {"file": os.path.join(MUSIC, choice["file"]), "rel": choice["file"], "start": start, "why": why, "bpm": choice["bpm"], "claim_free": choice.get("claim_free", False)}

if __name__ == "__main__":
    if sys.argv[1] == "build":
        for t in build(): print(t["file"], t["bpm"], t["energy_db"], t["energy"], t["bright_hz"], t["seconds"], "claim_free" if t.get("claim_free") else "")
    else:
        print(pick({"dur": float(sys.argv[2]), "motion": float(sys.argv[3]), "text": sys.argv[4]}))
