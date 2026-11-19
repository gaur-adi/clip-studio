# Clip Studio

A local web app that turns live streams and VODs into tightly edited vertical Shorts. It watches streams with a rolling buffer (no full recording), finds moments, **plans a real edit** (setup → payoff → reaction), renders 1080×1920 video with Hindi/English captions and optional music, and runs a quality gate before anything lands in your output folder. Everything runs on your own machines with free tools. **It never uploads or publishes unless you explicitly do it.**

> Landing page: [`docs/index.html`](docs/index.html) (GitHub Pages serves it from `/docs`).

## How a clip is made
1. **Detect** – audio jumps, motion and Twitch chat bursts in a ~4 min rolling buffer.
2. **Transcribe** – Qwen3-ASR + forced aligner (Mac, MPS) with whisper.cpp fallback; word times kept for the whole source.
3. **Plan the edit** – an LLM (Ollama, e.g. `gemma4:12b`) sees the timestamped transcript and returns segments, named scores (hook / clarity / payoff / energy) and verbatim evidence quotes that are checked against the transcript.
4. **Gate** – weak hook, clarity or payoff is rejected or sent to review; high energy cannot compensate.
5. **Snap and tighten** – cuts never land inside a word; a late payoff is trimmed closer to its setup.
6. **Frame and caption** – presets `context`, `gameplay`, `gameplay_facecam`; phone safe areas; captions remapped through the same segment map as the cut.
7. **Verify** – optional vision check of the payoff frames, duplicate registry, quality gate (duration, black/silence, caption bounds, face overlap). Passing clips go to `final/`, the rest to `review/`.

Details: [`docs/ENGINE.md`](docs/ENGINE.md). The command-line workflow without the app: [`docs/MANUAL_WORKFLOW.md`](docs/MANUAL_WORKFLOW.md).

## Requirements
- macOS or Linux, Python 3.10+, `ffmpeg` (with `ffprobe`), `streamlink`, `yt-dlp`, `whisper-cpp` (`whisper-cli`)
- [Ollama](https://ollama.com) reachable from this machine (a GPU box is best) with a vision-capable model such as `gemma4:12b`
- Optional: Qwen3-ASR environment for speech recognition (`scripts/asr_server.py`), `fribidi` for Devanagari captions (`brew install fribidi`)
- Fonts: Anton and Hind-Bold are bundled in `assets/fonts/`

## Run
```bash
git clone <this repo> clip-studio && cd clip-studio
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "http://YOUR-LLM-HOST:11434" > ollama_host.txt     # Ollama URL
echo "gemma4:12b" > ollama_model.txt
./run_app.sh                                              # http://127.0.0.1:8765, local only
```
Optional overrides go in a root `config.json` (thresholds, edit limits, default framing); defaults live in `app/config.py`.

## Tests
```bash
cd tests && ../.venv/bin/python -m unittest discover -p "test_*.py"
```

## Principles
- **Honest scores:** named scores with reasons; a model's number is not a virality probability.
- **Fails safe:** model down or invalid answer → unscored plan marked for review, never auto-approved.
- **Accurate metadata:** game and creator come only from your setting or the stream's own info.
- **Rights are yours to check:** only clip content you have permission to reuse, follow the game publisher's video policy, and add real commentary. See the checklist in the manual workflow doc.

## Status
Experimental. Score thresholds (7/7/7) are starting values, not validated predictors. No license file has been chosen yet, so by default all rights are reserved.
