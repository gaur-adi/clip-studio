#!/usr/bin/env python3
"""Prints one line per EVENT from the running Clip Studio (new moments, Short/post status changes, stalls, stream end, errors) + a heartbeat every 5 min.
Run:  .venv/bin/python scripts/monitor_live.py        (Ctrl-C to stop)"""
import json, os, re, sys, time, urllib.request
BASE = "http://127.0.0.1:8765"; ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); LOG = os.path.join(ROOT, "work", "server.log")
def get(p):
    return json.loads(urllib.request.urlopen(BASE + p, timeout=8).read())
def out(m): print(time.strftime("%H:%M:%S"), m, flush=True)
seen_moments, seen_post, last_status, last_buf, stall_since, last_beat, down = {}, {}, {}, {}, {}, 0, False
log_pos = os.path.getsize(LOG) if os.path.exists(LOG) else 0
while True:
    try:
        lives = get("/api/live"); down = False
    except Exception as e:
        if not down: out("!! app NOT reachable (server stopped?)")
        down = True; time.sleep(10); continue
    ids = {l["id"] for l in lives}
    for lid in list(last_status):
        if lid not in ids: out(f"[{lid}] stream removed/stopped"); last_status.pop(lid)
    for l in lives:
        lid = l["id"]
        try: s = get("/api/live/" + lid)
        except Exception: continue
        tag = f"[{(s.get('channel') or l['url'].split('=')[-1])[:14]}]"
        if last_status.get(lid) != s["status"]: out(f"{tag} status -> {s['status']} {s.get('error') or ''}"); last_status[lid] = s["status"]
        if s["status"] == "watching":
            if s["buffer_secs"] <= last_buf.get(lid, -1) and s["buffer_secs"] < 230:
                stall_since.setdefault(lid, time.time())
                if time.time() - stall_since[lid] > 90 and stall_since[lid] > 0: out(f"{tag} !! buffer not growing for 90 s (stream stalled?)"); stall_since[lid] = -1
            else: stall_since.pop(lid, None)
            last_buf[lid] = s["buffer_secs"]
        for m in s["moments"]:
            if m["id"] not in seen_moments:
                seen_moments[m["id"]] = 1; out(f"{tag} NEW MOMENT {m['wall']} score {m['score']} - {', '.join(m['why'][:3])}")
            key = (m["id"], m.get("judging"), (m.get("post") or {}).get("status"), m.get("virality"))
            if seen_post.get(m["id"]) != key:
                seen_post[m["id"]] = key; po = m.get("post") or {}
                if not m.get("judging") and m.get("virality") is not None and key[3] is not None: out(f"{tag} judged: AI {m['virality']}/10 \"{m['title'][:60]}\" lang-check ok")
                if po.get("status"): out(f"{tag} short {po['status']} {po.get('note') or po.get('error') or ''} {po.get('final') or ''} {po.get('url') or ''}")
    if os.path.exists(LOG):
        sz = os.path.getsize(LOG)
        if sz < log_pos: log_pos = 0
        if sz > log_pos:
            with open(LOG, errors="ignore") as f:
                f.seek(log_pos); new = f.read(); log_pos = f.tell()
            for ln in new.splitlines():
                if re.search(r"Error|error:|Exception|failed", ln) and not re.search(r"ConnectionResetError|BrokenPipe|Exception occurred during processing", ln): out("LOG " + ln[:160])
    if time.time() - last_beat > 300:
        last_beat = time.time()
        out("heartbeat: " + " | ".join(f"{(x['url'].split('/')[-1] or x['url'])[-14:]} {x['status']} buf {last_buf.get(x['id'], '?')}s" for x in lives) + f" | moments so far {len(seen_moments)}")
    time.sleep(10)
