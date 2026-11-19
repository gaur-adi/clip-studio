#!/usr/bin/env python3
"""Local Clip Studio: paste a YouTube/Twitch link -> analyse -> ranked clip candidates -> render Shorts.
Run: ./run_app.sh   (binds 127.0.0.1 only)"""
import asyncio, json, mimetypes, os, re, shutil, subprocess, sys, threading, time, uuid, glob
import urllib.parse as up
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "scripts"))
import analyze as A, chat_spikes as CS, live as LV, config as C, editplan as E, dedupe as D, metadata as MD, pipeline_v2 as V2
PORT = int(os.environ.get("PORT", 8765)); HOST = os.environ.get("HOST", "127.0.0.1")
OUT, WORK, MUSIC, LOGS, FINAL = (os.path.join(ROOT, d) for d in ("out", "work", "music", "logs", "final"))
for d in (OUT, WORK, MUSIC, LOGS, FINAL): os.makedirs(d, exist_ok=True)
PERM_FILE = os.path.join(ROOT, "docs", "allowed_creators.json")
JOBS, LIVES = {}, {}
RECENT_MUSIC = []
PY = sys.executable

class Job:
    def __init__(s, kind):
        s.id = uuid.uuid4().hex[:8]; s.kind = kind; s.status = "running"; s.lines = []; s.result = None; s.error = None; JOBS[s.id] = s
    def log(s, m): s.lines.append(m); s.lines = s.lines[-40:]
    def pub(s): return {"id": s.id, "status": s.status, "log": s.lines[-8:], "result": s.result, "error": s.error}

def spawn(fn, job, *a):
    def w():
        try: job.result = fn(job, *a); job.status = "done"
        except Exception as e: job.error = str(e); job.status = "error"
    threading.Thread(target=w, daemon=True).start()

# ---------- analyse a video / VOD link ----------
def do_analyze(job, url, rs, re_, lang=None):
    job.log("Reading link ...")
    info = A.fetch_info(url)
    if info["is_live"]: raise RuntimeError("That link is a LIVE stream. Use 'Live mode' (record + chat spikes) instead.")
    dur = info["duration"] or 0
    if rs is None: rs, re_ = 0, min(dur, 4 * 3600) if dur else None
    if re_ is None or re_ > dur > 0: re_ = dur or re_
    job.log(f"{info['title']}  ({info['uploader']}, {int((re_ or 0)-rs)//60} min to analyse)")
    wd = os.path.join(WORK, f"an_{info['id']}")
    wav = A.download_audio(url, wd, rs, re_, lambda m: job.log(m[:110]))
    def vis_fetch(start, dur):
        vd = os.path.join(wd, "vis"); os.makedirs(vd, exist_ok=True)
        for f in glob.glob(os.path.join(vd, "v.*")): os.remove(f)
        cmd = ["yt-dlp", "--no-playlist", "-q", "-f", "worst[height<=480]/worst/b", "--merge-output-format", "mp4", "-o", os.path.join(vd, "v.%(ext)s"), url]
        if not ("/clip/" in url or (dur_total and start - rs <= 1 and start + dur + 3 >= dur_total)):
            cmd[1:1] = ["--download-sections", f"*{int(start)}-{int(start+dur)}", "--force-keyframes-at-cuts"]; 
        r = subprocess.run(cmd, capture_output=True)
        fs = glob.glob(os.path.join(vd, "v.*")); return fs[0] if fs else None
    dur_total = dur
    cands, _ = A.analyze_audio_file(wav, info, rs, url, wd, job.log, visual_fn=vis_fetch, lang=lang if lang not in (None, '', 'auto') else None)
    for c in cands: c["link"] = A.timelink(info, c["start"] + 3)
    return {"info": {k: v for k, v in info.items() if k != "heatmap"}, "source": url, "candidates": cands}

# ---------- render ----------
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:30] or "clip"

def description(info, title, start, creator):
    link = A.timelink(info, start) if info else ""
    return (f"{title}\n\nClip from {creator}'s stream: {link}\nCredit: {creator} {info.get('channel_url') or ''}\n"
            f"Used with the creator's permission. My commentary added.\nNot affiliated with Rockstar Games / Take-Two.\n"
            f"#shorts #gta6 #gta6gameplay #gta6launch #twitchclips").strip()

def do_render(job, p):
    job.log("Preparing the clip ...")
    info = p.get("info") or {}
    creator = (p.get("creator") or "").strip() or info.get("uploader") or "the streamer"   # permission check removed (user has permissions)
    start, dur = float(p["start"]), float(p["dur"])
    _e = C.load()["edit"]
    if not _e["min_len"] <= dur <= _e["max_len"]: raise RuntimeError(f"Duration must be {_e['min_len']:.0f}-{_e['max_len']:.0f} s")
    pad = min(3.0, start)
    name = (f"{slug(info.get('title') or 'live')}_{os.path.splitext(os.path.basename(p['local_file']))[0]}" if p.get("local_file") else f"{slug(info.get('title') or 'clip')}_{int(start)}"); rd = os.path.join(WORK, "r_" + name); os.makedirs(rd, exist_ok=True)
    if p.get("local_file"):
        src = p["local_file"]
        if not os.path.abspath(src).startswith(WORK + os.sep): raise RuntimeError("bad file")
        ss = start
    else:
        for f in glob.glob(os.path.join(rd, "seg.*")): os.remove(f)
        job.log("Downloading the section ...")
        whole = "/clip/" in p["source"] or "clips.twitch.tv" in p["source"] or (info.get("duration") and start - pad <= 1 and start + dur + 3 >= info["duration"])
        cmd = ["yt-dlp", "--no-playlist", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
               "-o", os.path.join(rd, "seg.%(ext)s"), p["source"]]
        if not whole: cmd[1:1] = ["--download-sections", f"*{int(start-pad)}-{int(start+dur+3)}", "--force-keyframes-at-cuts"]
        A.run(cmd, lambda m: job.log(m[:110]))
        src = os.path.join(rd, "seg.mp4"); ss = pad
    outp = os.path.join(OUT, name + ".mp4")
    cmd = [PY, os.path.join(ROOT, "scripts", "make_short.py"), src, "--start", str(ss), "--dur", str(dur),
           "--title", p.get("overlay") or "", "--mode", p.get("mode") or "blur", "--lang", p.get("lang") or "auto", "-o", outp] + (["--game-subs"] if p.get("game_subs") else []) + (["--words-file", p["words_file"]] if p.get("words_file") and p.get("local_file") and float(p.get("start") or 0) == 0 and os.path.abspath(p["words_file"]).startswith(WORK + os.sep) else [])
    if p.get("mode") == "stack" and p.get("face"): cmd += ["--face", p["face"]]
    if p.get("music") == "auto":   # AI picks the phonk track + its best section for THIS clip, mixed low under the voice
        try:
            import visual, music_ai
            mm = visual.window_metrics(src, ss, dur)
            clip = {"dur": dur, "motion": (mm or {}).get("motion", 10), "text": p.get("text") or "", "mood": p.get("overlay") or p.get("title") or "",
                    "hype": min(len(re.findall(r"[!?]", p.get("text") or "")) / 6 + (p.get("virality") or 5) / 20, 1)}
            job.log("Choosing music with the AI on this Mac ...")
            pk = music_ai.pick(clip, claim_free_only=bool(p.get("claim_free_only")), recent=RECENT_MUSIC[-3:], log=job.log)
            RECENT_MUSIC.append(pk["rel"])
            job.log(f"Music: {pk['rel']} @ {pk['start']}s ({pk['bpm']} bpm) - {pk['why']}")
            cmd += ["--music", pk["file"], "--music-start", str(pk["start"]), "--music-db", str(p.get("music_db") or -21)]
            job.music = pk
        except Exception as e:
            job.log(f"(auto music skipped: {str(e)[:80]})")
    elif p.get("music"):
        m = os.path.join(MUSIC, os.path.basename(p["music"]))
        if os.path.exists(m): cmd += ["--music", m]
    job.log("Rendering (reframe, captions, music) ...")
    A.run(cmd, lambda m: job.log(m[:110]))
    title = p.get("title") or ""
    return {"video": "/files/out/" + name + ".mp4", "title": title, "description": description(info, title, start, creator), "music": getattr(job, "music", None)}

# ---------- live mode: rolling buffer + AI moment detection (see live.py) ----------
PIPE_LOCK = threading.Lock()
YT_TOKEN = os.path.join(os.environ.get("YT_DIR", ROOT), "youtube_token.json")
def yt_ready(): return os.path.exists(YT_TOKEN)

def save_final(live, m):
    """copy the finished Short into final/ with a metadata JSON that the uploader (or you) can publish from"""
    po = m["post"]; stamp = time.strftime("%Y%m%d-%H%M%S"); base = f"{stamp}_{live.channel or 'stream'}_{m['id']}"
    src = os.path.join(ROOT, po["video"].lstrip("/").replace("files/", "", 1)); dst = os.path.join(FINAL, base + ".mp4")
    shutil.copy2(src, dst)
    desc = po["description"]; hashtags = re.findall(r"#\w+", desc)
    meta = {"video_file": base + ".mp4", "title": po["title"], "description": desc, "tags": po.get("tags", []), "hashtags": hashtags,
            "category": "Gaming", "privacy_suggested": live.opts.get("privacy", "public"), "made_for_kids": False, "language": "en",
            "creator": live.channel, "source_url": live.url, "source_moment_time": m.get("wall"), "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ai": {"virality_1_10": m.get("virality"), "rank_score": m.get("score"), "why": m.get("why"), "transcript": m.get("text"), "hook_on_screen": m.get("hook")},
            "music": {"track": po.get("music"), "why": po.get("music_why")}, "warnings": m.get("warn", []),
            "notes": ["Music from Pixabay may be registered in YouTube Content ID" if po.get("music") and "/" in (po.get("music") or "") else "music is original (claim-free)"],
            "status": "ready", "youtube_url": None}
    json.dump(meta, open(os.path.join(FINAL, base + ".json"), "w"), indent=2, ensure_ascii=False)
    open(os.path.join(FINAL, base + ".txt"), "w").write(f"{po['title']}\n\n{desc}\n\nTags: {', '.join(po.get('tags', []))}\n")
    po["final"] = "final/" + base; po["meta_path"] = os.path.join(FINAL, base + ".json")

def upload(m, privacy):
    po = m["post"]; po["status"] = "uploading"
    r = subprocess.run([PY, os.path.join(ROOT, "scripts", "youtube_upload.py"), os.path.join(ROOT, po["video"].lstrip("/").replace("files/", "", 1)),
                        "--title", po["title"], "--description", po["description"], "--tags", ",".join(po.get("tags", [])), "--privacy", privacy],
                       capture_output=True, text=True)
    url = next((l for l in r.stdout.splitlines() if l.startswith("https://")), None)
    if url:
        po.update(status="uploaded", url=url, note=f"privacy: {privacy}")
        try:
            mp = po.get("meta_path")
            if mp: d = json.load(open(mp)); d.update(status="uploaded", youtube_url=url, uploaded=time.strftime("%Y-%m-%d %H:%M:%S"), privacy_used=privacy); json.dump(d, open(mp, "w"), indent=2, ensure_ascii=False)
        except Exception: pass
    else: po.update(status="error", error=(r.stderr or r.stdout).strip().splitlines()[-1][:200] if (r.stderr or r.stdout).strip() else "upload failed")

def pipeline_legacy(live, m):
    """auto: moment -> 40 s Short (blur-fit, captions, hook) -> viral-style title/description -> (optional) upload"""
    o = live.opts
    if not o["render"]: return
    sc = m.get("virality")
    if sc is None:   # no speech to judge, or the AI was unreachable: never auto-make an upload-ready Short with junk metadata
        m["post"] = {"status": "skipped", "note": "AI could not judge this moment (little speech or AI unavailable) - use Render Short if you like it"}; return
    if sc < o["min"]:
        m["post"] = {"status": "skipped", "note": f"AI score {sc} below minimum {o['min']}"}; return
    m["post"] = {"status": "rendering"}
    with PIPE_LOCK:
        ch = live.channel or "streamer"
        info = {"title": f"{ch}-{m['id']}", "uploader": ch, "extractor": "twitch", "webpage_url": live.url, "id": m["id"], "channel_url": live.url}
        job = Job("auto")
        res = do_render(job, {"source": live.url, "info": info, "local_file": m["file"], "start": 0, "dur": 40, "mode": "blur",
                              "overlay": m.get("hook") or "", "title": m["title"], "creator": ch, "music": "auto", "words_file": m.get("words_file"), "lang": o.get("lang") or "auto", "game_subs": o.get("game_subs"), "text": m.get("text", ""), "virality": m.get("virality"), "claim_free_only": o.get("claim_free")})
        meta = A.llm_meta(m.get("text", ""), ch, live.url) or {}
        title = meta.get("title") or m["title"]; tags = meta.get("tags") or ["gta6", "gta6gameplay", "shorts"]
        desc = (meta.get("description") or title) + f"\n\nClip from {ch}'s stream: {live.url}\nCredit: {ch}\nNot affiliated with Rockstar Games / Take-Two.\n#shorts #gta6 #gta6gameplay #gta6launch"
        m["post"] = {"status": "ready", "music": (res.get("music") or {}).get("rel"), "music_why": (res.get("music") or {}).get("why"), "video": res["video"], "title": title, "description": desc, "tags": tags}
        save_final(live, m)
        if m.get("warn"): m["post"]["note"] = "held: " + "; ".join(m["warn"]); return
        if o["post"]:
            if yt_ready(): upload(m, o["privacy"])
            else: m["post"]["note"] = "YouTube not connected (docs/YOUTUBE_SETUP.md) - ready to post manually"

def _live_ctx(live, m):
    cfg = C.load(); words = json.load(open(m["words_file"])) if m.get("words_file") and os.path.exists(m["words_file"]) else []
    src = V2.source_identity(live.url, live.id); info = getattr(live, "info", None) or {}
    topic = MD.resolve_topic(live.opts.get("game"), info.get("title"), m.get("text")); creator = MD.resolve_creator(live.channel, info)
    return cfg, words, src, topic, creator

def pipeline(live, m):
    """moment -> edit plan -> duplicate check -> (approval) -> render -> quality gate -> final/ (ready) or review/ (needs_review)."""
    cfg = C.load()
    if not cfg["planner"]["enabled"]: return pipeline_legacy(live, m)
    o = live.opts
    if not o["render"]: return
    cfg, words, src, topic, creator = _live_ctx(live, m)
    try: dur = V2.media_duration(m["file"])
    except Exception as e: m["state"] = "render_failed"; m["post"] = {"status": "error", "error": f"unreadable moment file: {e}"}; return
    m["state"] = "planning"; m["post"] = {"status": "planning"}
    lang = MD.detect_language(m.get("text") or "")
    plan = V2.make_plan(words, m.get("peak_rel", 28.0), dur, cfg, lang, topic["game"] if topic["verified"] else None, video=m["file"])
    m["plan"] = plan; m["state"] = plan["state"]; m["virality"] = plan.get("editorial_quality")
    if plan.get("title_hint"): m["title"] = plan["title_hint"]
    if plan.get("opening_text"): m["hook"] = plan["opening_text"]
    if plan["state"] == "rejected" or not plan.get("segments"):
        m["post"] = {"status": "rejected" if plan["state"] == "rejected" else "needs_review", "note": "; ".join(plan.get("reasons", []))[:300]}; return
    seg0, seg1 = plan["segments"][0]["start"], plan["segments"][-1]["end"]
    ok, row = D.claim(src["key"], m["src_t0"] + seg0, m["src_t0"] + seg1, m["id"], "planned", cfg)
    if not ok:
        m["state"] = "duplicate"; m["post"] = {"status": "skipped", "note": f"duplicate of clip {row.get('clip_id')} (same source interval)"}; return
    m["registry_id"] = row
    if plan["state"] != "planned" or not cfg["auto_approve"]:
        D.set_state(row, "needs_review"); m["state"] = "needs_review"
        m["post"] = {"status": "needs_review", "note": ("awaiting your approval: " + "; ".join(plan.get("reasons", []))[:240])}; return
    approve_moment(live, m, plan, None, force=False)

def approve_moment(live, m, plan, preset, force=False, face=None, gx="0.5"):
    """render the (possibly user-adjusted) plan; the quality gate decides final/ vs review/"""
    cfg, words, src, topic, creator = _live_ctx(live, m); o = live.opts
    if "registry_id" not in m:
        ok, row = D.claim(src["key"], m["src_t0"] + plan["segments"][0]["start"], m["src_t0"] + plan["segments"][-1]["end"], m["id"], "approved", cfg)
        if not ok: m["state"] = "duplicate"; m["post"] = {"status": "skipped", "note": f"duplicate of clip {row.get('clip_id')}"}; return
        m["registry_id"] = row
    D.set_state(m["registry_id"], "rendering"); m["state"] = "rendering"; m["post"] = {"status": "rendering"}
    stamp = time.strftime("%Y%m%d-%H%M%S"); base = f"{stamp}_{live.channel or 'stream'}_{m['id']}"
    ctx = {"cfg": cfg, "plan": plan, "words": words, "src": m["file"], "base": base, "preset": preset or cfg["framing"]["default"], "face": face, "gx": gx, "words_file": m.get("words_file"),
           "source": src, "topic": topic, "creator": creator, "abs_t0": m["src_t0"], "claimed": True, "registry": None, "wall": m.get("wall"), "privacy": o.get("privacy", "public"),
           "rank_score": m.get("score"), "warnings": m.get("warn", []), "game_subs": o.get("game_subs", False), "claim_free_only": o.get("claim_free", False), "recent_music": RECENT_MUSIC[-3:],
           "source_words": words, "source_words_file": m.get("words_file"), "source_ts": None, "lang": MD.detect_language(m.get("text") or "")}
    ctx = V2.finish_edit(ctx, log=lambda x: None, force=force)
    m["state"] = ctx["state"]; m["qa"] = ctx.get("qa")
    D.set_state(m["registry_id"], {"ready": "ready", "needs_review": "needs_review", "render_failed": "render_failed"}.get(ctx["state"], "needs_review"))
    if ctx["state"] == "render_failed": m["post"] = {"status": "error", "error": ctx.get("error", "render failed")}; return
    meta = json.load(open(ctx["meta_path"])); folder = "final" if ctx["state"] == "ready" else "review"
    m["post"] = {"status": "ready" if ctx["state"] == "ready" else "needs_review", "video": "/files/out/" + base + ".mp4", "title": meta["title"], "description": meta["description"], "tags": meta["tags"],
                 "final": f"{folder}/{base}", "meta_path": ctx["meta_path"], "music": (ctx.get("music_info") or {}).get("track"), "music_why": (ctx.get("music_info") or {}).get("why"),
                 "note": ("quality gate failed: " + "; ".join(ctx["qa"]["failed"])) if ctx["state"] == "needs_review" else "passed the quality gate"}
    if ctx["state"] == "ready" and o.get("post") and yt_ready(): upload(m, o["privacy"])

# ---------- review / approve / settings (planner workflow) ----------
SETTINGS_RULES = {("thresholds", "hook"): (0, 10), ("thresholds", "clarity"): (0, 10), ("thresholds", "payoff"): (0, 10), ("thresholds", "review_margin"): (0, 5),
                  ("edit", "min_len"): (3, 30), ("edit", "max_len"): (10, 60), ("edit", "max_time_to_payoff"): (3, 40)}
SETTINGS_BOOL = {("auto_approve",), ("planner", "enabled"), ("qa", "visual_check")}
PRESETS = ("context", "gameplay", "gameplay_facecam")

def find_moment(live_id, mid):
    l = LIVES.get(live_id); m = next((x for x in (l.w.moments if l else []) if x["id"] == mid), None)
    return l, m

def save_settings(p):
    """whitelisted, range-checked changes merged into config.json (the only file this writes); returns the effective config"""
    path = os.path.join(ROOT, "config.json")
    try: cur = json.load(open(path))
    except Exception: cur = {}
    def put(keys, v):
        d = cur
        for k in keys[:-1]: d = d.setdefault(k, {})
        d[keys[-1]] = v
    for (a, b), (lo, hi) in SETTINGS_RULES.items():
        v = (p.get(a) or {}).get(b)
        if v is None: continue
        v = float(v)
        if not lo <= v <= hi: raise ValueError(f"{a}.{b} must be between {lo} and {hi}")
        put((a, b), v)
    for keys in SETTINGS_BOOL:
        v = p
        for k in keys: v = v.get(k) if isinstance(v, dict) else None
        if isinstance(v, bool): put(keys, v)
    fd = (p.get("framing") or {}).get("default")
    if fd is not None:
        if fd not in PRESETS: raise ValueError("unknown framing preset")
        put(("framing", "default"), fd)
    tmp = path + ".tmp"; json.dump(cur, open(tmp, "w"), indent=1); os.replace(tmp, path)
    return C.load()

def plan_update(live, m, p):
    cfg, words, src, topic, creator = _live_ctx(live, m); dur = V2.media_duration(m["file"]); base = m.get("plan") or {}
    plan = V2.manual_plan(words, float(p["start"]), float(p["end"]), dur, cfg, base=base)
    if p.get("opening_text") is not None: plan["opening_text"] = (str(p["opening_text"]).strip()[:80] or None)
    m["plan"] = plan; m["state"] = "needs_review"; m["post"] = {"status": "needs_review", "note": "timing changed by you: approve to render"}
    return plan

def do_approve(live, m, preset, force):
    try:
        approve_moment(live, m, m["plan"], preset, force=force)
    except Exception as e:
        m["state"] = "render_failed"; m["post"] = {"status": "error", "error": str(e)[:300]}

class Live:
    def __init__(s, url, channel, sens, opts):
        s.id = uuid.uuid4().hex[:8]; s.url = url; s.channel = channel; s.stop = threading.Event(); s.opts = opts
        s.chat_path = os.path.join(LOGS, f"live-{channel}-{time.strftime('%H%M%S')}.jsonl") if channel else None
        if channel:
            threading.Thread(target=lambda: asyncio.run(CS.log(channel, 0, s.chat_path, False, stop=s.stop)), daemon=True).start()
        threading.Thread(target=lambda: setattr(s, 'info', (lambda: A.fetch_info(url))() if True else None), daemon=True).start() if False else None
        s.info = {}
        def _fetch():
            try: s.info = A.fetch_info(url)
            except Exception: s.info = {}
        threading.Thread(target=_fetch, daemon=True).start()
        s.w = LV.Watcher(url, s.id, WORK, sens=sens, chat_path=s.chat_path, on_judged=lambda m: pipeline(s, m), lang=(opts.get('lang') if opts.get('lang') not in (None, '', 'auto') else None)); s.w.start(); LIVES[s.id] = s
    def state(s):
        d = s.w.state(); d.update({"id": s.id, "channel": s.channel, "chat": bool(s.chat_path), "opts": s.opts, "youtube": yt_ready(), "url": s.url}); return d
    def end(s):
        s.stop.set(); s.w.end()

# ---------- HTTP ----------
class Quiet(ThreadingHTTPServer):
    def handle_error(self, request, client_address):      # browsers cancel video previews mid-download: not an error
        import sys as _s
        if isinstance(_s.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)): return
        super().handle_error(request, client_address)

class H(BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def send_json(s, obj, code=200):
        b = json.dumps(obj).encode(); s.send_response(code); s.send_header("Content-Type", "application/json")
        s.send_header("Content-Length", str(len(b))); s.end_headers(); s.wfile.write(b)
    def local_ok(s):
        host = (s.headers.get("Host") or "").split(":")[0]; org = s.headers.get("Origin")
        return host in ("127.0.0.1", "localhost") and (not org or up.urlparse(org).hostname in ("127.0.0.1", "localhost"))
    def do_GET(s):
        if not s.local_ok(): return s.send_json({"error": "forbidden"}, 403)
        path = up.urlparse(s.path).path
        if path == "/": return s.file(os.path.join(HERE, "index.html"))
        if path.startswith("/files/"):
            rel = os.path.normpath(path[7:]); full = os.path.realpath(os.path.join(ROOT, rel))
            if rel.split(os.sep)[0] not in ("out", "work", "final") or not full.startswith(ROOT + os.sep): return s.send_json({"error": "no"}, 404)
            return s.file(full)
        if path.startswith("/api/job/"):
            j = JOBS.get(path.split("/")[-1]); return s.send_json(j.pub() if j else {"error": "unknown"}, 200 if j else 404)
        if path == "/api/live": return s.send_json([{"id": x.id, "url": x.url, "status": x.w.status} for x in LIVES.values() if x.w.status not in ("stopped",)])
        if path.startswith("/api/live/"):
            l = LIVES.get(path.split("/")[-1]); return s.send_json(l.state() if l else {"error": "unknown"}, 200 if l else 404)
        if path == "/api/music": return s.send_json(sorted(os.path.basename(f) for f in glob.glob(MUSIC + "/*") if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg"))))
        if path == "/api/analytics/report":
            import analytics; return s.send_json(analytics.report())
        if path == "/api/settings":
            c = C.load(); return s.send_json({k: c[k] for k in ("thresholds", "edit", "framing", "safe_area", "qa", "planner", "auto_approve")} | {"presets": list(PRESETS)})
        if path == "/api/health": return s.send_json({t: bool(shutil.which(t)) for t in ("ffmpeg", "yt-dlp", "whisper-cli", "streamlink")} | {"model": os.path.exists(A.MODEL)})
        s.send_json({"error": "not found"}, 404)
    def do_POST(s):
        if not s.local_ok() or "json" not in (s.headers.get("Content-Type") or ""): return s.send_json({"error": "forbidden"}, 403)
        p = json.loads(s.rfile.read(int(s.headers.get("Content-Length") or 0)) or b"{}"); path = up.urlparse(s.path).path
        try:
            if path == "/api/analyze":
                if not A.ok_url(p.get("url")): return s.send_json({"error": "Paste a YouTube or Twitch link"}, 400)
                j = Job("analyze"); rs = p.get("from"); re_ = p.get("to")
                spawn(do_analyze, j, p["url"].strip(), float(rs) if rs not in (None, "") else None, float(re_) if re_ not in (None, "") else None, p.get("lang"))
                return s.send_json({"job": j.id})
            if path == "/api/render":
                j = Job("render"); spawn(do_render, j, p); return s.send_json({"job": j.id})
            if path == "/api/live/start":
                u = p.get("url", "").strip()
                if not A.ok_url(u): return s.send_json({"error": "Paste a YouTube or Twitch link"}, 400)
                m = re.match(r"https?://(?:www\.)?twitch\.tv/([A-Za-z0-9_]+)/?$", u)
                if not shutil.which("streamlink"): return s.send_json({"error": "streamlink not installed"}, 400)
                for x in LIVES.values():
                    if x.url == u and x.w.status not in ("stopped", "error", "stream ended"): return s.send_json({"live": x.id, "chat": bool(x.chat_path), "reused": True})
                opts = {"render": bool(p.get("auto_render", True)), "post": bool(p.get("auto_post", False)), "min": float(p.get("min") or 5), "privacy": p.get("privacy") or "public", "claim_free": bool(p.get("claim_free_only")), "game": (p.get("game") or "").strip(), "lang": p.get("lang") or "auto", "game_subs": bool(p.get("game_subs"))}
                l = Live(u, m.group(1).lower() if m else None, float(p.get("sens") or 3.0), opts)
                return s.send_json({"live": l.id, "chat": bool(m)})
            if path == "/api/post":
                l = LIVES.get(p.get("live")); m = next((x for x in (l.w.moments if l else []) if x["id"] == p.get("moment")), None)
                if not m or not m.get("post") or not m["post"].get("video"): return s.send_json({"error": "render the Short first"}, 400)
                if not yt_ready(): return s.send_json({"error": "YouTube not connected - see docs/YOUTUBE_SETUP.md"}, 400)
                for k in ("title", "description"):
                    if p.get(k): m["post"][k] = p[k]
                threading.Thread(target=upload, args=(m, p.get("privacy") or "public"), daemon=True).start(); return s.send_json({"ok": True})
            if path == "/api/settings":
                try: c = save_settings(p)
                except (ValueError, TypeError) as e: return s.send_json({"error": str(e)}, 400)
                return s.send_json({"ok": True, "thresholds": c["thresholds"], "auto_approve": c["auto_approve"], "framing": c["framing"], "edit": c["edit"]})
            if path in ("/api/plan/update", "/api/approve", "/api/reject"):
                l, m = find_moment(p.get("live"), p.get("moment"))
                if not m or not m.get("plan"): return s.send_json({"error": "unknown moment or no plan"}, 404)
                if m.get("state") in ("rendering", "planning"): return s.send_json({"error": f"moment is {m['state']}: wait"}, 409)
                if path == "/api/plan/update":
                    try: return s.send_json({"ok": True, "plan": plan_update(l, m, p)})
                    except Exception as e: return s.send_json({"error": str(e)}, 400)
                if path == "/api/reject":
                    m["state"] = "rejected"; m["post"] = {"status": "rejected", "note": "rejected by you"}
                    if m.get("registry_id"): D.set_state(m["registry_id"], "rejected")
                    return s.send_json({"ok": True})
                if not m["plan"].get("segments"): return s.send_json({"error": "this moment has no edit to render"}, 400)
                preset = p.get("preset") or C.load()["framing"]["default"]
                if preset not in PRESETS and preset not in ("blur", "center", "auto", "stack"): return s.send_json({"error": "unknown framing preset"}, 400)
                m["plan"]["approved_by"] = "user"   # an explicit human approval of a review-state plan; the quality gate still decides final/ vs review/
                threading.Thread(target=do_approve, args=(l, m, preset, True), daemon=True).start(); return s.send_json({"ok": True})
            if path.startswith("/api/live/stop/"):
                l = LIVES.get(path.split("/")[-1]); l and l.end(); return s.send_json({"ok": True})
        except Exception as e:
            return s.send_json({"error": str(e)}, 500)
        s.send_json({"error": "not found"}, 404)
    def file(s, full):
        if not os.path.isfile(full): return s.send_json({"error": "not found"}, 404)
        size = os.path.getsize(full); ct = mimetypes.guess_type(full)[0] or "application/octet-stream"
        rng = re.match(r"bytes=(\d+)-(\d*)", s.headers.get("Range") or ""); a, b = 0, size - 1
        if rng: a = int(rng.group(1)); b = int(rng.group(2) or size - 1)
        s.send_response(206 if rng else 200); s.send_header("Content-Type", ct); s.send_header("Accept-Ranges", "bytes")
        if rng: s.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        s.send_header("Content-Length", str(b - a + 1)); s.end_headers()
        with open(full, "rb") as f:
            f.seek(a); left = b - a + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk: break
                try: s.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError): break
                left -= len(chunk)

def _shutdown(*_):
    for l in list(LIVES.values()):
        try: l.end()
        except Exception: pass
    os._exit(0)

if __name__ == "__main__":
    import signal
    subprocess.run(["pkill", "-f", "streamlink.*--output|streamlink.* -O "], capture_output=True)       # leftovers from a previous crashed run
    for d in glob.glob(os.path.join(WORK, "live_buf_*")): shutil.rmtree(d, ignore_errors=True)
    signal.signal(signal.SIGTERM, _shutdown); signal.signal(signal.SIGINT, _shutdown)   # stopping the app also stops all watchers
    print(f"Clip Studio on http://127.0.0.1:{PORT}  (Ctrl-C to quit)")
    Quiet((HOST, PORT), H).serve_forever()
