# Clip Studio: local web app (YouTube/Twitch link or live stream -> AI-picked 40 s Shorts)
FROM python:3.12-slim-trixie AS whisper
RUN apt-get update && apt-get install -y --no-install-recommends git cmake g++ make ca-certificates && rm -rf /var/lib/apt/lists/*
# whisper.cpp CPU build (containers on macOS have no Metal GPU). For the NVIDIA laptop see docs/DOCKER.md (CUDA build arg).
ARG WHISPER_REF=v1.9.5
ARG WHISPER_CUDA=0
RUN git clone --depth 1 --branch ${WHISPER_REF} https://github.com/ggml-org/whisper.cpp /w && cd /w \
 && cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=$([ "$WHISPER_CUDA" = 1 ] && echo ON || echo OFF) -DBUILD_SHARED_LIBS=OFF \
 && cmake --build build -j4 --target whisper-cli && cp build/bin/whisper-cli /whisper-cli

FROM python:3.12-slim-trixie
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates unzip libgomp1 libglib2.0-0 libfribidi0 libraqm0 && rm -rf /var/lib/apt/lists/*
# deno: yt-dlp needs a JS runtime for YouTube
RUN case "$TARGETARCH" in arm64) D=aarch64;; *) D=x86_64;; esac \
 && curl -fsSL -o /tmp/deno.zip https://github.com/denoland/deno/releases/latest/download/deno-${D}-unknown-linux-gnu.zip \
 && unzip -q /tmp/deno.zip -d /usr/local/bin && rm /tmp/deno.zip
COPY --from=whisper /whisper-cli /usr/local/bin/whisper-cli
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p models && curl -fsSL -o models/ggml-small.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin \
 && curl -fsSL -o models/face_detection_yunet_2023mar.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
COPY app app
COPY scripts scripts
COPY music music
COPY assets assets
RUN mkdir -p out work logs docs secrets
ENV HOST=0.0.0.0 PORT=8765 YT_DIR=/app/secrets PYTHONUNBUFFERED=1
EXPOSE 8765
CMD ["python", "app/server.py"]
