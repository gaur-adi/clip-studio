# Kdenlive finishing pass (manual) - `brew install --cask kdenlive`
No pre-made .kdenlive file (they embed absolute paths and break between versions); setup takes a minute:
1. File > Project Settings: profile 1080x1920, 30 fps, progressive.
2. Import `work/<name>_1_reframed.mp4` (no burned captions) - or `_2_captioned.mp4` if you only trim/add music.
3. Cut with the razor (X) at in/out; total 20-45 s. Ripple-delete gaps.
4. Commentary: record your voice (Project > Record) on A2, or add Titles for on-screen takes (max 3 lines).
5. Captions: Project > Subtitles > Import the `.srt`; style bold white with black outline, ~70% height, max 2 lines. Or Subtitles > Speech recognition (built in). Skip if you use the burned-in version.
6. Music on A3 at about -20 dB, keyframe it down ~10 dB under speech, fade in 1 s / out 1.5 s. Mute the streamer's own music.
7. Render: MP4 H.264/AAC, 1080x1920, 30 fps, CRF ~18-20, audio 192k. Peaks <= -1 dB. Watch once on your phone.
Safe zone: keep text out of the top ~200 px and bottom ~350 px.
