# Run Clip Studio in Docker
Everything (ffmpeg, yt-dlp, whisper.cpp + model, OpenCV, streamlink, the app) is in one image.
## Start / stop (macOS, free runtime = Colima)
```
colima start --cpu 4 --memory 6        # once per reboot
cd clip-studio
docker-compose up -d                   # open http://127.0.0.1:8765   (only this computer can reach it)
docker-compose logs -f                 # logs
docker-compose down                    # stop the app
colima stop                            # stop the Docker VM to free RAM
```
Rebuild after code changes: `docker-compose build && docker-compose up -d`.
## Config
- `.env`: `OLLAMA_HOST=http://YOUR-LLM-HOST:11434` (a GPU machine does the AI judging, titles, music choice).
- Folders on your Mac mapped into the container: `out/` finished Shorts, `music/` tracks + library.json, `logs/`, `work/`, `docs/`, `secrets/` (put `youtube_client_secret.json` there; the token is saved there too).
- YouTube connect inside Docker: `docker exec -it clipstudio python scripts/youtube_upload.py --auth` prints no browser window; easier: run `.venv/bin/python scripts/youtube_upload.py --auth` on the Mac with `YT_DIR=secrets` once.
## Notes
- Containers on a Mac have no Apple GPU: speech-to-text runs on CPU (slower than the native app, fine for 30-40 s clips).
- NVIDIA laptop with Docker + nvidia-container-toolkit: `docker build --build-arg WHISPER_CUDA=1 -t clipstudio .` and run with `--gpus all`.
