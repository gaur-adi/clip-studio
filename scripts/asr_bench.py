#!/usr/bin/env python3
"""ASR benchmark on audio with KNOWN text: word error rate (WER), character error rate (CER), speed. Engines run on this Mac."""
import json, os, re, subprocess, sys, unicodedata
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); D = os.path.join(ROOT, "work", "asrbench")
HI1 = "अरे यार ये क्या है देखो देखो पुलिस आ गई भागो भागो मेरी गाड़ी कहाँ है कमाल हो गया ये गेम बहुत ज़बरदस्त है"
HI2 = "भाई देख ये गाड़ी में ब्लास्ट हो गया मैंने तो सोचा ही नहीं था ये होगा पुलिस के हेलीकॉप्टर भी पीछे लग गए अब कहाँ जाऊँ"
EN1 = "wait wait wait no way I just stole a helicopter and the cops are already on me I cannot believe this game"
EN2 = "we need to get out of here before they arrive just take the jet ski and head for the water"
CASES = {"hindi_1": ("hi1.wav", HI1), "hindi_2": ("hi2.wav", HI2), "english_1": ("en1.wav", EN1), "english_2": ("en2.wav", EN2),
         "switching (hi,en,hi,en)": ("mix_seq.wav", " ".join([HI1, EN1, HI2, EN2])), "overlap (hi + quiet en game + noise)": ("mix_overlap.wav", HI2 + " " + EN2)}
def norm(t):
    t = unicodedata.normalize("NFC", t.lower()); t = t.replace("़", "")          # drop nukta: ज़/ज the same for scoring
    return re.sub(r"[^\w\s]|_", " ", t).split()
def edit(a, b):
    p = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        c = [i]
        for j, y in enumerate(b, 1): c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (x != y)))
        p = c
    return p[-1]
def wer(ref, hyp): r, h = norm(ref), norm(hyp); return edit(r, h) / max(len(r), 1)
def cer(ref, hyp): r, h = "".join(norm(ref)), "".join(norm(hyp)); return edit(list(r), list(h)) / max(len(r), 1)
def run(engine, wav):
    py = os.path.join(ROOT, ".venv-asr", "bin", "python") if engine == "qwen3" else sys.executable
    r = subprocess.run([py, os.path.join(ROOT, "scripts", "asr_run.py"), engine, os.path.join(D, wav)], capture_output=True, text=True)
    try: return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: return {"text": "", "lang": "ERR", "secs": 0, "err": r.stderr[-200:]}
engines = sys.argv[1:] or ["whisper_auto", "whisper_hi", "qwen3"]
res = {e: {} for e in engines}
for case, (wav, ref) in CASES.items():
    print(f"\n### {case}\n  REF : {ref[:110]}")
    for e in engines:
        o = run(e, wav); res[e][case] = (wer(ref, o["text"]), cer(ref, o["text"]), o["secs"])
        print(f"  {e:13s} lang={o.get('lang')} WER={res[e][case][0]:.0%} CER={res[e][case][1]:.0%} {o['secs']}s | {o['text'][:110]} {o.get('err','')}")
print("\n=== average over all cases ===")
for e in engines:
    v = list(res[e].values()); print(f"{e:13s} WER {sum(x[0] for x in v)/len(v):.0%}  CER {sum(x[1] for x in v)/len(v):.0%}  avg {sum(x[2] for x in v)/len(v):.1f}s")
