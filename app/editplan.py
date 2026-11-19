"""Edit planner core: validated, speech-safe, chronological edit plans from a full word transcript. Pure functions (no network, no ffmpeg) so they can be unit-tested.
A plan: {"decision": accept|review|reject, "segments": [{"start","end","role","note"}], "opening_text", "payoff_time", "scores": {hook,clarity,payoff,energy},
         "evidence": {"opening": {"t","quote"}, "payoff": {"t","quote"}}, "what_happens", "why_care", "reasons": [...], ...}   (all times: SOURCE-relative seconds)"""
import json, math, re

class PlanError(ValueError):
    """a plan or LLM answer that cannot be trusted"""

def finite(x): return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)

# ---------- words ----------
def clean_words(words):
    """keep only well-formed words {w,s,e} with finite, ordered times; preserves the originals untouched elsewhere"""
    out = []
    for x in words or []:
        if not isinstance(x, dict) or not str(x.get("w", "")).strip(): continue
        s, e = x.get("s"), x.get("e")
        if not (finite(s) and finite(e)) or s < 0 or e < s: continue
        out.append({"w": str(x["w"]).strip(), "s": float(s), "e": float(e)})
    out.sort(key=lambda w: w["s"]); return out

def sentences(words, gap=0.8, max_words=18):
    """group words into sentence-like units: [{s,e,text,i0,i1}]"""
    out, cur = [], []
    def flush():
        if cur: out.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(w["w"] for w in cur), "i0": cur[0]["_i"], "i1": cur[-1]["_i"]})
    for i, w in enumerate(words):
        w = dict(w, _i=i)
        if cur and (w["s"] - cur[-1]["e"] > gap or len(cur) >= max_words): flush(); cur.clear()
        cur.append(w)
        if re.search(r"[.!?।…]$", w["w"]): flush(); cur.clear()
    flush(); return out

def transcript_lines(words, max_chars=24000):
    """the COMPLETE transcript as timestamped lines for the planner (never silently truncated: the caller learns if it had to be)"""
    lines = [f"[{u['s']:.1f}-{u['e']:.1f}] {u['text']}" for u in sentences(words)]
    text = "\n".join(lines)
    return text, len(text) > max_chars

# ---------- validation ----------
def validate_time(t, duration, name="time", eps=0.05):
    if not finite(t): raise PlanError(f"{name} is not a finite number: {t!r}")
    if t < -eps or t > duration + eps: raise PlanError(f"{name} {t} outside the media (0-{duration:.2f})")
    return min(max(float(t), 0.0), float(duration))

def repair_segments(segs):
    """sort by start and merge overlapping/touching segments (a model often lists them out of order or overlapping). Reversed/empty/non-finite ones are NOT repaired:
    they still raise in validate_segments. -> (segments, repaired?)"""
    if not isinstance(segs, list) or not segs or not all(isinstance(g, dict) and finite(g.get("start")) and finite(g.get("end")) and g["end"] > g["start"] for g in segs): return segs, False
    srt = sorted((dict(g) for g in segs), key=lambda g: g["start"]); out = [srt[0]]
    for g in srt[1:]:
        if g["start"] <= out[-1]["end"] + 0.05: out[-1]["end"] = max(out[-1]["end"], g["end"]); out[-1]["note"] = (out[-1].get("note") or "") + " (merged)"
        else: out.append(g)
    return out, out != segs

def validate_segments(segs, duration, cfg):
    """ordered, non-overlapping, inside the media, total length inside [min_len, max_len]"""
    if not finite(duration) or duration <= 0: raise PlanError(f"bad media duration {duration!r}")
    if not isinstance(segs, list) or not segs: raise PlanError("plan has no segments")
    out, prev_end = [], 0.0
    for i, g in enumerate(segs):
        if not isinstance(g, dict): raise PlanError(f"segment {i} is not an object")
        s = validate_time(g.get("start"), duration, f"segment {i} start"); e = validate_time(g.get("end"), duration, f"segment {i} end")
        if e <= s: raise PlanError(f"segment {i} is reversed or empty ({s}-{e})")
        if s < prev_end - 1e-6: raise PlanError(f"segment {i} overlaps or is out of order")
        out.append({"start": round(s, 3), "end": round(e, 3), "role": str(g.get("role") or "full"), "note": str(g.get("note") or "")}); prev_end = e
    total = sum(g["end"] - g["start"] for g in out)
    lo, hi = cfg["edit"]["min_len"], cfg["edit"]["max_len"]
    if total < lo - 1e-6: raise PlanError(f"edit is {total:.1f}s, shorter than the minimum {lo}s")
    if total > hi + 1e-6: raise PlanError(f"edit is {total:.1f}s, longer than the maximum {hi}s")
    return out

# ---------- speech-safe boundaries ----------
def snap_start(words, t, cfg, duration):
    """a cut that begins at t must not land inside a word: move to the word's start (minus pre-roll), else keep t but leave pre-roll room inside silence"""
    pre = cfg["edit"]["pre_roll"]
    for i, w in enumerate(words):
        if w["s"] < t < w["e"]:                          # inside a word -> begin just before it
            prev_end = words[i - 1]["e"] if i else 0.0
            return max(min(max(w["s"] - pre, prev_end + 0.02), w["s"]), 0.0)      # never later than the word's own start
    nxt = next((w for w in words if w["s"] >= t), None)
    if nxt and nxt["s"] - t < pre:                       # a word starts right after the cut: give it room
        prev_end = max((w["e"] for w in words if w["e"] <= nxt["s"]), default=0.0)
        return max(min(max(nxt["s"] - pre, prev_end + 0.02), nxt["s"]), 0.0)
    return max(t, 0.0)

def snap_end(words, t, cfg, duration):
    """a cut that ends at t must not land inside a word: extend to the word's end (plus post-roll, never into the next word)"""
    post = cfg["edit"]["post_roll"]
    for i, w in enumerate(words):
        if w["s"] < t < w["e"]:
            nxt = words[i + 1]["s"] if i + 1 < len(words) else duration
            return min(w["e"] + post, max(nxt - 0.02, w["e"]), duration)
    prev = max((w for w in words if w["e"] <= t), key=lambda w: w["e"], default=None)
    if prev and t - prev["e"] < post:                    # ended right after a word: let it ring out
        nxt = next((w["s"] for w in words if w["s"] > prev["e"]), duration)
        return min(prev["e"] + post, max(nxt - 0.02, prev["e"]), duration)
    return min(t, duration)

def snap_segments(segs, words, cfg, duration):
    out = []
    for g in segs:
        s = snap_start(words, g["start"], cfg, duration); e = snap_end(words, g["end"], cfg, duration)
        if e > s: out.append(dict(g, start=round(s, 3), end=round(e, 3)))
    return out

def boundary_report(segs, words):
    """list every word that a boundary cuts through (empty = speech-safe)"""
    bad = []
    for g in segs:
        for t, kind in ((g["start"], "start"), (g["end"], "end")):
            for w in words:
                if w["s"] + 1e-3 < t < w["e"] - 1e-3: bad.append({"segment_boundary": kind, "t": t, "word": w["w"]})
    return bad

# ---------- timeline + caption remapping ----------
def segment_offsets(segs):
    off, acc = [], 0.0
    for g in segs: off.append(acc); acc += g["end"] - g["start"]
    return off, acc

def remap_words(words, segs):
    """source-relative words -> edited-timeline words, using the SAME segment map the renderer uses. Words that straddle a cut are dropped (and counted)."""
    offs, total = segment_offsets(segs); out, dropped = [], 0
    for w in words:
        for g, o in zip(segs, offs):
            if w["s"] >= g["start"] - 1e-3 and w["e"] <= g["end"] + 1e-3:
                out.append({"w": w["w"], "s": round(w["s"] - g["start"] + o, 3), "e": round(w["e"] - g["start"] + o, 3)}); break
        else:
            if any(min(w["e"], g["end"]) - max(w["s"], g["start"]) > 1e-3 for g in segs): dropped += 1
    return out, dropped

def selected_transcript(words, segs):
    return " ".join(w["w"] for w in words if any(w["s"] >= g["start"] - 1e-3 and w["e"] <= g["end"] + 1e-3 for g in segs))

# ---------- scoring / decision ----------
SCORE_KEYS = ("hook", "clarity", "payoff", "energy")
def read_scores(raw):
    """validate named scores: all four present, finite, 0-10. Missing/invalid -> PlanError (the candidate stays unreviewed, never a neutral default)"""
    if not isinstance(raw, dict): raise PlanError("scores missing")
    out = {}
    for k in SCORE_KEYS:
        v = raw.get(k)
        if not finite(v) or not 0 <= v <= 10: raise PlanError(f"score '{k}' missing or outside 0-10: {v!r}")
        out[k] = round(float(v), 1)
    return out

def editorial_quality(scores):
    """0-10. Energy is deliberately NOT part of it, and the result can never exceed (weakest of hook/clarity/payoff) + 2:
    a loud, exciting clip with a confusing setup or no ending does not score well."""
    core = [scores["hook"], scores["clarity"], scores["payoff"]]
    return round(min(sum(core) / 3, min(core) + 2.0), 1)

def gate(scores, cfg):
    """-> (state, reasons) from independent thresholds: pass | needs_review | rejected"""
    th = cfg["thresholds"]; reasons, worst = [], "pass"
    for k in ("hook", "clarity", "payoff"):
        v, t = scores[k], th[k]
        if v < t - th["review_margin"]: reasons.append(f"{k} {v} is far below {t}"); worst = "rejected"
        elif v < t:
            reasons.append(f"{k} {v} below {t}")
            if worst != "rejected": worst = "needs_review"
    return worst, reasons

# ---------- LLM answer -> plan ----------
def _norm(t):   # keep Devanagari letters AND their vowel signs (\w alone would split Hindi words at every matra)
    return re.sub(r"[^\w\s\u0900-\u097F]", " ", t.lower()).split()
def quote_in(words, quote, t_lo, t_hi):
    """does the quoted text really occur in the transcript inside [t_lo, t_hi]? (fuzzy: all quote words appear in order)"""
    q = _norm(quote or "")
    if not q: return False
    span = [_norm(w["w"]) for w in words if w["e"] >= t_lo and w["s"] <= t_hi]; flat = [x for xs in span for x in xs]
    i = 0
    for tok in flat:
        if tok == q[i]:
            i += 1
            if i == len(q): return True
    return False

def parse_llm_plan(raw, words, duration, cfg):
    """Validate the planner model's JSON. Raises PlanError for anything malformed/partial. Returns a plan dict (decision may still be review/reject)."""
    if not isinstance(raw, dict): raise PlanError("planner answer is not a JSON object")
    decision = raw.get("decision")
    if decision not in ("accept", "review", "reject"): raise PlanError(f"decision missing/invalid: {decision!r}")
    plan = {"decision": decision, "what_happens": str(raw.get("what_happens") or "")[:400], "why_care": str(raw.get("why_care") or "")[:400],
            "reasons": [str(x)[:200] for x in (raw.get("reasons") or []) if isinstance(x, (str, int, float))][:8], "planner": "llm"}
    if decision == "reject":
        plan["segments"] = []; plan["scores"] = None
        try: plan["scores"] = read_scores(raw.get("scores"))
        except PlanError: pass
        if not plan["reasons"]: plan["reasons"] = ["planner rejected the moment"]
        return plan
    segs = raw.get("segments")
    if segs is None and finite(raw.get("start")) and finite(raw.get("end")): segs = [{"start": raw["start"], "end": raw["end"]}]
    segs, repaired = repair_segments(segs)
    if repaired: plan["reasons"].append("segments were out of order/overlapping and were merged")
    segs = validate_segments(segs, duration, dict(cfg, edit=dict(cfg["edit"], min_len=0.1, max_len=1e9)))        # structural checks first
    words_c = clean_words(words)
    segs = snap_segments(segs, words_c, cfg, duration)
    segs = validate_segments(segs, duration, cfg)                                                            # then the real length limits
    segs, polish_notes = polish_segments(segs, words_c, cfg, duration); plan["reasons"] += polish_notes
    segs = validate_segments(segs, duration, cfg)
    if boundary_report(segs, words_c): raise PlanError("a boundary still cuts through a word")
    plan["segments"] = segs; plan["scores"] = read_scores(raw.get("scores"))
    ev = raw.get("evidence") or {}
    plan["evidence"] = {}
    lo, hi = segs[0]["start"], segs[-1]["end"]
    for key in ("opening", "payoff"):
        e = ev.get(key)
        if not isinstance(e, dict) or not finite(e.get("t")) or not str(e.get("quote") or "").strip(): raise PlanError(f"evidence for the {key} is missing (needs a timestamp and quote)")
        t = validate_time(e["t"], duration, f"{key} evidence time")
        if not (lo - 0.5 <= t <= hi + 0.5): raise PlanError(f"{key} evidence time {t} is outside the planned edit")
        plan["evidence"][key] = {"t": round(t, 2), "quote": str(e["quote"])[:200], "verified": quote_in(words_c, e["quote"], t - 1.5, t + 9)}
    if not plan["evidence"]["opening"]["verified"] or not plan["evidence"]["payoff"]["verified"]:
        plan["reasons"].append("the model's quoted opening/payoff could not be found in the transcript near its timestamp")
        if plan["decision"] == "accept": plan["decision"] = "review"
    plan["payoff_time"] = plan["evidence"]["payoff"]["t"]
    plan["time_to_payoff"] = round(plan["payoff_time"] - segs[0]["start"], 2)
    if plan["time_to_payoff"] > cfg["edit"]["max_time_to_payoff"]:
        plan["reasons"].append(f"the payoff arrives {plan['time_to_payoff']:.1f}s into the edit (limit {cfg['edit']['max_time_to_payoff']:.0f}s): cut more of the setup")
        plan["late_payoff"] = True
        if plan["decision"] == "accept": plan["decision"] = "review"
    ot = raw.get("opening_text"); plan["opening_text"] = (str(ot).strip()[:80] or None) if isinstance(ot, str) else None
    plan["editorial_quality"] = editorial_quality(plan["scores"])
    state, why = gate(plan["scores"], cfg); plan["gate"] = state; plan["reasons"] += why
    if state == "rejected": plan["decision"] = "reject"
    elif state == "needs_review" and plan["decision"] == "accept": plan["decision"] = "review"
    return plan

def polish_segments(segs, words, cfg, duration):
    """Light, speech-safe polish applied to a model plan: (1) drop 1-2 leading filler words (um/so/like/हम्म...) if they sit in the first `filler_trim_max` seconds;
    (2) if the last sentence is cut off, extend the end to finish it (at most `finish_sentence_max` s, never past the next segment or max_len).
    Returns (segments, notes). Never moves a boundary into a word; keeps min_len."""
    e = cfg["edit"]; fill = {str(x).lower() for x in e.get("fillers", [])}; notes = []; out = [dict(g) for g in segs]
    units = sentences(words)
    for k, g in enumerate(out):
        inside = [w for w in words if w["s"] >= g["start"] - 1e-6 and w["e"] <= g["end"] + 1e-6]
        trimmed = 0
        while trimmed < 2 and len(inside) > 3 and inside[0]["w"].strip(".,!?।…").lower() in fill and inside[0]["s"] - g["start"] < e["filler_trim_max"]:
            inside.pop(0); trimmed += 1
        if trimmed:
            ns = snap_start(words, inside[0]["s"], cfg, duration)
            if g["end"] - ns >= e["min_len"] and ns > g["start"]: notes.append(f"trimmed {trimmed} leading filler word(s) at {g['start']:.1f}s"); g["start"] = round(ns, 3)
        last = next((w for w in reversed(words) if w["e"] <= g["end"] + 1e-6 and w["s"] >= g["start"]), None)
        if last and not re.search(r"[.!?।…]$", last["w"]):
            u = next((u for u in units if u["s"] <= last["s"] <= u["e"]), None)
            limit = out[k + 1]["start"] - 0.05 if k + 1 < len(out) else duration
            if u and last["e"] < u["e"] <= g["end"] + e["finish_sentence_max"]:
                ne = snap_end(words, u["e"], cfg, duration)
                if ne <= limit and ne - g["start"] <= e["max_len"] and ne > g["end"]: notes.append(f"extended the end {ne - g['end']:.1f}s to finish the sentence"); g["end"] = round(ne, 3)
    return out, notes

def tighten(plan, words, cfg, duration):
    """Explicit, flagged tightening for a plan whose payoff comes too late: begin `tighten_lead` seconds before the payoff and stop `tighten_tail` seconds after it,
    both snapped to speech-safe points. It stays 'review' (a human decides whether the dropped setup mattered) and records exactly what it did."""
    e = cfg["edit"]; pt = plan.get("payoff_time")
    if not finite(pt) or not plan.get("segments"): return plan
    w = clean_words(words); first, last = plan["segments"][0]["start"], plan["segments"][-1]["end"]
    s0 = snap_start(w, max(pt - e["tighten_lead"], first), cfg, duration); e0 = snap_end(w, min(pt + e["tighten_tail"], last, duration), cfg, duration)
    if e0 - s0 < e["min_len"]: e0 = min(s0 + e["min_len"], duration); s0 = max(min(s0, e0 - e["min_len"]), 0.0)
    seg = validate_segments([{"start": s0, "end": e0, "role": "tightened", "note": f"auto-tightened: {e['tighten_lead']:.0f}s of setup before the payoff, {e['tighten_tail']:.0f}s of reaction after"}], duration, cfg)
    out = dict(plan, segments=seg, auto_tightened=True, time_to_payoff=round(pt - seg[0]["start"], 2), late_payoff=False, decision="review", original_segments=plan["segments"])
    out["reasons"] = [r for r in plan.get("reasons", []) if "into the edit (limit" not in r] + [f"auto-tightened from {plan['segments'][0]['start']:.1f}-{last:.1f}s to {seg[0]['start']:.1f}-{seg[0]['end']:.1f}s: confirm the dropped setup was not needed"]
    return out

# ---------- reliable fallback (no LLM): chronological, sentence-aligned, scored as UNKNOWN ----------
def heuristic_plan(words, peak, duration, cfg):
    """Used when the model is unavailable: a speech-safe window that starts at the sentence that begins the setup and ends after the reaction.
    It carries NO quality scores, so it can never be auto-approved."""
    w = clean_words(words); lo, hi = cfg["edit"]["min_len"], cfg["edit"]["max_len"]
    if not w: raise PlanError("no usable words: cannot plan (empty or failed speech recognition)")
    sents = sentences(w)
    k = next((i for i, u in enumerate(sents) if u["s"] <= peak <= u["e"] + 1.0), None)
    if k is None: k = min(range(len(sents)), key=lambda i: abs(sents[i]["s"] - peak))
    a = k
    while a > 0 and sents[k]["e"] - sents[a - 1]["s"] <= 14 and sents[a]["s"] - sents[a - 1]["e"] < 1.5: a -= 1      # up to ~14 s of connected setup
    b = k
    while b + 1 < len(sents) and sents[b + 1]["s"] - sents[b]["e"] < 1.5 and sents[b + 1]["e"] - sents[a]["s"] <= hi: b += 1
    s, e = sents[a]["s"], sents[b]["e"] + 0.6
    if e - s < lo: e = min(s + lo, duration); s = max(min(s, e - lo), 0.0)
    segs = snap_segments([{"start": max(s - 0.2, 0), "end": min(e, duration), "role": "full", "note": "sentence-aligned window around the detected peak"}], w, cfg, duration)
    segs = validate_segments(segs, duration, cfg)
    return {"decision": "review", "segments": segs, "scores": None, "planner": "heuristic", "opening_text": None, "payoff_time": None, "evidence": {},
            "what_happens": "", "why_care": "", "reasons": ["planned without the editorial model: scores unavailable, needs a human look"]}
