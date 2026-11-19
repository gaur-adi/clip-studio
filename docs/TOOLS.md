# Free tool ranking (verified on this Mac, 18 Nov 2026)
1. yt-dlp (brew, 2026.10.26): `--download-sections "*a-b" --force-keyframes-at-cuts`; tested OK on YouTube. Not tested on Twitch (no permitted sample). Can't record a live stream from second one; optional `brew install streamlink` for that.
2. ffmpeg 8.1: all editing. This build has NO libass/drawtext, so captions are Pillow PNG overlays (tested).
3. whisper.cpp (`brew install whisper-cpp`, base.en 148 MB): offline, word times via `-ml 1 -sow -ojf`. English only; for Hindi use a multilingual model (`--model models/ggml-base.bin`). Word timing is approximate; edit `*.words.json` and rerun with `--reuse-words`. Alternative: Kdenlive's built-in speech-to-text.
4. Kdenlive 26.08 (cask): manual finishing, free/open source.
5. Twitch anonymous chat (wss://irc-ws.chat.twitch.tv, justinfan nick, read-only): tested live, no login. Unofficial behavior could change.
6. Music: YouTube Audio Library (log in yourself), Pixabay Music, Free Music Archive CC0, Incompetech (credit). Never ship streamer/game music.
