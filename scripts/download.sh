#!/bin/zsh
# Download a Twitch VOD segment / Twitch clip / YouTube video (or a segment of it) into ../work
# usage: download.sh URL [START END]      START/END like 1:23:45 or 83 (seconds)
# Only use content whose creator has given you clipping/reposting permission (see README).
set -e
cd "$(dirname "$0")/.."
URL="$1"; START="$2"; END="$3"
[ -z "$URL" ] && { echo "usage: download.sh URL [START END]"; exit 1; }
ARGS=(-f "bv*[height<=1080]+ba/b[height<=1080]/b" --merge-output-format mp4 --no-playlist
      -o "work/%(extractor)s_%(id)s.%(ext)s" --print after_move:filepath)
if [ -n "$START" ] && [ -n "$END" ]; then
  ARGS+=(--download-sections "*${START}-${END}" --force-keyframes-at-cuts
         -o "work/%(extractor)s_%(id)s_${START//:/-}_${END//:/-}.%(ext)s")
fi
exec yt-dlp "${ARGS[@]}" "$URL"
