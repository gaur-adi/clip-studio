"""Live AI moment detection with a ROLLING BUFFER (no full recording).
streamlink -> ffmpeg 10 s segments in work/live_buf_*/ ; only the last ~4 min is kept, older segments are deleted.
Every segment is scored (audio loudness jump + visual motion + Twitch chat burst); when a spike appears the
surrounding ~35 s is cut out of the buffer into work/live_moments/ and judged by whisper + the LLM.
Only these moment clips persist; the buffer is wiped when you stop."""
import glob, json, os, shutil, subprocess, threading, time
import numpy as np
import analyze as A
import visual

class Watcher:
    def __init__(s, url, name, work, sens=3.0, buf=240, chat_path=None, on_judged=None, lang=None):
        s.lang = lang; s.id = name; s.url = url; s.sens = sens; s.buf = buf; s.chat_path = chat_path
        s.dir = os.path.join(work, f"live_buf_{name}"); s.mdir = os.path.join(work, "live_moments")
        shutil.rmtree(s.dir, ignore_errors=True); os.makedirs(s.dir); os.makedirs(s.mdir, exist_ok=True)
        s.stop = threading.Event(); s.moments = []; s.pending = []; s.segs = []; s.seen = set()
        s.t = []; s.db = []; s.mo = []; s.chat = {}; s.chat_pos = 0; s.last_moment = 0; s.last_score = 0.0; s.status = "starting"; s.err = None
        s.procs = []; s.on_judged = on_judged; s.tl = None

    def start(s):
        s.run = 0; s.restarts = 0
        s._spawn()
        threading.Thread(target=s._run, daemon=True).start()

    def _spawn(s):
        """(re)start streamlink -> ffmpeg segmenter; each run has its own filename prefix so a reconnect never overwrites segments"""
        args = ["streamlink", "-O", s.url, "best"]
        if "twitch" in s.url: args.insert(1, "--twitch-disable-ads")
        p1 = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        p2 = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-c", "copy", "-f", "segment", "-segment_time", "10",
                               "-segment_format", "mpegts", "-reset_timestamps", "1", os.path.join(s.dir, f"s{s.run:02d}_%06d.ts")],
                              stdin=p1.stdout, stderr=subprocess.DEVNULL)
        p1.stdout.close(); s.procs = [p1, p2]; s.run += 1; s.spawned = time.time()

    def end(s):
        s.stop.set()
        for p in s.procs:
            try: p.terminate()
            except Exception: pass
        time.sleep(1); shutil.rmtree(s.dir, ignore_errors=True)   # wipe the buffer; only moment clips stay
        s.status = "stopped"

    # ---- chat (anonymous Twitch log written by chat_spikes) ----
    def _tail_chat(s):
        if not s.chat_path or not os.path.exists(s.chat_path): return
        with open(s.chat_path) as f:
            f.seek(s.chat_pos)
            for line in f:
                if not line.endswith("\n"): break
                try: d = json.loads(line)
                except Exception: continue
                if "t" in d: s.chat[int(d["t"])] = s.chat.get(int(d["t"]), 0) + 1
            s.chat_pos = f.tell()

    def _chat_rate(s, t):   # messages in the 5 s ending at t
        return sum(s.chat.get(int(t) - k, 0) for k in range(5))

    # ---- main loop ----
    def _run(s):
        try:
            while not s.stop.is_set():
                time.sleep(4)
                files = sorted(glob.glob(os.path.join(s.dir, "s*_*.ts")))
                if len(files) >= 1: s.status = "watching"
                new = [f for f in files[:-1] if f not in s.seen]
                if new and s.tl is None:   # first batch = already-played video Twitch/YouTube hands us at start: anchor timeline so the LAST one ends ~now
                    s.tl = time.time() - sum(s._dur(f) for f in new) - 4
                for f in new: s.seen.add(f); s._process(f)
                if s.restarts and time.time() - getattr(s, 'spawned', 0) > 120: s.restarts = 0     # stable again
                s._tail_chat()
                try: s._check_pending()
                except Exception as e: s.err = f"cut failed: {str(e)[:80]}"      # one bad cut must not stop the watcher
                s._purge()
                if s.procs and s.procs[1].poll() is not None and not s.stop.is_set():
                    for p in s.procs:
                        try: p.terminate()
                        except Exception: pass
                    if s.restarts < 8:                         # dropped connection / stream hiccup: reconnect instead of giving up
                        s.restarts += 1; s.status = f"reconnecting ({s.restarts}/8)"; s.err = None; time.sleep(6); s._spawn(); continue
                    s.status = "stream ended"; s.err = "stream ended or unreachable"; break
                if s.status.startswith("reconnecting") and len(files) >= 1: s.status = "watching"
        except Exception as e:
            s.err = str(e)[:200]; s.status = "error"

    def _dur(s, f):
        try: return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]))
        except Exception: return 10.0

    def _process(s, f):
        d = s._dur(f); t0 = s.tl; s.tl += d; mt = s.tl     # timeline from cumulative real durations (file mtimes are unreliable in bursts)
        db = A.loudness_series(f); mo = visual.per_second(f)
        n = len(db)
        if n < 3: return
        mo = (mo + [mo[-1] if mo else 0] * n)[:n]
        s.segs.append((f, t0, mt))
        base = len(s.t); s.t += [t0 + i for i in range(n)]; s.db += db; s.mo += mo
        if len(s.t) < 70: return
        T = np.array(s.t); D = np.array(s.db); M = np.array(s.mo)
        sm = np.convolve(D, np.ones(3) / 3, mode="same")
        best = (0.0, None)
        for i in range(max(base, 60), len(T)):
            lo, hi = max(0, i - 150), max(1, i - 10)
            bd, bm = sm[lo:hi], M[lo:hi]
            a = (sm[i] - bd.mean()) / max(bd.std(), 1.5)
            m = (M[i] - bm.mean()) / max(bm.std(), 0.5)
            cr = 0.0
            if s.chat:
                hist = [s._chat_rate(T[j]) for j in range(lo, hi, 5)]
                cr = (s._chat_rate(T[i]) - np.mean(hist)) / max(np.std(hist), 1.0)
            sc = max(a, 0) + .6 * max(m, 0) + max(cr, 0) * 1.0
            if sc > best[0]: best = (sc, (T[i], a, m, cr))
        s.last_score = round(float(best[0]), 2)
        if best[1] and best[0] >= s.sens and best[1][0] - s.last_moment > 60:
            tp, a, m, cr = best[1]; s.last_moment = tp
            why = []
            if a > 1.5: why.append(f"audio jump (z {a:.1f})")
            if m > 1.5: why.append("sudden on-screen action")
            if cr > 1.5: why.append("chat burst")
            s.pending.append({"t": float(tp), "score": round(float(best[0]), 2), "why": why or ["spike"]})

    def _check_pending(s):
        newest = s.segs[-1][2] if s.segs else 0
        for pm in list(s.pending):
            if newest >= pm["t"] + 12:
                s.pending.remove(pm); s._cut(pm)

    def _cut(s, pm):
        a, b = pm["t"] - 28, pm["t"] + 12
        use = [x for x in s.segs if x[2] > a and x[1] < b and os.path.exists(x[0])]
        if not use: return
        mid = f"m{int(pm['t'])}_{s.id}"; lst = os.path.join(s.mdir, mid + ".txt"); out = os.path.join(s.mdir, mid + ".mp4")
        with open(lst, "w") as f:
            for x in use: f.write(f"file '{x[0]}'\n")
        off = max(0, a - use[0][1])
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-fflags", "+discardcorrupt", "-f", "concat", "-safe", "0", "-i", lst, "-ss", f"{off:.2f}", "-t", "40",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", out], capture_output=True)
        try: os.remove(lst)
        except OSError: pass
        if not os.path.exists(out): return
        m = {"id": mid, "wall": time.strftime("%H:%M:%S"), "file": out, "preview": "/files/work/live_moments/" + mid + ".mp4",
             "start": 0, "dur": 40, "score": pm["score"], "why": pm["why"], "text": "", "title": "Live moment - add your title", "warn": [], "judging": True,
             "state": "candidate", "peak_rel": round(pm["t"] - a, 2), "src_t0": round(a, 2), "src_t1": round(b, 2), "source_key": s.url}
        s.moments.insert(0, m)
        threading.Thread(target=s._judge, args=(m,), daemon=True).start()

    def _judge(s, m):
        try:
            tmp = os.path.join(s.mdir, "tx_" + m["id"]); os.makedirs(tmp, exist_ok=True)
            wav = os.path.join(tmp, "a.wav")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", m["file"], "-vn", "-ac", "1", "-ar", "16000", wav], capture_output=True)
            q = A.asr_call(wav)          # one pass over the whole moment: these words become the captions AND feed the AI score
            if q and q.get("words"):
                wf = os.path.join(s.mdir, m["id"] + ".words.json"); json.dump(q["words"], open(wf, "w"), ensure_ascii=False); m["words_file"] = wf
                segs = A._segments_from_words(q["words"], 0)
            else:
                segs = A.transcribe_segments(wav, 0, 40, tmp, s.lang)
            f, why, warn, text = A.virality_features(segs, 0, 40, 28)
            if not text.strip(): m["why"].append("no speech to judge")
            m["text"] = text; m["warn"] = warn; m["why"] += why; m["score"] = round(m["score"] + f, 2)
            m["title"] = A.suggest_title(text, "streamer")
            c = {"text": text, "title": m["title"], "why": []}
            import config as _C
            if not _C.load()["planner"]["enabled"] and A.llm_rerank([c], lambda _: None) and "llm" in c:      # the edit planner replaces this one-shot judge
                m["virality"] = c["llm"]; m["score"] = round(m["score"] + (c["llm"] - 5) * .5, 2); m["title"] = c.get("title", m["title"]); m["hook"] = c.get("hook", ""); 
                if c.get("reason"): m["why"].append(c["reason"])
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            m["why"].append(f"(judge failed: {str(e)[:60]})")
        m["judging"] = False
        if s.on_judged:
            try: s.on_judged(m)
            except Exception as e: m["post"] = {"status": "error", "error": str(e)[:160]}

    def _purge(s):
        cut = (s.segs[-1][2] if s.segs else time.time()) - s.buf
        keep = []
        for x in s.segs:
            if x[2] < cut:
                try: os.remove(x[0])
                except OSError: pass
            else: keep.append(x)
        s.segs = keep
        n = sum(1 for t in s.t if t < cut)
        if n > 600: s.t, s.db, s.mo = s.t[n:], s.db[n:], s.mo[n:]
        for k in [k for k in s.chat if k < cut]: del s.chat[k]

    def state(s):
        return {"status": s.status, "error": s.err, "buffer_files": len(s.segs), "buffer_secs": int(len(s.segs) * 10),
                "last_score": s.last_score, "threshold": s.sens, "moments": s.moments}
