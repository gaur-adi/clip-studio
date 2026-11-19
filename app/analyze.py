"""Link analysis: finds clip-worthy moments in a YouTube/Twitch video using
audio-loudness jumps + YouTube 'most replayed' heatmap + YouTube chat replay (when available)
+ whisper transcript hype words. All local/free."""
import json, os, re, statistics, subprocess, sys, glob, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
def _model():
    for m in (os.environ.get("WHISPER_MODEL"), os.path.join(ROOT, "models", "ggml-large-v3-turbo.bin"), os.path.join(ROOT, "models", "ggml-small.bin"), os.path.join(ROOT, "models", "ggml-base.en.bin")):
        if m and os.path.exists(m): return m
    return os.path.join(ROOT, "models", "ggml-base.en.bin")
MODEL = _model()            # multilingual (Hindi + English, auto-detected) when ggml-small.bin is present
MULTI = ".en." not in MODEL
LAST_LANG = {"code": "en"}
URL_RE = re.compile(r"^https?://([\w-]+\.)?(youtube\.com|youtu\.be|twitch\.tv)/", re.I)
HYPE = {"oh", "wow", "no", "what", "omg", "god", "holy", "insane", "crazy", "unbelievable", "wait", "yes", "dude",
        "bro", "damn", "wtf", "scream", "help", "run", "dead", "die", "lol", "haha", "look", "whoa", "nice", "let's", "go"}

def ok_url(u): return bool(URL_RE.match(u or ""))

def run(cmd, log=None, check=True):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = []
    for line in p.stdout:
        out.append(line)
        if log and line.strip() and not line.startswith("frame="): log(line.rstrip()[:200])
    p.wait()
    if check and p.returncode: raise RuntimeError(f"{os.path.basename(cmd[0])} failed ({p.returncode}): {''.join(out[-3:])}")
    return "".join(out)

def fetch_info(url):
    out = subprocess.run(["yt-dlp", "-J", "--no-playlist", url], capture_output=True, text=True)
    if out.returncode: raise RuntimeError("yt-dlp could not read that link: " + out.stderr.strip().splitlines()[-1][:200])
    d = json.loads(out.stdout)
    return {"id": d.get("id"), "title": d.get("title"), "uploader": (d.get("channel") if "twitch" in (d.get("extractor_key") or "").lower() and d.get("channel") else (d.get("uploader") or d.get("channel"))),
            "channel_url": d.get("uploader_url") or d.get("channel_url"), "duration": d.get("duration"),
            "is_live": bool(d.get("is_live")), "extractor": (d.get("extractor_key") or "").lower(),
            "webpage_url": d.get("webpage_url") or url, "heatmap": d.get("heatmap"),
            "thumbnail": d.get("thumbnail")}

def timelink(info, sec):
    sec = int(sec); u = info["webpage_url"]
    if "twitch" in info["extractor"] and "/videos/" in u:
        return f"{u.split('?')[0]}?t={sec//3600}h{sec%3600//60}m{sec%60}s"
    if "youtube" in info["extractor"]: return f"https://www.youtube.com/watch?v={info['id']}&t={sec}s"
    return u

def download_audio(url, workdir, rs, re_, log):
    os.makedirs(workdir, exist_ok=True)
    for f in glob.glob(os.path.join(workdir, "audio.*")): os.remove(f)
    cmd = ["yt-dlp", "--no-playlist", "-f", "ba[abr<=96]/worst[height<=480]/ba/b", "-x", "--audio-format", "wav",
           "--postprocessor-args", "ffmpeg:-ac 1 -ar 16000", "-o", os.path.join(workdir, "audio.%(ext)s"), "--newline"]
    if rs is not None and re_ is not None and rs > 0:
        try:
            run(cmd + ["--download-sections", f"*{int(rs)}-{int(re_)}"], log); return os.path.join(workdir, "audio.wav")
        except RuntimeError:
            log("section download failed, fetching full audio and trimming ...")
            run(cmd + [url], log)
            w = os.path.join(workdir, "audio.wav"); t = w + ".trim.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(int(rs)), "-t", str(int(re_ - rs)), "-i", w, t]); os.replace(t, w)
            return w
    run(cmd + [url], log)
    if re_ is not None and rs is not None:
        w = os.path.join(workdir, "audio.wav"); t = w + ".trim.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-t", str(int(re_)), "-i", w, t]); os.replace(t, w)
    return os.path.join(workdir, "audio.wav")

def loudness_series(wav, log=None):
    """per-second RMS dB list"""
    cmd = ["ffmpeg", "-nostats", "-loglevel", "error", "-i", wav, "-af",
           "asetnsamples=n=8000:p=0,astats=metadata=1:reset=1,ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-",
           "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    vals = []
    for line in out.splitlines():
        if line.startswith("lavfi.astats.Overall.RMS_level="):
            v = line.split("=", 1)[1]
            vals.append(-90.0 if "inf" in v or v == "nan" else max(float(v), -90.0))
    return [sum(vals[i:i+2]) / len(vals[i:i+2]) for i in range(0, len(vals), 2)]

def zs(a):
    if not a: return a
    mu = statistics.mean(a); sd = statistics.pstdev(a) or 1
    return [(x - mu) / sd for x in a]

def audio_scores(db):
    n = len(db); sm = [statistics.mean(db[max(0, i-1):i+2]) for i in range(n)]
    rise = []
    for i in range(n):
        w = sm[max(0, i-90):max(i-5, 1)] or [sm[i]]
        rise.append(sm[i] - statistics.median(w))
    return [max(x, 0) for x in zs(rise)], rise, sm

def yt_chat_series(url, workdir, n, offset, log):
    """YouTube chat replay -> per-second msg counts (best effort)"""
    try:
        for f in glob.glob(os.path.join(workdir, "chat*")): os.remove(f)
        run(["yt-dlp", "--skip-download", "--write-subs", "--sub-langs", "live_chat", "-o", os.path.join(workdir, "chat.%(ext)s"), url], None, check=False)
        files = glob.glob(os.path.join(workdir, "chat*live_chat*"))
        if not files: return None
        cnt = [0] * n
        for line in open(files[0], errors="ignore"):
            try: d = json.loads(line)
            except Exception: continue
            for a in d.get("replayChatItemAction", {}).get("actions", []):
                if "addChatItemAction" in a:
                    ms = d["replayChatItemAction"].get("videoOffsetTimeMsec")
                    if ms is not None:
                        i = int(int(ms) / 1000 - offset)
                        if 0 <= i < n: cnt[i] += 1
        if sum(cnt) < 20: return None
        log(f"YouTube chat replay: {sum(cnt)} messages")
        return cnt
    except Exception as e:
        log(f"(no chat replay: {e})"); return None

def heat_series(heatmap, n, offset):
    if not heatmap: return None
    out = [0.0] * n
    for h in heatmap:
        for t in range(int(h["start_time"]), int(h["end_time"]) + 1):
            i = t - int(offset)
            if 0 <= i < n: out[i] = h["value"]
    return out

import urllib.request, urllib.error

import threading
LLM_LOCK = threading.Lock()   # the laptop GPU answers one request at a time: queue here instead of timing out there

def chat_json(prompt, temp=.3, timeout=240, max_tokens=320):
    """one JSON reply from the Ollama model (OLLAMA_HOST / OLLAMA_MODEL); thinking mode switched off for qwen3-style models"""
    host = os.environ.get("OLLAMA_HOST", ""); host = host if host.startswith("http") else ("http://" + host if host else "")
    if not host: raise RuntimeError("no LLM host")
    model = os.environ.get("OLLAMA_MODEL", "gemma4:12b")
    body = {"model": model, "stream": False, "format": "json", "options": {"temperature": temp, "num_predict": max_tokens}, "messages": [{"role": "user", "content": prompt}]}
    with LLM_LOCK:
        for attempt in range(2):
            for think in ((False, None) if model.startswith(("qwen3", "gemma4")) else (None,)):
                b = dict(body)
                if think is not None: b["think"] = think
                try:
                    req = urllib.request.Request(host + "/api/chat", json.dumps(b).encode(), {"Content-Type": "application/json"})
                    return json.loads(json.loads(urllib.request.urlopen(req, timeout=timeout).read())["message"]["content"])
                except urllib.error.HTTPError:
                    continue
                except (TimeoutError, OSError):
                    break
    raise RuntimeError("LLM request failed")

EMO_HI = {"अरे","यार","भाई","क्या","वाह","ओह","अबे","देखो","रुको","भागो","पागल","कमाल","ज़बरदस्त","जबरदस्त","मस्त","गजब","ग़ज़ब","नहीं","बाप","हे","ओए","बचाओ","मारो","अरे",
          "arre","yaar","bhai","kya","wah","oye","abe","dekho","ruko","bhago","pagal","kamaal","zabardast","mast","gajab","nahi","bachao","maro"}
TOPIC_HI = {"गाड़ी","गाडी","पुलिस","गोली","हेलीकॉप्टर","चोरी","डकैती","ग्राफिक्स","मैप","जीटीए","मिशन","बैंक","नाव","gaadi","police","goli","chori","dakaiti","gta","mission","bank"}
EMO = {"oh","wow","omg","god","holy","insane","crazy","unbelievable","wait","dude","bro","damn","whoa","what","no","help",
       "scream","dead","lol","haha","run","yes","nooo","stop","look","seriously","literally","never","first","finally","huge","biggest"}
TOPIC = {"gta","rockstar","vice","city","leonida","lucia","jason","police","cops","helicopter","car","crash","chase","heist","shoot",
         "graphics","trailer","map","physics","npc","launch","mission","wanted","boat","bank","robbery","explosion","ragdoll"}
BAD_RE = re.compile(r"(fuck|shit|bitch|cunt|dick|asshole|nigg|retard|madarchod|bhenchod|behenchod|chutiya|gaand|harami|मादरचोद|भोसड़ी|भोसडी|चूतिया|बहनचोद|गांड|हरामी)", re.I)


ASR_URL = os.environ.get("ASR_URL", "http://127.0.0.1:8770")
def asr_call(path, timeout=300):
    """Qwen3-ASR service on this Mac (auto language, handles Hindi<->English switching). None if it isn't up -> callers fall back to whisper.cpp"""
    try:
        if not json.loads(urllib.request.urlopen(ASR_URL + "/health", timeout=1).read()).get("ready"): return None
        req = urllib.request.Request(ASR_URL + "/transcribe", json.dumps({"path": path, "language": None}).encode(), {"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=timeout).read()); return d if d.get("words") is not None else None
    except Exception: return None

def _segments_from_words(words, start):
    segs, cur = [], []
    for w in words:
        if cur and (w["s"] - cur[-1]["e"] > 0.8 or len(cur) >= 14): segs.append(cur); cur = []
        cur.append(w)
        if re.search(r"[.!?।]$", w["w"]): segs.append(cur); cur = []
    if cur: segs.append(cur)
    return [{"s": max(start, 0) + c[0]["s"], "e": max(start, 0) + c[-1]["e"], "t": " ".join(x["w"] for x in c)} for c in segs]

def _whisper(seg, base, lang, start):
    subprocess.run(["whisper-cli", "-m", MODEL, "-f", seg, "-oj", "-np", "-of", base] + (["-l", lang] if MULTI else []), capture_output=True)
    try: d = json.load(open(base + ".json"))
    except Exception: return [], None
    out = []
    for x in d.get("transcription", []):
        t = x["text"].strip()
        if not t: continue
        o = {"s": max(start, 0) + x["offsets"]["from"] / 1000, "e": max(start, 0) + x["offsets"]["to"] / 1000, "t": t}
        if re.fullmatch(r"[\[\(].*[\]\)]", t): o["tag"] = True
        out.append(o)
    try: return out, d["result"]["language"]
    except Exception: return out, None

def transcribe_segments(wav, start, dur, tmp, lang=None, game=True):
    """whisper.cpp (Metal GPU) -> [{s,e,t}] with absolute times. One pass in the chosen language (the streamer), plus - when that language is not English -
    a second English pass that picks up the GAME's own dialogue (GTA is spoken in English); those lines are tagged game=True and never overlap the streamer's."""
    seg = os.path.join(tmp, "seg.wav"); base = os.path.join(tmp, "seg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(max(start, 0)), "-t", str(dur), "-i", wav, "-ac", "1", "-ar", "16000", seg])
    q = asr_call(seg)
    if q and q["words"]:
        if q.get("language"): LAST_LANG["code"] = {"Hindi": "hi", "English": "en"}.get(q["language"], q["language"])
        return _segments_from_words(q["words"], start)
    main_lang = lang or os.environ.get("WHISPER_LANG") or "auto"
    main, det = _whisper(seg, base, main_lang, start)
    if det: LAST_LANG["code"] = det
    if MULTI and game and main_lang not in ("auto", "en") or (MULTI and game and main_lang == "auto" and det not in (None, "en")):
        eng, _ = _whisper(seg, base + "_en", "en", start)
        for g in eng:
            if g.get("tag"): continue
            txt = g["t"]; words = re.findall(r"[A-Za-z']+", txt)
            if len(words) < 3 or sum(ord(c) > 127 for c in txt) > 0.2 * len(txt) or len(set(w.lower() for w in words)) < 0.5 * len(words): continue   # not real English / a loop
            dur_g = max(g["e"] - g["s"], 0.1)
            ov = sum(max(0.0, min(g["e"], m["e"]) - max(g["s"], m["s"])) for m in main if not m.get("tag"))
            if ov / dur_g < 0.4: g["game"] = True; main.append(g)
        main.sort(key=lambda x: x["s"])
    return main

def virality_features(segs, ws, we, peak):
    """cheap, explainable signals from the transcript of the window [ws,we] around peak"""
    inw = [g for g in segs if g["e"] > ws and g["s"] < we]
    text = " ".join(("🎮 " + g["t"]) if g.get("game") else g["t"] for g in inw if not g.get("tag"))
    words = re.findall(r"[\u0900-\u097F]+|[a-z']+", text.lower())
    f, why, warn = 0.0, [], []
    if not words: return 0.0, [], [], text
    first = " ".join(g["t"] for g in inw[:2]).lower()
    if "?" in first or "!" in first or any((w in EMO or w in EMO_HI) for w in re.findall(r"[\u0900-\u097F]+|[a-z']+", first)): f += .6; why.append("strong opening hook")
    emo = sum((w in EMO or w in EMO_HI) for w in words) + .6 * text.count("!")
    if emo >= 3: f += min(emo * .15, 1.2); why.append("high emotion")
    if any(g.get("tag") and re.search(r"laugh|giggl|cheer|applau|scream", g["t"], re.I) for g in inw) or re.search(r"\b(ha){2,}|lmao|lol\b|हाहा|हा हा|हंस", text.lower()):
        f += .8; why.append("laughter/reaction")
    near = [g for g in inw if abs((g["s"] + g["e"]) / 2 - peak) < 6]; nw = sum(len(g["t"].split()) for g in near)
    rate_all = len(words) / max(we - ws, 1)
    if near and nw / 12 > 1.5 * rate_all and nw > 12: f += .5; why.append("speech burst at the peak")
    gaps = [b["s"] - a["e"] for a, b in zip(inw, inw[1:])]
    if gaps and max(gaps) > 2.5: f += .3; why.append("silence-then-reaction")
    tp = sum((w in TOPIC or w in TOPIC_HI) for w in words)
    if tp >= 2: f += min(.25 * tp, .8); why.append("GTA-relevant")
    if BAD_RE.search(text): warn.append("strong language (masked in captions; spoken audio may limit ads)")
    if len(words) < 12: f -= .6; why.append("little speech") if False else None
    return f, [w for w in why if w], warn, text

def snap(segs, peak, total):
    """cut on sentence/segment boundaries: start ~14-20 s before the peak, end ~10-14 s after, 20-45 s long"""
    starts = [g["s"] for g in segs if peak - 20 <= g["s"] <= peak - 8]
    st = min(starts) if starts else max(peak - 16, 0)
    ends = [g["e"] for g in segs if peak + 8 <= g["e"] <= peak + 16]
    en = max(ends) if ends else peak + 12
    dur = min(max(en - st, 22), 44)
    return round(st, 1), round(dur, 1)

def llm_rerank(cands, log):
    """Optional: local LLM (Ollama, GPU) judges virality. OLLAMA_HOST=http://<ubuntu-ip>:11434 uses the Ubuntu laptop."""
    host = os.environ.get("OLLAMA_HOST", ""); host = host if host.startswith("http") else "http://" + host
    model = os.environ.get("OLLAMA_MODEL", "gemma4:12b")
    if not host or host == "http://": log("(no LLM host set; heuristic virality only)"); return False
    try: urllib.request.urlopen(host + "/api/tags", timeout=3).read()
    except Exception: log("(no local LLM found; using heuristic virality only)"); return False
    log(f"Asking {model} to judge virality ...")
    items = [{"id": i, "transcript": c["text"][:700]} for i, c in enumerate(cands) if c["text"]]
    prompt = ("You pick viral YouTube Shorts from livestream clips (mostly GTA 6 / gaming; judge only what the transcript shows; a line marked with a game emoji is the game's own dialogue). "
              "For EACH transcript give FOUR scores from 0 to 10, using the whole range: "
              "hook (is there a strong, curious or funny opening in the first 2 seconds), energy (real emotion: shock, panic, laughter, hype), "
              "clarity (can a stranger follow it without context), payoff (a clear surprise, fail, joke or impressive moment happens). "
              "Anchors: 9-10 = clip you would post immediately (e.g. 'I just stole a helicopter and the cops are on me, no way!'); 5-6 = okay but slow; "
              "0-2 = menu talk, thanking viewers, silence-filler ('mm hmm', 'one second'). Do not cluster scores: if one part is great and another weak, say so. "
              "Also write a punchy, honest title (<=55 chars) and a short hook line (on-screen text). WRITE the title and hook in the SAME LANGUAGE as the transcript "
              "(Hindi in Devanagari; keep game words like GTA in English). Never mention a game or person that is not in the transcript. "
              "Reply ONLY JSON: {\"clips\":[{\"id\":0,\"hook_s\":0,\"energy_s\":0,\"clarity_s\":0,\"payoff_s\":0,\"title\":\"\",\"hook\":\"\",\"reason\":\"one short English sentence\"}]}\n\n" + json.dumps(items))
    try:
        data = chat_json(prompt, .5, 240, 420)
        for x in data.get("clips", []):
            try: c = cands[int(x["id"])]
            except Exception: continue
            parts = [float(x[k]) for k in ("hook_s", "energy_s", "clarity_s", "payoff_s") if isinstance(x.get(k), (int, float))]
            c["llm_parts"] = parts
            c["llm"] = round(sum(parts) / len(parts), 1) if parts else float(x.get("virality", 0)); c["reason"] = x.get("reason", "")
            if x.get("title"): c["title"] = x["title"][:70]
            if x.get("hook"): c["hook"] = x["hook"][:80]
        return True
    except Exception as e:
        log(f"(LLM step skipped: {str(e)[:80]})"); return False

def pick_peaks(score, top, gap=45):
    order = sorted(range(len(score)), key=lambda i: -score[i]); out = []
    for i in order:
        if score[i] <= 0: break
        if all(abs(i - j) >= gap for j in out): out.append(i)
        if len(out) >= top: break
    return out

def suggest_title(text, uploader):
    sents = [x.strip() for x in re.split(r"(?<=[.!?।])\s+", text) if len(x.strip()) > 8]
    pick = next((x for x in sents if "!" in x or "?" in x), sents[0] if sents else "")
    if pick and len(pick) <= 55: return f"\"{pick}\" - {uploader or 'streamer'}"
    return f"This moment was wild ({uploader or 'streamer'})"

def analyze_audio_file(wav, info, offset, url, workdir, log, top=8, chat_cnt=None, use_heat=True, visual_fn=None, lang=None):
    log("Measuring loudness ...")
    db = loudness_series(wav); n = len(db)
    if n < 30: raise RuntimeError("audio too short to analyse")
    a, rise, sm = audio_scores(db)
    fused = list(a); src = {"audio": a}
    heat = heat_series(info.get("heatmap"), n, offset) if use_heat else None
    chat = chat_cnt
    if url and chat is None and "youtube" in info["extractor"] and not info["is_live"]:
        chat = yt_chat_series(url, workdir, n, offset, log)
    if heat:
        h = zs(heat); fused = [f + .8 * max(x, 0) for f, x in zip(fused, h)]; src["heat"] = h; log("Using YouTube 'most replayed' heatmap")
    if chat:
        c = zs([statistics.mean(chat[max(0, i-2):i+3]) for i in range(n)]); fused = [f + max(x, 0) for f, x in zip(fused, c)]; src["chat"] = c
    fused = [statistics.mean(fused[max(0, i-1):i+2]) for i in range(n)]
    peaks = pick_peaks(fused, max(top * 2, 12), gap=40)
    if n <= 50: peaks = peaks[:1] or [n // 2]
    tmp = os.path.join(workdir, "tx"); os.makedirs(tmp, exist_ok=True)
    cands = []
    for k, p in enumerate(peaks, 1):
        log(f"Reading moment {k}/{len(peaks)} (speech-to-text on GPU) ...")
        ws0 = max(0, p - 50)
        segs = transcribe_segments(wav, ws0, 110, tmp, lang) if os.path.exists(MODEL) else []
        st, dur = snap(segs, p, n)
        if n <= 50: st, dur = 0, min(n, 45)   # source is already a short clip: keep all of it
        f, why, warn, text = virality_features(segs, st, st + dur, p)
        sig = []
        if src["audio"][p] > 1: sig.append(f"audio jump {rise[p]:+.0f} dB")
        if "heat" in src and src["heat"][p] > .5: sig.append("most-replayed section")
        if "chat" in src and src["chat"][p] > 1: sig.append("chat burst")
        cands.append({"peak": p + offset, "start": st + offset, "dur": dur, "heur": round(fused[p] + f, 2), "why": (sig + why) or ["loudness peak"],
                      "warn": warn, "text": text[:600], "title": suggest_title(text, info.get("uploader"))})
    if visual_fn:   # AI tracking: motion / scene-change bursts from the actual video (OpenCV), blended with audio+speech
        import visual
        ms = []
        for k, c in enumerate(cands, 1):
            log(f"Watching moment {k}/{len(cands)} (motion + scene changes) ...")
            try:
                v = visual_fn(c["start"], c["dur"]); m = visual.window_metrics(v) if v else None
            except Exception as e:
                m = None
            c["vis"] = m; ms.append(m)
        ok = [m for m in ms if m]
        if ok:
            mo = [m["motion"] for m in ok]; bu = [m["bursts"] for m in ok]
            zm = zs(mo) if len(ok) > 1 else [0]; zb = zs([float(b) for b in bu]) if len(ok) > 1 else [0]
            i = 0
            for c in cands:
                if not c.get("vis"): continue
                v = max(-1.0, min(1.0, .5 * (.6 * zm[i] + .4 * zb[i])))
                if c["vis"]["static"] > .7: v -= .4; c["why"].append("mostly static picture")
                elif c["vis"]["motion"] > 15 and c["vis"]["bursts"] >= 3: c["why"].append("high-action visuals")
                c["heur"] = round(c["heur"] + v, 2); i += 1
    used = llm_rerank(cands, log)
    for c in cands:
        c["score"] = round(c["heur"] + (c.get("llm", 5) - 5) * .5 if used else c["heur"], 2)
        c["virality"] = round(c["llm"], 1) if "llm" in c else None
        if c.get("reason"): c["why"].append(c["reason"])
    cands.sort(key=lambda c: -c["score"])
    return cands[:top], sm


def llm_meta(text, streamer, link, log=lambda m: None):
    """Viral-style but honest title/description/tags for a Short, from the transcript, via the local LLM. Returns dict or None."""
    host = os.environ.get("OLLAMA_HOST", ""); host = host if host.startswith("http") else ("http://" + host if host else "")
    model = os.environ.get("OLLAMA_MODEL", "gemma4:12b")
    if not host or not text: return None
    prompt = ("Write YouTube Shorts metadata for a ~40 s gaming clip (GTA 6 launch week) from streamer '%s'. Transcript: \"%s\"\n"
              "Rules: title <= 60 chars, curiosity hook, one emoji max, no lies/clickbait about things not in the transcript, no spoilers of story twists, "
              "no profanity. Write in the SAME LANGUAGE as the transcript (Hindi transcript -> Hindi in Devanagari, keep game words like GTA in English; tags can mix Hindi and English). Description: 2 short punchy lines + a question that invites comments. 8 tags, lowercase. "
              "Reply ONLY JSON {\"title\":\"\",\"description\":\"\",\"tags\":[\"\"]}") % (streamer, text[:900])
    try:
        d = chat_json(prompt, .6, 120)
        return {"title": str(d.get("title", ""))[:70], "description": str(d.get("description", "")), "tags": [str(t) for t in d.get("tags", [])][:10]}
    except Exception as e:
        log(f"(meta LLM failed: {str(e)[:60]})"); return None
