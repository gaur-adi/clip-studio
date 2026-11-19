"""Persistent duplicate registry (SQLite): the same source interval is never rendered twice, across watchers, restarts and concurrent requests.
claim() runs inside BEGIN IMMEDIATE so two requests cannot both pass the overlap check."""
import os, sqlite3, time
import config as C
DB = os.path.join(C.ROOT, "data", "clip_registry.sqlite3")
def _conn(path=None):
    p = path or DB; os.makedirs(os.path.dirname(p), exist_ok=True)
    c = sqlite3.connect(p, timeout=30, isolation_level=None)
    c.execute("CREATE TABLE IF NOT EXISTS edits(id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, t0 REAL NOT NULL, t1 REAL NOT NULL, clip_id TEXT, state TEXT NOT NULL, created REAL NOT NULL)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_src ON edits(source_id)"); return c
LIVE_STATES = ("planned", "needs_review", "approved", "rendering", "ready", "published")      # rejected / render_failed / released do not block a retry
def overlap(a0, a1, b0, b1): return max(0.0, min(a1, b1) - max(a0, b0))
def claim(source_id, t0, t1, clip_id=None, state="planned", cfg=None, path=None):
    """-> (True, row_id) when the interval is new, (False, existing_row) when it overlaps a live one"""
    cfg = cfg or C.load(); d = cfg["dedupe"]
    if not (t1 > t0): raise ValueError("empty interval")
    c = _conn(path)
    try:
        c.execute("BEGIN IMMEDIATE")
        for r in c.execute("SELECT id,t0,t1,clip_id,state FROM edits WHERE source_id=? AND state IN (%s)" % ",".join("?" * len(LIVE_STATES)), (source_id, *LIVE_STATES)):
            ov = overlap(t0, t1, r[1], r[2])
            if ov >= d["min_overlap_secs"] or ov >= d["min_overlap_fraction"] * min(t1 - t0, r[2] - r[1]):
                c.execute("ROLLBACK"); return False, {"id": r[0], "t0": r[1], "t1": r[2], "clip_id": r[3], "state": r[4]}
        cur = c.execute("INSERT INTO edits(source_id,t0,t1,clip_id,state,created) VALUES(?,?,?,?,?,?)", (source_id, t0, t1, clip_id, state, time.time()))
        rid = cur.lastrowid; c.execute("COMMIT"); return True, rid
    except Exception:
        try: c.execute("ROLLBACK")
        except Exception: pass
        raise
    finally: c.close()
def set_state(row_id, state, path=None):
    c = _conn(path)
    try: c.execute("UPDATE edits SET state=? WHERE id=?", (state, row_id))
    finally: c.close()
def check(source_id, t0, t1, cfg=None, path=None):
    """read-only duplicate test"""
    cfg = cfg or C.load(); d = cfg["dedupe"]; c = _conn(path)
    try:
        for r in c.execute("SELECT id,t0,t1,clip_id,state FROM edits WHERE source_id=? AND state IN (%s)" % ",".join("?" * len(LIVE_STATES)), (source_id, *LIVE_STATES)):
            ov = overlap(t0, t1, r[1], r[2])
            if ov >= d["min_overlap_secs"] or ov >= d["min_overlap_fraction"] * min(t1 - t0, r[2] - r[1]): return {"id": r[0], "clip_id": r[3], "state": r[4]}
        return None
    finally: c.close()
