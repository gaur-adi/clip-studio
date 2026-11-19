# Manual clipping workflow (scripts)

The command-line way to make a Short without the web app. Written for a GTA 6 launch-week channel; adapt the checklist to your game and rights situation.

Everything lives in `scripts/`. Use the venv python: `.venv/bin/python`.
Installed: ffmpeg, yt-dlp, whisper-cpp (`whisper-cli` + `models/ggml-base.en.bin`), Pillow, websockets.
**Not installed: Kdenlive** -> `brew install --cask kdenlive`.

## Clip Studio app (paste a link -> clips)
`./run_app.sh` opens http://127.0.0.1:8765 (local only). Paste a YouTube/Twitch video, VOD or clip link -> it finds the best moments (audio jumps, YouTube most-replayed + chat replay, whisper transcript hooks/emotion/laughter, sentence-snapped cuts, optional local-LLM virality score 1-10 with title + on-screen hook) -> fill the permission gate -> Render Short -> MP4 + title/description with credit and timestamp link. **Live stream tab**: Twitch chat-spike detection + Streamlink recording; clip from the recording.
GPU: whisper.cpp uses the Mac's GPU (Metal). The AI model runs through Ollama on the Ubuntu laptop (`ollama_host.txt`); the model name is in `ollama_model.txt` (now `gemma4:12b`, chosen by `scripts/model_bench.py` for Hindi + English). Only the laptop needs `OLLAMA_HOST=0.0.0.0 ollama serve`.

### Docker + AI music
- `docker-compose up -d` runs the whole app (see `docs/DOCKER.md`).
- `music/`: 4 synthesised phonk loops (claim-free) + 10 Pixabay phonk tracks in `music/pixabay/`. `scripts/music_ai.py build` profiles tempo/energy/best section; each Short gets a track + start chosen by AI (laptop LLM, heuristic fallback) at -19 dB under the voice. Pixabay tracks can be registered in YouTube Content ID, so tick "claim-free only" for auto-posting.

### AI tracking + live (added)
- **Visual AI (OpenCV, local):** moment ranking now blends audio, speech, motion/scene-change bursts and the LLM. Framing mode "AI auto" finds the streamer's facecam (YuNet face model) and stacks gameplay on top, cam below.
- **Live tab:** paste a live Twitch/YouTube link. A rolling buffer (last ~4 min only, deleted continuously and wiped on Stop) is scored every 10 s on audio jumps, on-screen action and Twitch chat bursts; at a spike ~35 s is cut into `work/live_moments/`, transcribed and judged by the LLM. Click Render on a moment card.
- Permission gate removed (your call); the description still credits the streamer.

## The per-clip routine (manual / script version)
1. **Pick a stream whose creator allows clipping + reposting** (checklist below). Keep your own notes file: name, where they said yes, link/screenshot, date.
2. **Find ONE clear moment** (fail, first reaction, unexpected detail, great play). While watching, log chat in a second terminal:
   `.venv/bin/python scripts/chat_spikes.py log CHANNEL --alert` (prints `[SPIKE] hh:mm:ss` live; Ctrl-C stops; log in `logs/`).
   Afterwards: `.venv/bin/python scripts/chat_spikes.py spikes logs/CHANNEL-*.jsonl --stream-start 2026-11-19T18:00:00` -> ranked peaks + suggested window (chat lags the action 5-15 s, so the window starts ~30 s earlier). A spike is a hint: watch the moment yourself.
3. **Cut to 20-45 s**: `scripts/download.sh "VOD_OR_CLIP_URL" 1:23:10 1:24:00` (a few seconds of slack), then choose the exact in-point with `--start`.
4. **1080x1920, action + face visible**: `scripts/frame.sh work/FILE.mp4 12` -> open `work/frame.png`, note the facecam rectangle as fractions (x,y,w,h). `--mode stack --face x,y,w,h` = gameplay on top, facecam below; `--mode blur` (default) = 16:9 over blurred background.
5. **Captions + your commentary, quiet music, export** in one command:
   ```
   .venv/bin/python scripts/make_short.py work/FILE.mp4 --start 4 --dur 32 \
     --title "My take: <hook / context line>" --music music/YOURTRACK.mp3 \
     --mode stack --face 0.02,0.62,0.22,0.36 -o out/clip01.mp4
   ```
   Output: 1080x1920, 30 fps, H.264/AAC, ~-13 LUFS, upload-ready. Music sits ~20 dB under speech (`--music-db` to tune).
6. **Hand-finish in Kdenlive** (your voice-over, trimming): `docs/KDENLIVE.md`. `--stage reframed|captioned` stops early; `.srt` / `.words.json` sit next to the captioned file.
Upload manually yourself using the title/description pattern below.

## Rights / safety checklist
- [ ] Creator **explicitly allows clipping AND reposting** (Twitch's clip button is not permission). Check their Twitch About panels, Discord rules, YouTube About, pinned posts; if unclear, **ask** and keep the reply. No permission = skip.
- [ ] Credit them in the title or first description line, with a link to the stream/VOD at the timestamp.
- [ ] **Add real commentary** (hook, context, opinion, your voice). YouTube's reused-content rule applies even with the creator's permission, and a few violating videos can hit the whole channel's monetization.
- [ ] Streamer's music / DMCA-prone audio: mute or replace. Use only tracks you have rights to; check Content ID claims after upload.
- [ ] **Rockstar/Take-Two policy** (<https://support.rockstargames.com/articles/200153756/rockstar-games-video-policy>), re-read on the day. As last checked: fan videos are OK for *non-commercial* use (no money made from the footage), must not intentionally spoil the story; isolated cutscenes, cheats/mods and pre-release footage get removed. Monetizing GTA footage may conflict with it, so decide knowingly. Questions: copyright@take2games.com.
- [ ] No spoiler-baiting or misleading titles/thumbnails; skip or label big story moments.
- [ ] No personal info about the streamer or chatters; their face/likeness is covered by their permission.
- [ ] Description disclaimer: "Not affiliated with Rockstar Games / Take-Two."

## Titles, hashtags, cadence (launch week)
Titles (hook first, honest, <=60 chars): `He did NOT expect that in GTA 6 (via StreamerName)` / `First reaction to <thing> in GTA 6` / `This tiny GTA 6 detail is wild` / `Worst first-day fail in GTA 6 - StreamerName`.
Description: your one-line take + `Clip from <Streamer>'s stream: <VOD link @timestamp>, used with permission` + disclaimer.
Hashtags (3-5): `#shorts #gta6 #gta6gameplay #gta6launch #twitchclips`.
Cadence: launch day + next day 3-4 clips/day (time-sensitive); rest of week 2-3/day; then 1/day. Review views/retention after 48 h.

## Files
`scripts/`: chat_spikes.py, download.sh, frame.sh, reframe.py, captions.py, mix_music.py, make_short.py, make_test_music.sh. `music/` your licensed tracks (YouTube Audio Library, Pixabay, CC0). `docs/`: KDENLIVE.md, TOOLS.md. `out/test_blur_final.mp4` = sample result.

## Edit engine (v2)
See [docs/ENGINE.md](docs/ENGINE.md): edit planning, honest scoring, framing presets, quality gate, review UI, duplicate registry, analytics importer, tests.
