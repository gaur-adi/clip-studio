"""Editorial planner: complete timestamped transcript (+ peak + media duration) -> validated edit plan, via the configured Ollama model.
Never approves silently: a model/validation failure yields a heuristic plan with NO scores (state needs_review), an empty transcript yields no plan."""
import json
import analyze as A, config as C, editplan as E

def build_prompt(words, peak, duration, cfg, lang=None, topic=None):
    text, truncated = E.transcript_lines(words, cfg["llm"]["max_transcript_chars"])
    lo, hi = cfg["edit"]["min_len"], cfg["edit"]["max_len"]
    return ("You are an editor of vertical short-form videos (YouTube Shorts). Below is the COMPLETE timestamped transcript of a candidate moment cut from a stream "
        f"(media length {duration:.1f}s; an audio/chat/motion detector flagged a peak near {peak:.1f}s - that is only a hint, not proof it is good). "
        f"Language: {lang or 'unknown'}. Topic: {topic or 'unknown'}.\n\nTRANSCRIPT\n{text}\n\n"
        "TASK: decide whether a stranger would enjoy this and, if yes, plan the TIGHTEST chronological edit: only the minimum setup needed to understand it, "
        "an interesting line or action within the first 3 seconds, the exact payoff, and a short clean reaction. Do not pad; do not reorder. "
        f"Total edited length must be between {lo:.0f} and {hi:.0f} seconds and follow the content. Segments are in SOURCE seconds, ascending, inside 0-{duration:.1f}, "
        "starting and ending at sentence boundaries (never in the middle of a word). The DEFAULT is exactly ONE continuous segment. Use a second segment only to skip a long stretch of dead air or an irrelevant tangent in the middle; segments must never overlap and must be listed in time order. "
        "A valid PAYOFF is a fail or reversal (confident claim followed by failure), a surprise, a funny line, an impressive play, or a genuine reaction to something unexpected. "
        "A game or UI event (a controller disconnecting, a crash, a death) IS a valid payoff when the speaker's setup made the viewer expect something else. "
        "Use decision 'reject' ONLY when there is no coherent setup plus payoff (pure navigation, thanking viewers, filler); if context is missing or you are unsure use 'review'. "
        "Do not reject because the topic is minor: judge whether the edited moment is complete and watchable.\n"
        "Scores are integers 0-10 and must use the whole range honestly: hook (is the opening curious/funny/surprising), clarity (can a stranger follow it without context), "
        "payoff (does a clear joke, fail, surprise or achievement actually happen), energy (real emotion). High energy must NOT raise the others. "
        "Evidence: opening = {t, quote} for the first thing viewers hear, payoff = {t, quote}; each quote must be copied VERBATIM from the transcript near its time. "
        "opening_text: optional on-screen context line, max 8 words, in the transcript's language, adding context WITHOUT inventing facts or dialogue (or null).\n"
        'Reply ONLY with JSON: {"decision":"accept|review|reject","what_happens":"","why_care":"","segments":[{"start":0,"end":0,"role":"setup|payoff|reaction|full","note":""}],'
        '"opening_text":null,"scores":{"hook":0,"clarity":0,"payoff":0,"energy":0},"evidence":{"opening":{"t":0,"quote":""},"payoff":{"t":0,"quote":""}},"reasons":[""]}'), truncated

def plan_moment(words, peak, duration, cfg=None, lang=None, topic=None, chat=None, log=lambda m: None):
    """-> plan dict. plan['state']: planned | needs_review | rejected. chat(prompt, temp, timeout, max_tokens)->dict is injectable for tests."""
    cfg = cfg or C.load(); chat = chat or A.chat_json
    w = E.clean_words(words)
    meta = {"prompt_version": cfg["llm"]["prompt_version"], "model": __import__("os").environ.get("OLLAMA_MODEL", "gemma4:12b")}
    if len(w) < 3:
        return dict(meta, decision="review", state="needs_review", segments=[], scores=None, planner="none", evidence={}, opening_text=None, payoff_time=None,
                    what_happens="", why_care="", reasons=["no usable transcript (speech recognition empty or failed): nothing to plan from"])
    if not (E.finite(duration) and duration > 0): raise E.PlanError(f"bad media duration {duration!r}")
    prompt, truncated = build_prompt(w, peak, duration, cfg, lang, topic)
    if truncated: log("transcript longer than the planner budget: split the source into smaller moments")
    err = None; last = None
    base_prompt = prompt
    for attempt in range(3):
        try:
            raw = chat(prompt, 0.2 if attempt else 0.3, 240, cfg["llm"]["max_tokens"])
            plan = E.parse_llm_plan(raw, w, duration, cfg); plan.update(meta)
            plan["state"] = {"accept": "planned", "review": "needs_review", "reject": "rejected"}[plan["decision"]]
            plan["truncated_transcript"] = truncated
            if plan.get("late_payoff") and attempt == 0:           # one corrective retry: tell the model exactly what is wrong
                prompt = prompt + (f"\n\nYOUR PREVIOUS PLAN was too slow: the payoff at {plan['payoff_time']:.1f}s arrived {plan['time_to_payoff']:.1f}s after the edit began "
                                   f"(limit {cfg['edit']['max_time_to_payoff']:.0f}s). Start the edit LATER: keep only the minimum setup needed to understand the payoff, "
                                   "and drop earlier repetition. Reply with the full JSON again.")
                last = plan; continue
            if plan.get("late_payoff"):                            # still too slow after the corrective retry: tighten explicitly (flagged, stays review)
                try: plan = E.tighten(plan, w, cfg, duration); plan["state"] = "needs_review"
                except E.PlanError as e2: plan["reasons"].append(f"could not tighten: {e2}")
            return plan
        except E.PlanError as e:
            err = f"planner answer rejected: {e}"; log(err)
            prompt = base_prompt + f"\n\nYOUR PREVIOUS ANSWER WAS INVALID: {str(e)[:240]}. Fix exactly that and reply with the complete JSON again."
        except Exception as e: err = f"planner model unavailable: {str(e)[:120]}"; log(err); break
    try:
        plan = E.heuristic_plan(w, peak, duration, cfg)           # reliable chronological fallback, unscored
    except E.PlanError as e:
        return dict(meta, decision="review", state="needs_review", segments=[], scores=None, planner="none", evidence={}, opening_text=None, payoff_time=None,
                    what_happens="", why_care="", reasons=[err or "", str(e)])
    plan.update(meta); plan["state"] = "needs_review"; plan["reasons"].insert(0, err or "no model answer"); plan["llm_error"] = err
    return plan
