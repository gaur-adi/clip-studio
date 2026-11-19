"""Visual payoff + edge validation with a vision-capable model (the configured Ollama model; gemma4:12b accepts images).
Idea adapted (re-implemented, no code copied) from the contact-sheet approach: timestamped 3x3 frame sheets, a payoff-visible question and a menu/loading check.
Honest scope: a sheet of small frames lets the model confirm a CLEAR on-screen event (a screen, a crash, a popup). It cannot judge subtle gameplay; failures degrade to 'unavailable', never to 'approved'."""
import base64, json, os, subprocess, time, urllib.request, urllib.error
from PIL import Image, ImageDraw, ImageFont
import config as C
FONT_PATH = os.path.join(C.ROOT, "assets", "fonts", "Anton-Regular.ttf")

def contact_sheet(video, t0, t1, out_path, n=9, tile_w=480):
    """chronological n-frame sheet (3x3), each tile labelled with its source time in seconds"""
    font = ImageFont.truetype(FONT_PATH, 34); tiles = []; tmp = out_path + ".tile.png"
    for i in range(n):
        t = t0 + (t1 - t0) * (i + 0.5) / n
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", f"scale={tile_w}:-2", tmp], check=True)
        im = Image.open(tmp).convert("RGB"); d = ImageDraw.Draw(im); d.rectangle([0, 0, 125, 44], fill=(0, 0, 0)); d.text((8, 3), f"{t:.1f}s", font=font, fill=(255, 230, 0)); tiles.append(im)
    os.remove(tmp); w, h = tiles[0].size; cols = 3; rows = (n + cols - 1) // cols; S = Image.new("RGB", (w * cols, h * rows))
    for i, im in enumerate(tiles): S.paste(im, ((i % cols) * w, (i // cols) * h))
    S.save(out_path, quality=82); return out_path

def _ask(image_path, prompt, host=None, model=None, timeout=240):
    host = host or os.environ.get("OLLAMA_HOST", ""); host = host if host.startswith("http") else ("http://" + host if host else "")
    if not host: raise RuntimeError("no vision model host configured")
    model = model or os.environ.get("OLLAMA_MODEL", "gemma4:12b"); b = base64.b64encode(open(image_path, "rb").read()).decode()
    body = {"model": model, "stream": False, "format": "json", "think": False, "options": {"temperature": 0.1, "num_predict": 320}, "messages": [{"role": "user", "content": prompt, "images": [b]}]}
    req = urllib.request.Request(host + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.loads(json.loads(urllib.request.urlopen(req, timeout=timeout).read())["message"]["content"])

def check_payoff(video, t0, t1, payoff_desc, payoff_time, work_dir, ask=None):
    """-> {"available": bool, "payoff_visible": bool|None, "first_time": float|None, "menu_at_start": bool|None, "what": str, "confidence": float|None, "sheet": path}
    The model is told the payoff description and time and must find it in the pictures. A wrong answer is detectable: a time far from the transcript's payoff time is flagged."""
    os.makedirs(work_dir, exist_ok=True); sheet = contact_sheet(video, t0, t1, os.path.join(work_dir, "payoff_sheet.jpg"))
    q = ("This is a 3x3 contact sheet of frames from a gaming stream clip in chronological order (left-to-right, top-to-bottom); each frame is labelled with its time in seconds. "
         f"The transcript says the key moment happens around {payoff_time:.0f} s: {payoff_desc[:220]!r}. Look ONLY at the pictures. "
         'Reply JSON: {"payoff_visible":true|false,"first_time_visible":number|null,"what_is_on_screen":"one sentence","menu_or_loading_at_start":true|false,"confidence":0-10}')
    try:
        r = (ask or _ask)(sheet, q)
        if not isinstance(r, dict) or "payoff_visible" not in r: raise ValueError("incomplete answer")
        ft = r.get("first_time_visible"); ft = float(ft) if isinstance(ft, (int, float)) and ft == ft else None
        return {"available": True, "payoff_visible": bool(r["payoff_visible"]), "first_time": ft, "menu_at_start": bool(r.get("menu_or_loading_at_start")),
                "what": str(r.get("what_is_on_screen") or "")[:200], "confidence": float(r["confidence"]) if isinstance(r.get("confidence"), (int, float)) else None, "sheet": sheet}
    except Exception as e:
        return {"available": False, "payoff_visible": None, "first_time": None, "menu_at_start": None, "what": f"visual check unavailable: {str(e)[:100]}", "confidence": None, "sheet": sheet}

def apply_to_plan(plan, vis, cfg=None):
    """fold the visual result into the plan WITHOUT inflating it: contradictions and menu openings push the plan to review; confirmation is only recorded"""
    plan["visual"] = {k: v for k, v in vis.items() if k != "sheet"}; plan["visual_sheet"] = vis.get("sheet")
    if not vis["available"]: plan["reasons"].append("visual payoff check unavailable (not used as evidence)"); return plan
    if vis["payoff_visible"] is False and (vis["confidence"] or 0) >= 6:
        plan["reasons"].append("the vision check could NOT see the payoff in the edited frames: " + vis["what"]); plan["decision"] = "review"; plan["state"] = "needs_review"
    elif vis["payoff_visible"] and plan.get("payoff_time") and vis["first_time"] is not None and abs(vis["first_time"] - plan["payoff_time"]) > 4:
        plan["reasons"].append(f"the vision check saw the event at {vis['first_time']:.0f}s but the transcript puts the payoff at {plan['payoff_time']:.0f}s"); plan["decision"] = "review"; plan["state"] = "needs_review"
    if vis["menu_at_start"]: plan["reasons"].append("the edit may open on a menu or loading screen"); plan["decision"] = "review"; plan["state"] = "needs_review"
    return plan
