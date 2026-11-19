import csv, json, os, tempfile, threading, unittest
import _fix as F
import analytics as AN, config as C, dedupe as D, metadata as MD

class Dedupe(unittest.TestCase):
    def setUp(self): self.db = os.path.join(tempfile.mkdtemp(), "r.sqlite3"); self.cfg = F.cfg()
    def test_overlap_blocked_distinct_allowed(self):
        ok, r = D.claim("src", 100, 120, "a", cfg=self.cfg, path=self.db); self.assertTrue(ok)
        ok2, ex = D.claim("src", 110, 130, "b", cfg=self.cfg, path=self.db); self.assertFalse(ok2); self.assertEqual(ex["clip_id"], "a")
        self.assertTrue(D.claim("src", 200, 220, "c", cfg=self.cfg, path=self.db)[0]); self.assertTrue(D.claim("other", 100, 120, "d", cfg=self.cfg, path=self.db)[0])
    def test_small_touch_is_allowed(self):
        D.claim("s", 100, 120, "a", cfg=self.cfg, path=self.db); self.assertTrue(D.claim("s", 118, 140, "b", cfg=self.cfg, path=self.db)[0])    # 2 s overlap < 5 s
    def test_rejected_edit_frees_the_interval(self):
        _, rid = D.claim("s", 100, 120, "a", cfg=self.cfg, path=self.db); D.set_state(rid, "rejected", path=self.db)
        self.assertTrue(D.claim("s", 100, 120, "b", cfg=self.cfg, path=self.db)[0])
    def test_concurrent_claims_only_one_wins(self):
        res = []; ts = [threading.Thread(target=lambda i=i: res.append(D.claim("s", 100, 120, f"c{i}", cfg=self.cfg, path=self.db)[0])) for i in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]; self.assertEqual(sum(res), 1)
    def test_empty_interval_rejected(self):
        with self.assertRaises(ValueError): D.claim("s", 5, 5, "a", cfg=self.cfg, path=self.db)

class Metadata(unittest.TestCase):
    def test_language(self):
        self.assertEqual(MD.detect_language("मेरा कंट्रोलर डिसकनेक्ट हो गया yaar"), "hi"); self.assertEqual(MD.detect_language("this is a plain english sentence"), "en"); self.assertEqual(MD.detect_language("hi"), "unknown")
    def test_game_is_never_guessed_from_transcript(self):
        t = MD.resolve_topic(None, "Late night stream", "GTA 6 is crazy"); self.assertFalse(t["verified"]); self.assertIsNone(t["game"])
    def test_game_verified_by_user_or_title(self):
        self.assertEqual(MD.resolve_topic("Minecraft", None, None)["game"], "Minecraft"); self.assertEqual(MD.resolve_topic(None, "GTA 6 LAUNCH LIVE", None)["game"], "GTA 6")
    def test_hashtags_follow_verified_topic(self):
        _, h = MD.tags_and_hashtags({"game": None, "verified": False}, "en"); self.assertNotIn("#GTA6", h); self.assertIn("#Gaming", h)
        _, h = MD.tags_and_hashtags({"game": "GTA 6", "verified": True}, "hi"); self.assertIn("#GTA6", h); self.assertIn("#HindiGaming", h)
        _, h = MD.tags_and_hashtags({"game": "Minecraft", "verified": True}, "en"); self.assertIn("#Minecraft", h); self.assertNotIn("#GTA6", h)
    def test_description_has_no_unverified_claims(self):
        plan = {"what_happens": "a plane theft fails", "scores": None, "reasons": []}
        md = MD.build_metadata({"plan": plan, "selected_text": "hello world this is some talk", "lang": "en", "topic": {"game": None, "verified": False, "evidence": ""},
                                "creator": {"name": None, "url": None, "known": False}, "source_url": "https://www.twitch.tv/x"}, chat=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
        d = md["description"].lower()
        for bad in ("permission", "launch week", "rockstar", "gta"): self.assertNotIn(bad, d)
        self.assertTrue(md["title"].strip()); self.assertEqual(md["language"], "en")
    def test_no_transcript_means_no_invented_title(self):
        called = []
        t, _ = MD.llm_title({"what_happens": ""}, "", "unknown", {"game": None, "verified": False}, {"name": None}, chat=lambda *a, **k: called.append(1) or {"title": "A person is shown", "summary": ["x"]})
        self.assertEqual((t, called), (None, []))
    def test_title_filter(self):
        self.assertFalse(MD.title_ok("A " + MD.BANNED_TITLE[0] + " clip", "en")); self.assertFalse(MD.title_ok("Controller disconnected at the worst time", "hi")); self.assertTrue(MD.title_ok("Controller disconnected at the worst time", "en")); self.assertFalse(MD.title_ok("hi", "en"))

class Config(unittest.TestCase):
    def test_broken_config_json_falls_back(self):
        p = os.path.join(tempfile.mkdtemp(), "config.json"); open(p, "w").write("{not json"); self.assertEqual(C.load(p)["thresholds"]["hook"], 7)
    def test_override_merges(self):
        p = os.path.join(tempfile.mkdtemp(), "config.json"); json.dump({"thresholds": {"hook": 5}}, open(p, "w")); c = C.load(p)
        self.assertEqual((c["thresholds"]["hook"], c["thresholds"]["clarity"]), (5, 7))

class Analytics(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.db = os.path.join(self.d, "a.sqlite3"); os.makedirs(os.path.join(self.d, "final"))
        json.dump({"title": "Controller gone", "youtube_url": "https://youtube.com/shorts/abcdefghijk", "schema_version": 2, "language": "hi", "framing": "context",
                   "durations": {"edited": 16.5}, "edit_plan": {"scores": {"hook": 7, "clarity": 8, "payoff": 9, "energy": 7}, "time_to_payoff": 7.4, "segments": [{"start": 22.8, "end": 39.3}]}},
                  open(os.path.join(self.d, "final", "c.json"), "w"))
        self.csv = os.path.join(self.d, "export.csv")
        with open(self.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["Content", "Video title", "Views", "Average view duration", "Average percentage viewed (%)", "Likes"])
            w.writerow(["Total", "", "200", "0:10", "30", "5"]); w.writerow(["abcdefghijk", "Controller gone", "1,200", "0:17", "52.5", "40"]); w.writerow(["zzzzzzzzzzz", "Unknown clip", "30", "-", "", ""])
    def test_import_and_join(self):
        n, k = AN.import_csv(self.csv, "48h", db=self.db); self.assertEqual((n, k), (2, 1))
        rows = AN.report(db=self.db, root=self.d); a = next(r for r in rows if r["video_id"] == "abcdefghijk"); u = next(r for r in rows if r["video_id"] == "zzzzzzzzzzz")
        self.assertTrue(a["matched"]); self.assertEqual((a["views"], a["avg_view_secs"], a["avg_pct_viewed"]), (1200, 17, 52.5)); self.assertEqual(a["retention_of_edit"], round(17 / 16.5, 2)); self.assertEqual(a["scores"]["payoff"], 7 + 2)
        self.assertFalse(u["matched"]); self.assertIsNone(u["avg_view_secs"])
    def test_reimport_updates_not_duplicates(self):
        AN.import_csv(self.csv, "48h", db=self.db); AN.import_csv(self.csv, "48h", db=self.db); AN.import_csv(self.csv, "7d", db=self.db)
        self.assertEqual(len(AN.report(db=self.db, root=self.d)), 4)
    def test_wrong_file_rejected(self):
        p = os.path.join(self.d, "bad.csv"); open(p, "w").write("a,b\n1,2\n")
        with self.assertRaises(ValueError): AN.import_csv(p, "x", db=self.db)
    def test_duration_parser(self):
        self.assertEqual(AN.num("1:02:03"), 3723); self.assertEqual(AN.num("0:17"), 17); self.assertIsNone(AN.num("-")); self.assertEqual(AN.num("12.5%"), 12.5)

if __name__ == "__main__": unittest.main()
