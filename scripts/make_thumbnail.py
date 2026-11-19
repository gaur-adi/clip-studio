#!/usr/bin/env python3
"""Original synthwave 'Vice City sunset' thumbnail for GTA 6 Shorts (our own artwork: no Rockstar logo/art).
  make_thumbnail.py   -> assets/thumbnails/gta6_1280x720.png and gta6_1080x1920.png"""
import math, os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); OUT = os.path.join(ROOT, "assets", "thumbnails")
FONT = os.path.join(ROOT, "assets", "fonts", "Anton-Regular.ttf")
def lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
def grad(w, h, stops):
    im = Image.new("RGB", (w, h)); px = im.load()
    for y in range(h):
        t = y / (h - 1)
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i + 1][0]:
                c = lerp(stops[i][1], stops[i + 1][1], (t - stops[i][0]) / (stops[i + 1][0] - stops[i][0])); break
        for x in range(w): px[x, y] = c
    return im
def palm(d, x, base_y, height, lean, color, scale=1.0, fr=0.42):
    pts = []; n = 24
    for i in range(n + 1):                                     # curved trunk
        t = i / n; pts.append((x + lean * (t ** 1.7) * height, base_y - t * height))
    w0, w1 = 16 * scale, 7 * scale; left = [(px - (w0 + (w1 - w0) * i / n) / 2, py) for i, (px, py) in enumerate(pts)]; right = [(px + (w0 + (w1 - w0) * i / n) / 2, py) for i, (px, py) in enumerate(pts)]
    d.polygon(left + right[::-1], fill=color)
    tx, ty = pts[-1]
    for ang in (-160, -130, -100, -70, -40, -15, 15, 195, 225):  # fronds
        a = math.radians(ang); L = height * fr
        ex, ey = tx + math.cos(a) * L, ty + math.sin(a) * L * 0.55 + L * 0.35
        mx, my = tx + math.cos(a) * L * 0.55, ty + math.sin(a) * L * 0.55 - L * 0.18
        nx, ny = -math.sin(a), math.cos(a); wd = L * 0.09
        d.polygon([(tx, ty), (mx + nx * wd, my + ny * wd), (ex, ey), (mx - nx * wd, my - ny * wd)], fill=color)
def build(W, H, vertical):
    S = 2; w, h = W * S, H * S
    img = grad(w, h, [(0, (22, 8, 56)), (0.35, (120, 22, 120)), (0.58, (255, 70, 120)), (0.74, (255, 150, 70)), (1, (255, 210, 120))])
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy = w // 2, int(h * (0.50 if vertical else 0.56)); r = int(min(w, h) * (0.30 if vertical else 0.30))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow)                  # sun + glow
    for k in range(6): gd.ellipse([cx - r - k * 40, cy - r - k * 40, cx + r + k * 40, cy + r + k * 40], fill=(255, 120, 180, 22))
    glow = glow.filter(ImageFilter.GaussianBlur(30 * S)); img.paste(glow, (0, 0), glow); d = ImageDraw.Draw(img, "RGBA")
    sun = Image.new("RGBA", (w, h), (0, 0, 0, 0)); sd = ImageDraw.Draw(sun)
    for i in range(r * 2):                                      # vertical sun gradient
        t = i / (r * 2); y = cy - r + i; sd.line([(0, y), (w, y)], fill=lerp((255, 235, 120), (255, 60, 140), t) + (255,))
    mask = Image.new("L", (w, h), 0); ImageDraw.Draw(mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    bands = ImageDraw.Draw(mask)
    for i in range(7):                                          # horizontal slits (retro sun)
        y = cy + int(r * (0.05 + i * 0.13)); bands.rectangle([cx - r, y, cx + r, y + int(4 * S + i * 3 * S)], fill=0)
    img.paste(sun, (0, 0), mask); d = ImageDraw.Draw(img, "RGBA")
    horizon = int(h * (0.72 if vertical else 0.74))              # sea + neon grid floor
    d.rectangle([0, horizon, w, h], fill=(18, 6, 44, 255))
    for i in range(1, 14):
        y = horizon + int((i / 13) ** 2.2 * (h - horizon)); d.line([(0, y), (w, y)], fill=(255, 80, 190, 150), width=2 * S)
    for i in range(-16, 17):
        d.line([(cx + i * 26 * S, horizon), (cx + i * 190 * S * (1.6 if vertical else 1), h)], fill=(0, 230, 255, 120), width=2 * S)
    dark = (14, 4, 36, 255)                                      # skyline + palms (silhouettes)
    import random; rnd = random.Random(6); x = 0
    while x < w:
        bw = rnd.randint(40, 110) * S // 2; bh = rnd.randint(40, 190) * S // (1 if vertical else 2); d.rectangle([x, horizon - bh, x + bw, horizon], fill=(30, 10, 66, 255)); x += bw + rnd.randint(2, 14)
    FR = 0.20 if vertical else 0.42
    palm(d, int(w * 0.07), h, h * (0.50 if vertical else 0.74), 0.10 if vertical else 0.16, dark, S * 1.6, FR); palm(d, int(w * 0.95), h, h * (0.46 if vertical else 0.68), -0.10 if vertical else -0.15, dark, S * 1.5, FR)
    palm(d, int(w * 0.20), h, h * (0.30 if vertical else 0.46), 0.08 if vertical else 0.12, dark, S * 1.1, FR)
    f1 = ImageFont.truetype(FONT, int(min(w, h) * (0.34 if vertical else 0.42))); f2 = ImageFont.truetype(FONT, int(min(w, h) * (0.075 if vertical else 0.085)))
    ty = int(h * (0.20 if vertical else 0.30))
    for dx, dy, col in ((14, 14, (0, 0, 0, 160)), (6, 6, (0, 230, 255, 255))):                      # extruded shadow + neon edge
        d.text((cx + dx * S, ty + dy * S), "GTA 6", font=f1, fill=col, anchor="mm")
    d.text((cx, ty), "GTA 6", font=f1, fill=(255, 255, 255, 255), anchor="mm", stroke_width=5 * S, stroke_fill=(255, 40, 140, 255))
    sub_y = ty + int(f1.size * 0.62); bw = int(f2.getlength("LAUNCH MOMENTS") + 70 * S)
    d.rounded_rectangle([cx - bw // 2, sub_y - int(f2.size * 0.75), cx + bw // 2, sub_y + int(f2.size * 0.75)], 18 * S, fill=(10, 6, 30, 215), outline=(0, 230, 255, 255), width=3 * S)
    d.text((cx, sub_y), "LAUNCH MOMENTS", font=f2, fill=(255, 255, 255, 255), anchor="mm")
    return img.resize((W, H), Image.LANCZOS)
if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    build(1280, 720, False).save(os.path.join(OUT, "gta6_1280x720.png")); build(1080, 1920, True).save(os.path.join(OUT, "gta6_1080x1920.png")); print("ok")
