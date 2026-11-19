"""Local analytics importer: YouTube Studio CSV exports -> SQLite, joined to each clip's edit record so edit choices (preset, length, time-to-payoff, scores) can be compared with real viewer behaviour.
No network, no OAuth, no tokens: you export the CSV from Studio yourself. (A read-only Analytics API reader would need its own owner authorisation and is deliberately NOT included.)
CLI:  python app/analytics.py import studio_export.csv --label 48h   |   python app/analytics.py report [--json]"""
import csv, glob, json, os, re, sqlite3, sys, time, argparse
import config as C
DB = os.path.join(C.ROOT, "data", "analytics.sqlite3"); SCAN = ("final", "published", "review")
COLS = {  # canonical -> accepted header spellings (lower-cased, punctuation stripped)
    "video_id": ["content", "video id", "videoid", "id"], "title": ["video title", "title"], "views": ["views"],
    "avg_view_secs": ["average view duration", "avg view duration", "average view duration seconds"],
    "avg_pct_viewed": ["average percentage viewed", "average percentage viewed ", "avg percentage viewed"],
    "likes": ["likes"], "impressions": ["impressions"], "ctr": ["impressions click through rate", "impressions clickthrough rate", "ctr"],
    "stayed_pct": ["stayed to watch", "stayed to watch "], "engaged_views": ["engaged views"], "subs": ["subscribers"]}

def _key(h): return re.sub(r"[^a-z0-9 ]+", " ", h.lower().replace("(%)", "")).strip()
def num(x):
    x = str(x or "").strip().replace(",", "").replace("%", "")
    if not x or x in ("-", "—"): return None
    if re.fullmatch(r"\d+:\d{2}(:\d{2})?", x): return float(sum(int(p) * 60 ** i for i, p in enumerate(reversed(x.split(":")))))
    try: return float(x)
    except ValueError: return None

def connect(path=None):
    p = path or DB; os.makedirs(os.path.dirname(p), exist_ok=True); c = sqlite3.connect(p, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots(video_id TEXT, label TEXT, imported_at REAL, title TEXT, views REAL, avg_view_secs REAL, avg_pct_viewed REAL, likes REAL,
                 impressions REAL, ctr REAL, stayed_pct REAL, engaged_views REAL, subs REAL, PRIMARY KEY(video_id, label))"""); return c

def import_csv(csv_path, label, db=None):
    """upsert one row per (video, label). Rows without a video id or title are skipped; unknown columns are ignored. Returns (imported, skipped)."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f: rows = list(csv.DictReader(f))
    if not rows: return 0, 0
    hm = {}
    for h in rows[0]:
        for canon, names in COLS.items():
            if _key(h) in names and canon not in hm: hm[canon] = h
    if "views" not in hm or ("video_id" not in hm and "title" not in hm): raise ValueError("this does not look like a Studio content export (needs Views and a Content/Video title column)")
    c = connect(db); n = k = 0
    for r in rows:
        vid = (r.get(hm.get("video_id", ""), "") or "").strip(); title = (r.get(hm.get("title", ""), "") or "").strip()
        if (vid.lower() in ("total", "") and not title) or vid.lower() == "total": k += 1; continue
        key = vid or "title:" + title
        v = {m: num(r.get(hm[m])) for m in ("views", "avg_view_secs", "avg_pct_viewed", "likes", "impressions", "ctr", "stayed_pct", "engaged_views", "subs") if m in hm}
        c.execute("INSERT OR REPLACE INTO snapshots(video_id,label,imported_at,title,views,avg_view_secs,avg_pct_viewed,likes,impressions,ctr,stayed_pct,engaged_views,subs) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (key, label, time.time(), title, v.get("views"), v.get("avg_view_secs"), v.get("avg_pct_viewed"), v.get("likes"), v.get("impressions"), v.get("ctr"), v.get("stayed_pct"), v.get("engaged_views"), v.get("subs"))); n += 1
    c.commit(); c.close(); return n, k

def edit_records(root=None):
    """every clip metadata JSON that has an edit record, keyed by YouTube id and title"""
    root = root or C.ROOT; out = []
    for d in SCAN:
        for p in glob.glob(os.path.join(root, d, "**", "*.json"), recursive=True):
            try:
                with open(p, encoding="utf-8") as f: m = json.load(f)
            except Exception: continue
            if not isinstance(m, dict) or "title" not in m: continue
            url = m.get("youtube_url") or (m.get("publication") or {}).get("youtube_url") or ""; mid = re.search(r"(?:v=|shorts/|youtu\.be/)([\w-]{11})", url or "")
            out.append({"path": p, "video_id": mid.group(1) if mid else None, "title": m["title"], "plan": m.get("edit_plan") or {}, "framing": m.get("framing"), "durations": m.get("durations") or {}, "language": m.get("language")})
    return out

def report(db=None, root=None):
    """per clip: latest snapshot per label joined with edit facts. Unmatched Studio rows are listed, not guessed."""
    c = connect(db); recs = edit_records(root); by_id = {r["video_id"]: r for r in recs if r["video_id"]}; by_title = {r["title"].strip().lower(): r for r in recs}
    rows = c.execute("SELECT video_id,label,title,views,avg_view_secs,avg_pct_viewed,likes,impressions,ctr,stayed_pct FROM snapshots ORDER BY video_id,label").fetchall(); c.close()
    out = []
    for vid, label, title, views, avs, apv, likes, imp, ctr, stay in rows:
        r = by_id.get(vid) or by_title.get((title or "").strip().lower()); pl = (r or {}).get("plan") or {}; sc = pl.get("scores") or {}
        edited = (r or {}).get("durations", {}).get("edited") or sum(g["end"] - g["start"] for g in pl.get("segments", []) if "end" in g) or None
        out.append({"video_id": vid, "label": label, "title": title, "matched": bool(r), "views": views, "avg_view_secs": avs, "avg_pct_viewed": apv, "likes": likes, "impressions": imp, "ctr": ctr, "stayed_pct": stay,
                    "edited_secs": edited, "time_to_payoff": pl.get("time_to_payoff"), "preset": (r or {}).get("framing"), "scores": sc or None, "language": (r or {}).get("language"),
                    "retention_of_edit": round(avs / edited, 2) if avs and edited else None})
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    i = sp.add_parser("import"); i.add_argument("csv"); i.add_argument("--label", default="manual", help="e.g. 48h or 7d: which snapshot this export is")
    r = sp.add_parser("report"); r.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "import": n, k = import_csv(a.csv, a.label); print(f"imported {n} rows ({k} skipped) as '{a.label}'")
    else:
        rows = report()
        if a.json: print(json.dumps(rows, indent=1, ensure_ascii=False))
        else:
            for x in rows: print(f"{x['label']:>6} {str(x['views'] or 0):>7} views  avg {x['avg_view_secs'] or 0:>5.1f}s of {x['edited_secs'] or 0:>5.1f}s  {'matched' if x['matched'] else 'UNMATCHED':9} {x['title'][:50]}")
