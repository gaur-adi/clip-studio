"""Visual 'AI tracking' signals (OpenCV, local): motion, scene/UI-change bursts, faces, auto facecam detection."""
import os, subprocess, sys
import numpy as np, cv2
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YUNET = os.path.join(ROOT, "models", "face_detection_yunet_2023mar.onnx")

def gray_frames(path, start=0.0, dur=None, fps=2, w=160, h=90):
    cmd = ["ffmpeg", "-loglevel", "error", "-ss", str(max(start, 0)), "-i", path]
    if dur: cmd += ["-t", str(dur)]
    cmd += ["-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[:n * w * h], np.uint8).reshape(n, h, w) if n else np.zeros((0, h, w), np.uint8)

def window_metrics(path, start=0.0, dur=None):
    """raw visual metrics for a clip window: motion (mean abs diff), scene-change bursts, motion peak, static ratio"""
    fr = gray_frames(path, start, dur)
    if len(fr) < 4: return None
    d = np.abs(np.diff(fr.astype(np.int16), axis=0)).mean(axis=(1, 2))
    big = (d > max(18.0, np.percentile(d, 95) * 1.0)).sum()
    return {"motion": float(d.mean()), "peak": float(d.max()), "bursts": int(big), "static": float((d < 1.0).mean())}

def per_second(path, start=0.0, dur=None):
    """per-second motion list (for live detection)"""
    fr = gray_frames(path, start, dur)
    if len(fr) < 3: return []
    d = np.abs(np.diff(fr.astype(np.int16), axis=0)).mean(axis=(1, 2))
    return [float(d[i:i + 2].mean()) for i in range(0, len(d), 2)]

def _bgr(path, t, w=640, h=360):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(max(t, 0)), "-i", path, "-frames:v", "1", "-vf", f"scale={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3) if len(raw) == w * h * 3 else None

def detect_facecam(path, duration, samples=8):
    """find a static streamer facecam: returns (x,y,w,h) as 0-1 fractions of the frame, or None"""
    if not os.path.exists(YUNET): return None
    W, H = 640, 360
    det = cv2.FaceDetectorYN.create(YUNET, "", (W, H), 0.75, 0.3, 5000)
    boxes = []
    for i in range(samples):
        img = _bgr(path, duration * (i + .5) / samples)
        if img is None: continue
        _, faces = det.detect(img)
        if faces is None: continue
        for f in faces:
            x, y, w, h = f[:4]
            if w * h < .22 * W * H and w > 20: boxes.append((x + w / 2, y + h / 2, w, h))
    if len(boxes) < max(2, samples // 3): return None
    a = np.array(boxes); med = np.median(a, axis=0)
    close = a[(abs(a[:, 0] - med[0]) < 40) & (abs(a[:, 1] - med[1]) < 40)]   # same place every time = facecam
    if len(close) < max(2, samples // 3): return None
    cx, cy, w, h = np.median(close, axis=0)
    bw, bh = min(w * 4.8, W), min(h * 4.0, H)                                # face -> whole facecam box
    x0 = min(max(cx - bw / 2, 0), W - bw); y0 = min(max(cy - bh / 2, 0), H - bh)
    if x0 < .08 * W: x0 = 0                      # facecams sit against a frame edge: snap to it
    if x0 + bw > .92 * W: x0 = W - bw
    if y0 < .08 * H: y0 = 0
    if y0 + bh > .92 * H: y0 = H - bh
    return tuple(round(float(v), 3) for v in (x0 / W, y0 / H, bw / W, bh / H))

def motion_center_x(path, start=0.0, dur=20.0):
    """stable horizontal centre (0-1) of where the action happens: motion energy per column over the clip. One constant value, so the crop never jitters."""
    fr = gray_frames(path, start, dur)
    if len(fr) < 4: return 0.5
    col = np.abs(np.diff(fr.astype(np.int16), axis=0)).mean(axis=(0, 1)); col = np.convolve(col, np.ones(9) / 9, mode="same")
    if col.sum() < 1e-6: return 0.5
    c = float((col * np.arange(len(col))).sum() / col.sum()) / (len(col) - 1)
    return round(min(max(c, 0.3), 0.7), 3)          # never drift far from the middle: HUD/minimap stay mostly in view

if __name__ == "__main__":
    p = sys.argv[1]; d = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]))
    print("metrics", window_metrics(p)); print("facecam", detect_facecam(p, d))
