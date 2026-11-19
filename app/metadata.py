"""Accurate metadata from the FINISHED edit: verified topic/game, detected language, resolved creator, specific title, honest description.
It never assumes a launch week, a game, a language, permission or commentary that the inputs do not support."""
import re
import analyze as A

BANNED_TITLE = ("you won't believe", "you wont believe", "wait for it", "this moment was wild", "must watch", "गजब", "unbelievable moment")
GTA_RE = re.compile(r"\bGTA\s*(?:6|VI)\b|Grand\s+Theft\s+Auto\s*(?:6|VI)\b", re.I)

def detect_language(text):
    """'hi' (Devanagari-dominant / Hindi-English mix), 'en', or 'unknown' when there are too few letters to tell"""
    dev = len(re.findall(r"[ऀ-ॿ]", text or "")); lat = len(re.findall(r"[A-Za-z]", text or ""))
    if dev + lat < 8: return "unknown"
    return "hi" if dev / (dev + lat) > 0.35 else "en"

def resolve_topic(user_game=None, stream_title=None, transcript=None):
    """-> {"game": name|None, "verified": bool, "evidence": str}. Only the user's explicit setting or the stream's own title can VERIFY a game."""
    if user_game and user_game.strip(): return {"game": user_game.strip(), "verified": True, "evidence": "set by the user"}
    if stream_title and GTA_RE.search(stream_title): return {"game": "GTA 6", "verified": True, "evidence": f"stream title: {stream_title[:80]}"}
    note = "transcript mentions GTA (unverified: not used for labels)" if transcript and GTA_RE.search(transcript) else "unknown"
    return {"game": None, "verified": False, "evidence": note}

def resolve_creator(live_channel=None, info=None):
    info = info or {}; name = live_channel or info.get("uploader") or info.get("channel")
    return {"name": name or None, "url": info.get("channel_url") or None, "known": bool(name)}

def tags_and_hashtags(topic, lang, extra=()):
    tags, hs = [], ["#Shorts"]
    if topic["verified"] and topic["game"] and "GTA" in topic["game"].upper():
        tags += ["GTA6", "GTA 6", "Grand Theft Auto VI"]; hs.append("#GTA6")
    elif topic["verified"] and topic["game"]:
        g = re.sub(r"[^A-Za-z0-9]", "", topic["game"]); tags.append(topic["game"]); hs.append("#" + g) if g else None
    else:
        hs.append("#Gaming")                    # unknown game: neutral, never GTA6 by guess
    if lang == "hi": tags += ["Hindi gaming"]; hs.append("#HindiGaming")
    for x in extra:
        x = str(x).strip()
        if x and x.lower() not in {t.lower() for t in tags} and len(tags) < 14: tags.append(x[:40])
    return tags, hs[:5]

def source_link(url, platform_id=None, source_ts=None):
    """link with the SOURCE-relative time when the platform supports it (never the wall-clock display time)"""
    if not url: return ""
    if source_ts is None: return url
    t = int(source_ts)
    if "youtube.com" in url or "youtu.be" in url: return url + ("&" if "?" in url else "?") + f"t={t}s"
    if "twitch.tv/videos/" in url: return url.split("?")[0] + f"?t={t//3600}h{t%3600//60}m{t%60}s"
    return url

def title_ok(title, lang):
    if not title or not 6 <= len(title) <= 80: return False
    if any(b in title.lower() for b in BANNED_TITLE): return False
    if lang == "hi" and detect_language(title) == "en" and not re.search(r"[ऀ-ॿ]", title): return False   # Hindi clip, English-only title
    return True

def fallback_title(plan, lang):
    wh = (plan.get("what_happens") or "").strip().rstrip(".")
    if wh: return wh[:70]
    q = ((plan.get("evidence") or {}).get("payoff") or {}).get("quote")
    return (q or ("हिंदी गेमिंग मोमेंट" if lang == "hi" else "Gaming moment"))[:70]

def llm_title(plan, selected_text, lang, topic, creator, chat=None):
    """specific title + summary from the SELECTED edit (full text, not a truncated source transcript). Returns (title, summary_lines) or (None, None)"""
    if len((selected_text or "").split()) < 3: return None, None          # nothing was said (or no transcript): a model title would be invented from nothing
    chat = chat or A.chat_json
    prompt = ("Write YouTube Shorts metadata for this finished edit. "
              f"Language of the clip: {'Hindi (write in Devanagari, keep game/brand words in English)' if lang == 'hi' else 'English' if lang == 'en' else 'same as the transcript'}. "
              f"Game/topic: {topic['game'] if topic['verified'] else 'unknown (do not guess a game)'}. Creator: {creator['name'] or 'unknown'}.\n"
              f"What happens (editor's note): {plan.get('what_happens') or 'n/a'}\nPayoff line: {((plan.get('evidence') or {}).get('payoff') or {}).get('quote') or 'n/a'}\n"
              f"Selected transcript:\n{selected_text}\n\n"
              "Rules: the title (max 70 chars) must state the SPECIFIC event that actually happens; no 'you won't believe', no 'wait for it', no invented outcome, no claims "
              "about launch week, permission, ownership or who is affiliated. summary = 1-2 plain sentences on what happens, then one genuine question for viewers. "
              'Reply ONLY JSON: {"title":"","summary":["",""]}')
    try:
        d = chat(prompt, 0.4, 120, 300)
        t = str(d.get("title") or "").strip(); s = [str(x).strip() for x in (d.get("summary") or []) if str(x).strip()][:3]
        return (t, s) if title_ok(t, lang) and s else (None, None)
    except Exception: return None, None

def build_metadata(ctx, chat=None):
    """ctx: plan, selected_text, lang, topic, creator, source_url, source_ts, extra_tags -> {title, description, tags, hashtags, language, topic, creator, notes}"""
    plan, text = ctx["plan"], ctx["selected_text"]
    lang = ctx.get("lang") or detect_language(text); topic = ctx["topic"]; creator = ctx["creator"]; notes = []
    title, summary = llm_title(plan, text, lang, topic, creator, chat)
    if not title: title = fallback_title(plan, lang); summary = [plan.get("what_happens") or title]; notes.append("title/summary from the editor note (model unavailable or rejected)")
    tags, hashtags = tags_and_hashtags(topic, lang, ctx.get("extra_tags", ()))
    link = source_link(ctx.get("source_url"), None, ctx.get("source_ts"))
    lines = list(summary)
    if link: lines += ["", ("Source stream: " + link) if not creator["known"] else f"Clip from {creator['name']}'s stream: {link}"]
    if creator["known"]: lines.append(f"Credit: {creator['name']}" + (f" ({creator['url']})" if creator.get("url") else ""))
    if topic["verified"] and topic["game"] and "GTA" in topic["game"].upper(): lines.append("Not affiliated with Rockstar Games / Take-Two.")
    lines += ["", " ".join(hashtags)]
    if not topic["verified"]: notes.append("game/topic not verified: neutral wording and #Gaming used")
    if not creator["known"]: notes.append("creator unknown: credited as 'Source stream'")
    return {"title": title, "description": "\n".join(lines), "tags": tags, "hashtags": hashtags, "language": lang, "topic": topic, "creator": creator, "notes": notes}
