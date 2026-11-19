#!/usr/bin/env python3
"""Local speech-recognition service (Qwen3-ASR-1.7B + forced aligner) on this Mac's GPU (MPS). Loads once, then serves:
   GET /health                      -> {"ready": true}
   POST /transcribe {path, language?: null|"Hindi"|"English"|...}  -> {language, text, words:[{w,s,e}]}
Run with the .venv-asr interpreter:  .venv-asr/bin/python scripts/asr_server.py   (port 8770, localhost only)"""
import json, os, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import torch
from qwen_asr import Qwen3ASRModel
PORT = int(os.environ.get("ASR_PORT", 8770)); LOCK = threading.Lock(); M = {"model": None}
def load():
    dev = "mps" if torch.backends.mps.is_available() else "cpu"; dt = torch.float16 if dev == "mps" else torch.float32
    M["model"] = Qwen3ASRModel.from_pretrained("Qwen/Qwen3-ASR-1.7B", dtype=dt, device_map=dev, max_new_tokens=768,
        forced_aligner="Qwen/Qwen3-ForcedAligner-0.6B", forced_aligner_kwargs=dict(dtype=dt, device_map=dev))
    print("ASR ready on", dev, flush=True)
import numpy as np, wave
SR = 16000; WIN = 8.0
def read_wav(path):
    w = wave.open(path); n = w.getnframes(); sr = w.getframerate(); x = np.frombuffer(w.readframes(n), np.int16).astype(np.float32) / 32768; ch = w.getnchannels(); w.close()
    if ch > 1: x = x.reshape(-1, ch).mean(1)
    return x, sr
def voiced_span(x, sr):
    """first/last moment of real sound in this window (so words are never spread over leading/trailing silence)"""
    fr = int(0.05 * sr); n = len(x) // fr
    if n < 2: return 0.0, len(x) / sr
    e = np.sqrt((x[:n * fr].reshape(n, fr) ** 2).mean(1)); thr = max(np.median(e), 0.25 * np.percentile(e, 90), 0.003); on = np.where(e > thr)[0]
    if len(on) == 0: return 0.0, len(x) / sr
    return max(on[0] * 0.05 - 0.05, 0.0), min((on[-1] + 1) * 0.05 + 0.05, len(x) / sr)
def cut_points(x, sr):
    """window boundaries about every WIN seconds, each moved to the quietest spot within +-1.5 s so words are not cut in half"""
    total = len(x) / sr; cuts = [0.0]; t = WIN
    while t < total - 3.0:
        a, b = int((t - 1.5) * sr), int(min(t + 1.5, total) * sr); fr = int(0.05 * sr); seg = x[a:b][:len(x[a:b]) // fr * fr].reshape(-1, fr)
        k = int(np.argmin(np.sqrt((seg ** 2).mean(1)))) if len(seg) else 0; c = (a + k * fr + fr // 2) / sr; cuts.append(c); t = c + WIN
    cuts.append(total); return cuts
def window_words(r, dur, x, sr):
    toks = r.text.split()
    if not toks: return []
    v0, v1 = voiced_span(x, sr); ts = [(float(t.start_time), float(t.end_time)) for t in (r.time_stamps or [])]
    ok = len(ts) == len(toks) and all(b >= a for a, b in ts) and all(ts[i][0] >= ts[i - 1][0] for i in range(1, len(ts)))
    ok = ok and sum(1 for a, b in ts if b - a < 0.01) <= 0.25 * len(ts) and (ts[-1][1] - ts[0][0]) >= 0.6 * (v1 - v0) if ok else False
    if ok: pairs = ts                                                       # the aligner output looks sane for this window: use it
    else:                                                                   # otherwise spread the words over the voiced part by length
        tot = sum(len(t) for t in toks) or 1; pairs = []; c = v0
        for t in toks: d = (v1 - v0) * len(t) / tot; pairs.append((c, c + d)); c += d
    return [{"w": t, "s": a, "e": b} for t, (a, b) in zip(toks, pairs)]
ALLOWED = set((os.environ.get("ASR_LANGS") or "Hindi,English").split(","))      # languages we expect on these streams
def _run(seg, sr, language):
    with LOCK:
        try: return M["model"].transcribe(audio=(seg, sr), language=language, return_time_stamps=True)[0]
        except Exception as e:
            print("aligner failed:", str(e)[:120], flush=True); return M["model"].transcribe(audio=(seg, sr), language=language)[0]
def transcribe_file(path, language):
    x, sr = read_wav(path); cuts = cut_points(x, sr); parts = []
    for a, b in zip(cuts, cuts[1:]):
        seg = x[int(a * sr):int(b * sr)]
        if len(seg) < 0.4 * sr: continue
        parts.append([a, b, seg, _run(seg, sr, language)])
    if language is None:       # auto-detect per window, but a quiet/noisy window can be misdetected (e.g. Malay): redo it in the clip's main language
        cnt = {}
        for a, b, seg, r in parts:
            if r.language in ALLOWED: cnt[r.language] = cnt.get(r.language, 0) + len(r.text)
        dom = max(cnt, key=cnt.get) if cnt else "English"
        for p_ in parts:
            if p_[3].language not in ALLOWED: p_[3] = _run(p_[2], sr, dom)
    words, texts, lang = [], [], None
    for a, b, seg, r in parts:
        lang = lang or r.language; texts.append(r.text)
        for w in window_words(r, b - a, seg, sr): w["s"] = round(a + w["s"], 3); w["e"] = round(a + w["e"], 3); words.append(w)
    return {"language": lang, "text": " ".join(texts), "words": words}

class H(BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def send(s, o, c=200):
        b = json.dumps(o, ensure_ascii=False).encode(); s.send_response(c); s.send_header("Content-Type", "application/json"); s.send_header("Content-Length", str(len(b))); s.end_headers(); s.wfile.write(b)
    def do_GET(s): s.send({"ready": M["model"] is not None})
    def do_POST(s):
        if M["model"] is None: return s.send({"error": "loading"}, 503)
        p = json.loads(s.rfile.read(int(s.headers.get("Content-Length") or 0)))
        try: s.send(transcribe_file(p["path"], p.get("language")))
        except Exception as e: s.send({"error": str(e)[:200]}, 500)
if __name__ == "__main__":
    threading.Thread(target=load, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
