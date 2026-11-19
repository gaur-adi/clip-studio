import os, sys, copy
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(ROOT, "app"))
import config as C

def cfg(**edit):
    c = copy.deepcopy(C.DEFAULTS); c["edit"].update(edit); return c

def words(spec, t0=0.0):
    """'hello world.' style string -> words, 0.4s each with 0.1s gaps; '|' inserts a 1.0s pause"""
    out, t = [], t0
    for tok in spec.split():
        if tok == "|": t += 1.0; continue
        out.append({"w": tok, "s": round(t, 3), "e": round(t + 0.4, 3)}); t += 0.5
    return out

# 40 s of speech: setup (0-14s), payoff line at ~16s, reaction after
SPEC = ("so I know exactly what to do here. | I will steal the plane and fly it away easily. | watch this carefully now. | "
        "oh no my controller disconnected! | how is this even happening right now. | that is so unlucky honestly.")
def raw_plan(**over):
    p = {"decision": "accept", "what_happens": "a confident plan fails", "why_care": "funny",
         "segments": [{"start": 10.0, "end": 21.5, "role": "full", "note": ""}], "opening_text": "Plane theft goes wrong",
         "scores": {"hook": 8, "clarity": 8, "payoff": 9, "energy": 7},
         "evidence": {"opening": {"t": 11.0, "quote": "watch this carefully now"}, "payoff": {"t": 14.0, "quote": "oh no my controller disconnected"}}, "reasons": ["ok"]}
    p.update(over); return p

DUR = 26.0
