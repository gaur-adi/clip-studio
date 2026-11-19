"""Edit-planned generation: moment -> plan -> duplicate check -> render -> quality gate -> final/ (or review/).
States (editorial; publication is tracked separately): candidate, planning, needs_review, approved, rendering, render_failed, ready, rejected, duplicate."""
import json, os, re, shutil, subprocess, sys, time
import analyze as A, config as C, dedupe as D, editplan as E, metadata as MD, planner as P, qa as Q
ROOT = C.ROOT; PY = sys.executable
FINAL, OUT, WORK = (os.path.join(ROOT, d) for d in ("final", "out", "work"))
REVIEW = os.path.join(ROOT, "review"); PREVIEWS = os.path.join(ROOT, "previews")
SCHEMA_VERSION = 2
PRESETS = ("context", "gameplay", "gameplay_facecam")

def media_duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).decode().strip())

def source_identity(url, live_key=None):
    u = url or ""; m = re.search(r"[?&]v=([\w-]{6,})", u) or re.search(r"youtu\.be/([\w-]{6,})", u)
    if m: return {"platform": "youtube", "id": m.group(1), "url": u, "key": "youtube:" + m.group(1)}
    m = re.search(r"twitch\.tv/videos/(\d+)", u)
    if m: return {"platform": "twitch", "id": m.group(1), "url": u, "key": "twitch-vod:" + m.group(1)}
    m = re.search(r"twitch\.tv/([A-Za-z0-9_]+)", u)
    if m: return {"platform": "twitch", "id": m.group(1).lower(), "url": u, "key": "twitch:" + m.group(1).lower()}
    return {"platform": "other", "id": live_key or u, "url": u, "key": "other:" + (live_key or u)}

def render_edit(src, segments, out_path, work_dir, opening_text="", mode=None, words_file=None, face=None, gx="0.5", lang="auto", game_subs=False,
                music_args=(), banner_secs=None, stage="final"):
    """one run of scripts/make_short.py for an edit -> {"out","layout","events","report"}"""
    os.makedirs(work_dir, exist_ok=True); os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = [PY, os.path.join(ROOT, "scripts", "make_short.py"), src, "--segments", ";".join(f"{g['start']},{g['end']}" for g in segments), "--work", work_dir, "-o", out_path,
           "--title", opening_text or "", "--gx", str(gx), "--lang", lang, "--stage", stage]
    if mode: cmd += ["--mode", mode]
    if face: cmd += ["--face", face]
    if words_file and os.path.exists(words_file): cmd += ["--words-file", words_file]
    if game_subs: cmd += ["--game-subs"]
    if banner_secs is not None: cmd += ["--banner-secs", str(banner_secs)]
    cmd += list(music_args)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: raise RuntimeError("render failed: " + (r.stderr or r.stdout).strip().splitlines()[-1][:300])
    name = os.path.splitext(os.path.basename(src))[0]
    return {"out": out_path, "layout": os.path.join(work_dir, f"{name}.layout.json"), "events": os.path.join(work_dir, f"{name}_2_captioned.mp4.events.json"),
            "report": out_path + ".render.json"}

def make_plan(words, peak, duration, cfg, lang, topic_name, log=lambda m: None, video=None, work_dir=None):
    plan = P.plan_moment(words, peak, duration, cfg, lang=lang, topic=topic_name, log=log)
    # optional vision check of the edited frames: can only ADD doubt (review), never raise a score; any failure is recorded as 'unavailable'
    if video and plan.get("segments") and plan.get("planner") == "llm" and cfg["qa"].get("visual_check") and plan.get("payoff_time") is not None:
        try:
            import visual_check as VC
            seg = plan["segments"]; vis = VC.check_payoff(video, seg[0]["start"], seg[-1]["end"], plan.get("what_happens") or plan["evidence"]["payoff"]["quote"],
                                                         plan["payoff_time"], work_dir or os.path.join(WORK, "visual"))
            VC.apply_to_plan(plan, vis, cfg)
        except Exception as e:
            plan.setdefault("reasons", []).append(f"visual check skipped: {str(e)[:80]}")
    return plan

def manual_plan(words, start, end, duration, cfg, base=None):
    """a human-chosen window: validated and snapped to speech-safe boundaries; keeps the model's scores/evidence for reference only"""
    w = E.clean_words(words)
    segs = E.validate_segments(E.snap_segments([{"start": E.validate_time(start, duration, "start"), "end": E.validate_time(end, duration, "end"), "role": "full", "note": "set by the user"}], w, cfg, duration), duration, cfg)
    p = dict(base or {}); p.update(segments=segs, planner="manual", decision="review", state="needs_review", edited_by_user=True)
    p["reasons"] = list((base or {}).get("reasons", [])) + ["segments set manually (speech-safe snapping applied)"]
    p["time_to_payoff"] = round(p["payoff_time"] - segs[0]["start"], 2) if E.finite(p.get("payoff_time")) else None
    return p

def music_for(plan, src, segs, text, recent=(), claim_free_only=False, log=lambda m: None):
    try:
        import visual, music_ai
        s0 = segs[0]["start"]; total = sum(g["end"] - g["start"] for g in segs); mm = visual.window_metrics(src, s0, total)
        pk = music_ai.pick({"dur": total, "motion": (mm or {}).get("motion", 10), "text": text[:300], "mood": plan.get("what_happens") or ""}, claim_free_only=claim_free_only, recent=recent, log=log)
        return ["--music", pk["file"], "--music-start", str(pk["start"]), "--music-db", "-21"], pk
    except Exception as e:
        log(f"(music skipped: {str(e)[:80]})"); return [], None

def build_meta_json(ctx):
    """schema v2 metadata. Keeps every key the earlier consumers read (title, description, tags, hashtags, category, privacy_suggested, made_for_kids, language, creator,
    source_url, source_moment_time, created, ai, music, warnings, notes, status, youtube_url) and ADDS the full edit record. status == editorial readiness; publication is separate."""
    md, plan, qa_res = ctx["metadata"], ctx["plan"], ctx["qa"]
    return {"schema_version": SCHEMA_VERSION, "video_file": ctx["video_file"], "title": md["title"], "description": md["description"], "tags": md["tags"], "hashtags": md["hashtags"],
            "category": "Gaming", "privacy_suggested": ctx.get("privacy", "public"), "made_for_kids": False, "language": md["language"],
            "creator": md["creator"]["name"], "creator_info": md["creator"], "topic": md["topic"], "source_url": ctx["source"]["url"], "source_identity": ctx["source"],
            "source_moment_time": ctx.get("wall"), "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ai": {"editorial_quality": plan.get("editorial_quality"), "scores": plan.get("scores"), "virality_1_10": plan.get("editorial_quality"), "rank_score": ctx.get("rank_score"),
                   "why": plan.get("reasons"), "transcript": ctx["selected_text"], "hook_on_screen": plan.get("opening_text"), "note": "editorial quality score (hook/clarity/payoff), not a prediction of views"},
            "state": ctx["state"], "status": "ready" if ctx["state"] == "ready" else ctx["state"], "publication": {"status": "unpublished", "youtube_url": None}, "youtube_url": None,
            "edit_plan": plan, "source_words": ctx.get("source_words"), "selected_words": ctx.get("selected_words"), "source_words_file": ctx.get("source_words_file"),
            "framing": {"preset": ctx.get("preset"), "layout": ctx.get("layout")}, "qa": qa_res, "models": {"llm": plan.get("model"), "prompt_version": plan.get("prompt_version"), "asr": "Qwen3-ASR-1.7B"},
            "music": ctx.get("music_info") or {"track": None, "why": None}, "warnings": ctx.get("warnings", []), "notes": md["notes"] + ctx.get("notes", []),
            "durations": {"source_seconds": ctx.get("source_duration"), "edited_seconds": ctx.get("edited_duration")}}

def write_package(folder, base, video_src, meta):
    os.makedirs(folder, exist_ok=True); dst = os.path.join(folder, base + ".mp4"); shutil.copy2(video_src, dst)
    json.dump(meta, open(os.path.join(folder, base + ".json"), "w"), indent=2, ensure_ascii=False)
    open(os.path.join(folder, base + ".txt"), "w").write(f"{meta['title']}\n\n{meta['description']}\n\nTags: {', '.join(meta['tags'])}\n")
    return os.path.join(folder, base + ".json")

def finish_edit(ctx, log=lambda m: None, force=False):
    """render the plan, run the quality gate, then write to final/ (state ready) or review/ (needs_review / render_failed). ctx: see build_meta_json plus src, plan, words, opts"""
    cfg = ctx.get("cfg") or C.load(); plan = ctx["plan"]; segs = plan["segments"]; base = ctx["base"]
    rd = os.path.join(WORK, "render_" + base); out = os.path.join(OUT, base + ".mp4")
    sel_text = E.selected_transcript(E.clean_words(ctx["words"]), segs); ctx["selected_text"] = sel_text
    lang = MD.detect_language(sel_text) if sel_text else (ctx.get("lang") or "unknown")
    music_args, pk = (music_for(plan, ctx["src"], segs, sel_text, ctx.get("recent_music", ()), ctx.get("claim_free_only", False), log) if ctx.get("music", True) else ([], None))
    ctx["music_info"] = {"track": pk["rel"], "why": pk["why"], "bpm": pk["bpm"], "claim_free": pk["claim_free"]} if pk else None
    log("rendering the planned edit ...")
    try:
        res = render_edit(ctx["src"], segs, out, rd, plan.get("opening_text") or "", ctx.get("preset") or cfg["framing"]["default"], ctx.get("words_file"), ctx.get("face"), ctx.get("gx", "0.5"),
                          "auto", ctx.get("game_subs", False), music_args, ctx.get("banner_secs"))
    except Exception as e:
        ctx["state"] = "render_failed"; ctx["error"] = str(e); return ctx
    rep = json.load(open(res["report"])); layout = json.load(open(res["layout"])) if os.path.exists(res["layout"]) else None
    ctx.update(selected_words=rep.get("selected_words"), layout=layout, edited_duration=rep["edited_duration"], source_duration=rep["source_duration"], out=out)
    md = MD.build_metadata({"plan": plan, "selected_text": sel_text, "lang": lang, "topic": ctx["topic"], "creator": ctx["creator"], "source_url": ctx["source"]["url"],
                            "source_ts": ctx.get("source_ts")}, chat=ctx.get("chat")); ctx["metadata"] = md
    dup = D.check(ctx["source"]["key"], ctx["abs_t0"] + segs[0]["start"], ctx["abs_t0"] + segs[-1]["end"], cfg, ctx.get("registry")) if ctx.get("abs_t0") is not None and not ctx.get("claimed") else None
    ctx["qa"] = Q.run_qa(out, rep["edited_duration"], res["events"], res["layout"], md, dup, cfg)
    if ctx["qa"]["passed"] and (plan.get("decision") == "accept" or force): ctx["state"] = "ready"
    else: ctx["state"] = "needs_review"
    if len(sel_text.split()) < 3:        # no transcript: no captions and a placeholder title, so a human must look at it before it goes anywhere
        ctx["state"] = "needs_review"; md["notes"].append("no transcript for this edit: no captions, placeholder title - check and rename before publishing")
    ctx["video_file"] = base + ".mp4"
    meta = build_meta_json(ctx)
    ctx["meta_path"] = write_package(FINAL if ctx["state"] == "ready" else REVIEW, base, out, meta)
    return ctx
