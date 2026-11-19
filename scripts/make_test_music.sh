#!/bin/zsh
# Generates a royalty-free (synthesised by us) ambient loop for testing: music/test_ambient.mp3
cd "$(dirname "$0")/.."
ffmpeg -y -loglevel error -f lavfi -i "sine=f=220:d=45" -f lavfi -i "sine=f=277.18:d=45" -f lavfi -i "sine=f=329.63:d=45" -f lavfi -i "sine=f=164.81:d=45" \
 -filter_complex "[0][1][2][3]amix=inputs=4:normalize=0,tremolo=f=0.25:d=0.5,lowpass=f=1200,volume=0.5" music/test_ambient.mp3 && echo music/test_ambient.mp3
