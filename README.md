<div align="center">

# Clip Studio

### Free, open-source AI clipper that turns live streams into tightly edited YouTube Shorts

Watches Twitch and YouTube live streams, **plans the edit around the payoff**, renders captioned 1080×1920 vertical video, and checks quality before anything reaches your output folder. Local, free tools. Hindi and English captions. It never uploads unless you do.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](https://www.python.org)
[![Tests](https://img.shields.io/badge/tests-55%20passing-brightgreen.svg)](tests)
[![Runs locally](https://img.shields.io/badge/runs-100%25%20local-black.svg)](#how-it-works)
[![Website](https://img.shields.io/badge/site-motion%20demo-FF4B2B.svg)](https://gaur-adi.github.io/clip-studio/)

[**Website and motion demo**](https://gaur-adi.github.io/clip-studio/) · [How it works](docs/ENGINE.md) · [Quick start](#quick-start) · [FAQ](#faq)

</div>

---

## What is Clip Studio?

Clip Studio is a **live stream clipper**: a local web app that finds the best moments in a Twitch or YouTube live stream or VOD and turns them into **YouTube Shorts** (also usable for Instagram Reels and TikTok after you export). Unlike tools that cut a fixed window around a loud moment, it reads the timestamped transcript, picks the **setup, payoff and reaction**, trims dead air, snaps cuts to speech boundaries, and rejects moments that are still weak after editing.

It runs on your own machines: a rolling buffer instead of full recordings, a local LLM through [Ollama](https://ollama.com), speech recognition on your Mac, and ffmpeg for rendering. No subscription, no cloud upload.

## Real Shorts made with it

These are public Shorts produced with earlier versions of this workflow (click a thumbnail to watch). The newer edit-planning engine described below was validated on a real clip, with before/after renders, rather than on a large published batch.

<table><tr><td align="center" width="25%"><a href="https://www.youtube.com/shorts/gFTFD-ljBS0"><img src="https://i.ytimg.com/vi/gFTFD-ljBS0/hqdefault.jpg" width="170" alt="Short: एक गलत Turn… और फिर Panic 😭 | GTA 6"></a><br><sub>एक गलत Turn… और फिर Panic 😭 | GTA 6</sub></td><td align="center" width="25%"><a href="https://www.youtube.com/shorts/FYQ5lZLApS4"><img src="https://i.ytimg.com/vi/FYQ5lZLApS4/hqdefault.jpg" width="170" alt="Short: सोचा छुप जाऊँगा… हेलीकॉप्टर अभी भी पीछे "></a><br><sub>सोचा छुप जाऊँगा… हेलीकॉप्टर अभी भी पीछे है 🚁 |</sub></td><td align="center" width="25%"><a href="https://www.youtube.com/shorts/577Y_pYcmTk"><img src="https://i.ytimg.com/vi/577Y_pYcmTk/hqdefault.jpg" width="170" alt="Short: Florida Drivers Are a Different Breed 😂 "></a><br><sub>Florida Drivers Are a Different Breed 😂 | GTA </sub></td><td align="center" width="25%"><a href="https://www.youtube.com/shorts/f6Iocca-Bp8"><img src="https://i.ytimg.com/vi/f6Iocca-Bp8/hqdefault.jpg" width="170" alt="Short: Delivery Partner को हाथ मत लगाना 😂 | GTA"></a><br><sub>Delivery Partner को हाथ मत लगाना 😂 | GTA 6</sub></td></tr><tr><td align="center" width="25%"><a href="https://www.youtube.com/shorts/8Fx1_JGpIaw"><img src="https://i.ytimg.com/vi/8Fx1_JGpIaw/hqdefault.jpg" width="170" alt="Short: बैंक जाना था… रास्ते में ही Chaos हो गया"></a><br><sub>बैंक जाना था… रास्ते में ही Chaos हो गया 😂 | G</sub></td><td align="center" width="25%"><a href="https://www.youtube.com/shorts/ZlJbxoKrVU4"><img src="https://i.ytimg.com/vi/ZlJbxoKrVU4/hqdefault.jpg" width="170" alt="Short: ये Vice City है या मुंबई का Traffic? 😂 |"></a><br><sub>ये Vice City है या मुंबई का Traffic? 😂 | GTA 6</sub></td><td align="center" width="25%"><a href="https://www.youtube.com/shorts/mEO6OHScHfY"><img src="https://i.ytimg.com/vi/mEO6OHScHfY/hqdefault.jpg" width="170" alt="Short: He Was NOT Ready for This 😱 | GTA 6"></a><br><sub>He Was NOT Ready for This 😱 | GTA 6</sub></td><td align="center" width="25%"><a href="https://www.youtube.com/shorts/8fffTPlrt6E"><img src="https://i.ytimg.com/vi/8fffTPlrt6E/hqdefault.jpg" width="170" alt="Short: Mission साफ है: पैसा कमाना है 💰 | GTA 6"></a><br><sub>Mission साफ है: पैसा कमाना है 💰 | GTA 6</sub></td></tr></table>

> The footage belongs to the streamers and game publishers. These clips were published with commentary and credit; this repository contains no streamer footage.

## Features

| | |
|---|---|
| **Edit planning** | An LLM reads the full timestamped transcript and returns segments, reasons and verbatim evidence quotes that are verified against what was said. |
| **Honest scoring** | Hook, clarity, payoff and energy are scored separately and gated independently. Loud energy cannot rescue a clip with no ending. |
| **Speech-safe cuts** | Boundaries never land inside a word. A late payoff is tightened closer to its setup (flagged for review). |
| **Vertical framing presets** | `context`, `gameplay`, `gameplay + facecam`, with phone safe areas so captions avoid the Shorts UI. |
| **Hindi and English captions** | Word-timed captions via Qwen3-ASR (forced alignment) with whisper.cpp fallback, Devanagari shaping, remapped through the same cut map. |
| **Quality gate** | Resolution, duration, black or silent frames, caption bounds, face overlap, duplicate intervals. Failing clips go to `review/`, not `final/`. |
| **Live watching** | Rolling buffer, audio/motion/chat-spike detection, several streams at once, automatic moment cutting. |
| **Review UI** | Per-moment scores, evidence, vision check and reasons; adjust timing and framing, approve or reject. |
| **Duplicate protection** | An atomic SQLite registry stops the same stretch of a stream being clipped twice. |
| **Analytics importer** | Import a YouTube Studio CSV and compare viewer retention with edit length, time-to-payoff and scores. |
| **Fails safe** | No transcript, model down or invalid answer means the clip waits for review with no invented score. |

## How it works

```
live stream / VOD
   -> rolling buffer + spike detection (audio, motion, chat)
   -> word-timed transcript (Qwen3-ASR or whisper.cpp)
   -> edit plan (LLM): segments, named scores, verified quotes
   -> gate + speech-safe snapping + tightening + optional vision payoff check
   -> duplicate claim
   -> render 1080x1920: framing preset, captions, optional music
   -> quality gate -> final/ (ready) or review/ (needs a human)
```

Full details, module map and rules: [`docs/ENGINE.md`](docs/ENGINE.md).

## Quick start

```bash
git clone https://github.com/gaur-adi/clip-studio.git && cd clip-studio
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "http://YOUR-LLM-HOST:11434" > ollama_host.txt     # your Ollama URL
echo "gemma4:12b" > ollama_model.txt                     # any capable (ideally vision) model
./run_app.sh                                              # http://127.0.0.1:8765 (local only)
```

Paste a Twitch or YouTube link, or start a live watcher, then review and approve moments in the UI.

**Requirements:** Python 3.10+, `ffmpeg` and `ffprobe`, `streamlink`, `yt-dlp`, `whisper-cpp`, and an [Ollama](https://ollama.com) host. Developed and tested on macOS; the rendering, planning and tests are plain Python and ffmpeg. Optional: Qwen3-ASR environment (`scripts/asr_server.py`) and `fribidi` for Devanagari captions.

**Configuration:** defaults live in [`app/config.py`](app/config.py); override anything in a root `config.json` (thresholds, edit limits, default framing) or from the UI settings.

**Tests:**
```bash
cd tests && ../.venv/bin/python -m unittest discover -p "test_*.py"
```

## FAQ

**How do I turn a Twitch or YouTube live stream into Shorts for free?**
Run Clip Studio locally, paste the stream link, and approve the moments it plans. Everything it uses is free software.

**Does it work with Hindi streams?**
Yes. Captions are Hindi and English with correct Devanagari shaping, and the planner works on mixed Hindi-English speech.

**Does it upload to YouTube for me?**
Only if you set up the optional uploader yourself ([`docs/YOUTUBE_SETUP.md`](docs/YOUTUBE_SETUP.md)) and trigger it. By default nothing is uploaded or published.

**Do I need a GPU?**
The language model runs through Ollama, so a GPU machine is best; it can be a different computer on your network. Rendering uses ffmpeg.

**Is it guaranteed to make viral clips?**
No. The scores are editorial checks, not predictions of views. Use the analytics importer to compare real results with your edit choices.

**Can I clip any streamer?**
Only clip content you have permission to reuse, follow the platform's and game publisher's policies, and add real commentary.

## Documentation

- [Engine design and rules](docs/ENGINE.md)
- [Manual command-line workflow](docs/MANUAL_WORKFLOW.md)
- [YouTube upload setup (optional)](docs/YOUTUBE_SETUP.md)
- [Docker (optional)](docs/DOCKER.md)
- [Third-party notices](THIRD_PARTY.md)

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Aditya Gaur. Third-party components and model licenses are listed in [THIRD_PARTY.md](THIRD_PARTY.md). The license covers this code only, not the streams, games or music you process.

## Responsible use

Respect streamers, game publishers and platform rules. Credit the creator, add real commentary, avoid misleading titles, and do not republish content you lack rights to.

<sub>Keywords: YouTube Shorts clipper, live stream clipper, Twitch clip to Shorts, AI video clipper, auto highlights, stream highlights generator, vertical video editor, Ollama, whisper, Hindi captions, open source.</sub>
