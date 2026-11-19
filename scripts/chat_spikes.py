#!/usr/bin/env python3
"""Anonymous, read-only Twitch chat logger + spike finder. No account, no token.

  log    CHANNEL [--seconds N] [--alert]   -> logs/CHANNEL-YYYYmmdd-HHMMSS.jsonl
  spikes LOGFILE [--bin 5] [--top 8] [--stream-start ISO8601]
"""
import argparse, asyncio, json, math, os, random, statistics, sys, time, datetime as dt
from collections import Counter

URL = "wss://irc-ws.chat.twitch.tv"
HYPE = {"lul","lulw","kekw","omegalul","pog","pogchamp","poggers","pogu","w","ww","www","l","ll","f",
        "omg","wtf","wow","lmao","lol","insane","clip","clipit","clip it","gg","nooo","noo","wtfff","holy",
        "cinema","peak","copium","kappa","monkas","pepege","icant","ez"}

def parse(line):
    tags = {}
    if line.startswith("@"):
        raw, line = line.split(" ", 1)
        for kv in raw[1:].split(";"):
            k, _, v = kv.partition("=")
            tags[k] = v
    parts = line.split(" ", 3)
    if len(parts) >= 4 and parts[1] == "PRIVMSG":
        user = parts[0].lstrip(":").split("!")[0]
        return {"user": user, "text": parts[3][1:], "emotes": tags.get("emotes", "")}
    return None

async def log(channel, seconds, out, alert, binsec=5, stop=None):
    import websockets
    channel = channel.lower().lstrip("#")
    end = time.time() + seconds if seconds else None
    counts = Counter(); n = 0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "a", buffering=1) as f:
        f.write(json.dumps({"meta": {"channel": channel, "start": time.time()}}) + "\n")
        last_bin = int(time.time() // binsec); hist = []
        while (end is None or time.time() < end) and not (stop and stop.is_set()):
            try:
                async with websockets.connect(URL, ping_interval=None) as ws:
                    await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
                    await ws.send("PASS SCHMOOPIIE")  # any string works for anonymous
                    await ws.send(f"NICK justinfan{random.randint(10000,99999)}")
                    await ws.send(f"JOIN #{channel}")
                    print(f"[chat] reading #{channel} anonymously ...", file=sys.stderr)
                    while (end is None or time.time() < end) and not (stop and stop.is_set()):
                        try:
                            data = await asyncio.wait_for(ws.recv(), timeout=2)
                        except asyncio.TimeoutError:
                            data = ""
                        now = time.time()
                        for line in data.split("\r\n"):
                            if line.startswith("PING"):
                                await ws.send("PONG :tmi.twitch.tv")
                            elif line:
                                m = parse(line)
                                if m:
                                    m["t"] = round(now, 2); n += 1
                                    counts[int(now // binsec)] += 1
                                    f.write(json.dumps(m, ensure_ascii=False) + "\n")
                        b = int(now // binsec)
                        if b > last_bin:  # a bin closed
                            c = counts[last_bin]; hist.append(c); last_bin = b
                            if alert and len(hist) > 12:
                                base = statistics.median(hist[-60:-1]) or 1
                                if c >= 5 and c / base >= 3:
                                    ts = dt.datetime.fromtimestamp(now - binsec).strftime("%H:%M:%S")
                                    print(f"[SPIKE] {ts} {c} msgs/{binsec}s (x{c/base:.1f} baseline) -> note this time!")
            except Exception as e:
                print(f"[chat] reconnecting after: {e}", file=sys.stderr); await asyncio.sleep(3)
    print(f"[chat] done, {n} messages -> {out}", file=sys.stderr)

def load(path):
    meta, msgs = None, []
    for line in open(path):
        d = json.loads(line)
        if "meta" in d: meta = d["meta"]
        else: msgs.append(d)
    return meta, msgs

def hype_score(m):
    toks = m["text"].lower().split()
    s = 1 if any(t.strip("!?.,") in HYPE for t in toks) else 0
    if m.get("emotes"): s += 1
    letters = [c for c in m["text"] if c.isalpha()]
    if len(letters) > 4 and sum(c.isupper() for c in letters) / len(letters) > .7: s += 1
    return s

def hms(sec):
    sec = int(max(sec, 0)); return f"{sec//3600:02d}:{sec%3600//60:02d}:{sec%60:02d}"

def find_spikes(path, binsec=5, top=8, min_gap=40):
    """Return ranked chat peaks: [{peak_t (epoch), log_offset, count, hype, uniq, score, sample}]"""
    meta, msgs = load(path)
    if len(msgs) < 5: return [], None
    t0 = meta["start"] if meta else msgs[0]["t"]
    tend = msgs[-1]["t"]; nb = int((tend - t0) // binsec) + 1
    cnt = [0]*nb; hyp = [0]*nb; users = [set() for _ in range(nb)]
    for m in msgs:
        i = int((m["t"] - t0) // binsec); cnt[i] += 1; hyp[i] += hype_score(m); users[i].add(m["user"])
    sm = lambda a: [sum(a[max(0,i-1):i+2])/len(a[max(0,i-1):i+2]) for i in range(len(a))]
    c, h = sm(cnt), sm(hyp)
    def z(a):
        mu = statistics.mean(a); sd = statistics.pstdev(a) or 1
        return [(x-mu)/sd for x in a]
    zc, zh = z(c), z(h)
    score = [zc[i] + .7*zh[i] + .3*math.log1p(len(users[i])) for i in range(nb)]
    picked = []
    for i in sorted(range(nb), key=lambda i: -score[i]):
        if all(abs(i-j)*binsec >= min_gap for j in picked): picked.append(i)
        if len(picked) >= top: break
    rows = []
    for i in picked:
        sample = next((m["text"][:40] for m in msgs if int((m["t"]-t0)//binsec) == i), "")
        rows.append({"peak_t": t0 + i*binsec + binsec/2, "log_offset": i*binsec + binsec/2, "count": cnt[i],
                     "hype": hyp[i], "uniq": len(users[i]), "score": score[i], "sample": sample})
    return rows, t0

def spikes(path, binsec, top, stream_start):
    rows, t0 = find_spikes(path, binsec, top)
    if not rows: sys.exit("no/too few messages in log")
    ss = dt.datetime.fromisoformat(stream_start).timestamp() if stream_start else None
    print(f"Chat lags the action ~5-15 s, so clip window starts BEFORE the peak.")
    print(f"{'#':>2} {'log_offset':>10} {'wall_clock':>10} {'vod_time':>9}  msgs  hype  uniq  clip_window  sample")
    for r, x in enumerate(rows, 1):
        peak = x["peak_t"]; base = (peak - ss) if ss else (peak - t0)
        print(f"{r:>2} {hms(x['log_offset']):>10} {dt.datetime.fromtimestamp(peak).strftime('%H:%M:%S'):>10} "
              f"{hms(peak-ss) if ss else '-':>9} {x['count']:>5} {x['hype']:>5} {x['uniq']:>5}  "
              f"{hms(base-30)}-{hms(base+12)}  {x['sample']!r}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("log"); a.add_argument("channel"); a.add_argument("--seconds", type=int, default=0)
    a.add_argument("--out"); a.add_argument("--alert", action="store_true")
    b = sub.add_parser("spikes"); b.add_argument("logfile"); b.add_argument("--bin", type=int, default=5)
    b.add_argument("--top", type=int, default=8); b.add_argument("--stream-start", help="ISO time the stream began (local), to get VOD timestamps")
    x = ap.parse_args()
    if x.cmd == "log":
        out = x.out or os.path.join(os.path.dirname(__file__), "..", "logs", f"{x.channel}-{dt.datetime.now():%Y%m%d-%H%M%S}.jsonl")
        try: asyncio.run(log(x.channel, x.seconds, os.path.abspath(out), x.alert))
        except KeyboardInterrupt: pass
    else: spikes(x.logfile, x.bin, x.top, x.stream_start)
