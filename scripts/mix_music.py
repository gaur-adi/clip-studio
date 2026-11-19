#!/usr/bin/env python3
"""Put quiet music under the speech. Music is looped/trimmed to the clip, faded, then
side-chain ducked by the voice (extra reduction whenever someone talks), mixed, loudness-normalised.
  mix_music.py in.mp4 music.mp3 out.mp4 [--music-db -20] [--stems DIR]
"""
import argparse, subprocess, sys
ap = argparse.ArgumentParser()
ap.add_argument("inp"); ap.add_argument("music"); ap.add_argument("out")
ap.add_argument("--music-db", type=float, default=-21, help="music level in dB relative to a -16 LUFS voice, before ducking")
ap.add_argument("--stems", help="also write voice.wav / music_ducked.wav here to verify levels")
ap.add_argument("--lufs", type=float, default=-14)
ap.add_argument("--music-start", type=float, default=0, help="start offset (s) inside the track, e.g. its best section")
a = ap.parse_args()
dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.inp]))
fo = max(dur - 1.5, 0)
fc = (f"[1:a]atrim=0:{dur:.2f},asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-1.5,"
      f"highpass=f=150,lowpass=f=9000,equalizer=f=1800:t=q:w=0.9:g=-6,equalizer=f=90:t=q:w=1:g=-3,volume={a.music_db}dB,"
      f"afade=t=in:d=0.8,afade=t=out:st={max(dur-2.2,0):.2f}:d=2.2[m];"
      f"[0:a]asplit=3[v1][v2][v3];[v3]highpass=f=180,lowpass=f=3400[key];"
      f"[m][key]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=550:makeup=1[md];"
      f"[v2][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I={a.lufs}:TP=-1.5:LRA=11[aout];[v1]anullsink")
cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", a.inp, "-stream_loop", "-1", "-ss", str(a.music_start), "-i", a.music,
       "-filter_complex", fc, "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
       "-movflags", "+faststart", a.out]
r = subprocess.call(cmd)
if r == 0 and a.stems:
    import os; os.makedirs(a.stems, exist_ok=True)
    f2 = (f"[1:a]atrim=0:{dur:.2f},asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-1.5,highpass=f=150,lowpass=f=9000,equalizer=f=1800:t=q:w=0.9:g=-6,equalizer=f=90:t=q:w=1:g=-3,volume={a.music_db}dB[m];"
          f"[0:a]asplit=3[v1][v2][v3];[v3]highpass=f=180,lowpass=f=3400[key];[m][key]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=550:makeup=1[md];[v1]anullsink;[v2]anullsink")
    subprocess.call(["ffmpeg", "-y", "-loglevel", "error", "-i", a.inp, "-stream_loop", "-1", "-ss", str(a.music_start), "-i", a.music, "-filter_complex",
                     f2, "-map", "[md]", "-t", f"{dur:.2f}", os.path.join(a.stems, "music_ducked.wav")])
sys.exit(r)
