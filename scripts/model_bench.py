#!/usr/bin/env python3
"""Compare Ollama models on Hindi/Hinglish/English moment judging + title writing:  OLLAMA_HOST=... model_bench.py model1 model2 ..."""
import os, sys, time
sys.path[:0] = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), d) for d in ("app", "scripts")]
import analyze as A
S = {"hindi": "अरे यार, ये क्या है? देखो देखो, पुलिस आ गई! भागो भागो! मेरी गाड़ी कहाँ है? कमाल हो गया, ये गेम बहुत ज़बरदस्त है!",
     "hinglish": "भाई देख ये गाड़ी में blast हो गया यार, मैंने तो सोचा ही नहीं था ये होगा, पुलिस के helicopter भी पीछे लग गए, अब कहाँ जाऊँ? ओह नो ओह नो!",
     "english": "Wait wait wait, no way, I just stole a helicopter and the cops are already on me. Oh my god, I'm literally flying through Vice City and I cannot believe this game!",
     "boring": "So today we are going to look at the settings menu, I will change the brightness slightly and then we continue with the controls page."}
for model in sys.argv[1:]:
    os.environ["OLLAMA_MODEL"] = model; print("\n=====", model)
    for k, t in S.items():
        c = {"text": t, "title": "", "why": []}; t0 = time.time(); A.llm_rerank([c], lambda m: None)
        meta = A.llm_meta(t, "streamer", "https://x") or {}
        print(f"[{k}] {time.time()-t0:4.1f}s  score={c.get('llm')}  title={c.get('title')!r}  hook={c.get('hook')!r}\n      reason={str(c.get('reason'))[:110]!r}\n      meta_title={meta.get('title')!r}")
