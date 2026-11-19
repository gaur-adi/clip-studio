"""Clip Studio settings (config.json at the project root). Missing keys fall back to DEFAULTS; the file is never overwritten.
All thresholds are EXPERIMENTAL starting points, not validated predictors of audience behaviour."""
import copy, json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS = {
    "edit": {"min_len": 8.0, "max_len": 45.0, "pre_roll": 0.15, "post_roll": 0.35, "max_gap_inside_word": 0.0, "opening_target_secs": 3.0, "max_time_to_payoff": 14.0, "tighten_lead": 7.0, "tighten_tail": 9.0, "finish_sentence_max": 2.5, "filler_trim_max": 1.5,
             "fillers": ["um", "uh", "umm", "uhh", "er", "erm", "hmm", "so", "like", "okay", "ok", "well", "अरे", "हम्म", "उम्म", "अच्छा", "तो", "मतलब"]},
    "thresholds": {"hook": 7.0, "clarity": 7.0, "payoff": 7.0, "review_margin": 2.0},   # a part below threshold-margin is rejected, in between needs review
    "planner": {"enabled": True},    # False: old one-shot judge (scores only), no edit planning
    "auto_approve": False,            # True: a plan that passes every gate and QA is rendered straight into final/. False: stops at needs_review
    "llm": {"max_transcript_chars": 24000, "max_tokens": 700, "prompt_version": "edit-plan-v2"},
    "safe_area": {"top": 170, "bottom": 380, "right": 160, "left": 48},          # px on the 1080x1920 canvas covered by Shorts UI
    "framing": {"default": "context", "gameplay_aspect": 0.9, "facecam_panel_h": 520, "banner_secs": 2.8},
    "qa": {"max_black_secs": 0.5, "max_opening_silence": 1.2, "min_gameplay_share": 0.30, "duration_tolerance": 0.6, "visual_check": True},
    "dedupe": {"min_overlap_secs": 5.0, "min_overlap_fraction": 0.5},
}
def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict): _merge(a[k], v)
        else: a[k] = v
    return a
def load(path=None):
    cfg = copy.deepcopy(DEFAULTS); p = path or os.path.join(ROOT, "config.json")
    try:
        if os.path.exists(p):
            with open(p) as f: _merge(cfg, json.load(f))
    except Exception: pass                      # a broken config.json must not stop rendering: defaults apply
    return cfg
