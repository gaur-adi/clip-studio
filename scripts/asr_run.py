#!/usr/bin/env python3
"""asr_run.py ENGINE FILE.wav  -> prints one JSON line {text, lang, secs}.  ENGINE: whisper_auto | whisper_hi | qwen3 (needs .venv-asr)"""
import json, os, re, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
eng, wav = sys.argv[1], sys.argv[2]; t0 = time.time(); text = ""; lang = None
if eng.startswith("whisper"):
    out = os.path.join(tempfile.mkdtemp(), "w")
    l = "hi" if eng == "whisper_hi" else "auto"
    subprocess.run(["whisper-cli", "-m", os.path.join(ROOT, "models", "ggml-large-v3-turbo.bin"), "-f", wav, "-l", l, "-oj", "-np", "-nt", "-of", out], capture_output=True)
    d = json.load(open(out + ".json")); text = " ".join(x["text"].strip() for x in d["transcription"]); lang = d["result"].get("language")
else:
    import torch
    from qwen_asr import Qwen3ASRModel
    dev = os.environ.get("ASR_DEVICE", "mps" if torch.backends.mps.is_available() else "cpu")
    m = Qwen3ASRModel.from_pretrained(os.environ.get("QWEN_ASR_MODEL", "Qwen/Qwen3-ASR-1.7B"), dtype=torch.float16 if dev == "mps" else torch.float32, device_map=dev, max_new_tokens=512)
    t0 = time.time()
    r = m.transcribe(audio=wav, language=None)[0]; text, lang = r.text, r.language
print(json.dumps({"text": text, "lang": lang, "secs": round(time.time() - t0, 1)}, ensure_ascii=False))
