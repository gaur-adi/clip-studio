#!/bin/zsh
# Grab a still to pick facecam/gameplay regions.  usage: frame.sh VIDEO [SECONDS] -> ../work/frame.png
cd "$(dirname "$0")/.."
ffmpeg -y -loglevel error -ss "${2:-5}" -i "$1" -frames:v 1 work/frame.png && echo "work/frame.png ($(ffprobe -v error -show_entries stream=width,height -of csv=p=0 work/frame.png | head -1))"
