import math, unittest
import _fix as F
import editplan as E

W = F.words(F.SPEC); CFG = F.cfg(); DUR = F.DUR

class ParsePlan(unittest.TestCase):
    def test_valid_plan(self):
        p = E.parse_llm_plan(F.raw_plan(), W, DUR, CFG)
        self.assertEqual(p["decision"], "accept"); self.assertEqual(len(p["segments"]), 1)
        self.assertTrue(p["evidence"]["payoff"]["verified"]); self.assertAlmostEqual(p["time_to_payoff"], 14.0 - p["segments"][0]["start"], 2)
        self.assertEqual(p["scores"]["payoff"], 9.0)
    def test_malformed_answers_raise(self):
        bad = [None, "text", [], {}, {"decision": "maybe"}, F.raw_plan(segments=[]), F.raw_plan(segments=[{"start": 5, "end": 5}]),
               F.raw_plan(segments=[{"start": 20, "end": 10}]), F.raw_plan(segments=[{"start": -5, "end": 12}]), F.raw_plan(segments=[{"start": 5, "end": 400}]),
               F.raw_plan(segments=[{"start": float("nan"), "end": 12}]), F.raw_plan(segments=[{"start": "a", "end": "b"}]),
               F.raw_plan(scores=None), F.raw_plan(scores={"hook": 8, "clarity": 8, "payoff": 9}), F.raw_plan(scores={"hook": 8, "clarity": 8, "payoff": 11, "energy": 7}),
               F.raw_plan(scores={"hook": float("nan"), "clarity": 8, "payoff": 9, "energy": 7}), F.raw_plan(evidence={}), F.raw_plan(evidence={"opening": {"t": 11, "quote": ""}, "payoff": {"t": 14, "quote": "x"}})]
        for raw in bad:
            with self.subTest(raw=str(raw)[:60]), self.assertRaises(E.PlanError): E.parse_llm_plan(raw, W, DUR, CFG)
    def test_too_short_and_too_long(self):
        with self.assertRaises(E.PlanError): E.parse_llm_plan(F.raw_plan(segments=[{"start": 11, "end": 13}]), W, DUR, CFG)
        with self.assertRaises(E.PlanError): E.parse_llm_plan(F.raw_plan(segments=[{"start": 0, "end": 26}]), W, DUR, F.cfg(max_len=20))
    def test_unverifiable_quote_forces_review(self):
        ev = {"opening": {"t": 11.0, "quote": "watch this carefully now"}, "payoff": {"t": 14.0, "quote": "completely invented words never said"}}
        p = E.parse_llm_plan(F.raw_plan(evidence=ev), W, DUR, CFG)
        self.assertFalse(p["evidence"]["payoff"]["verified"]); self.assertEqual(p["decision"], "review")
    def test_out_of_order_segments_are_merged_not_trusted(self):
        segs = [{"start": 14, "end": 21.5}, {"start": 10, "end": 15}]
        p = E.parse_llm_plan(F.raw_plan(segments=segs), W, DUR, CFG)
        self.assertEqual(len(p["segments"]), 1); self.assertTrue(any("merged" in r for r in p["reasons"]))
    def test_reject_needs_no_segments(self):
        p = E.parse_llm_plan({"decision": "reject", "reasons": ["filler"]}, W, DUR, CFG)
        self.assertEqual((p["decision"], p["segments"]), ("reject", []))
    def test_late_payoff_flagged_and_tightened(self):
        p = E.parse_llm_plan(F.raw_plan(segments=[{"start": 0.0, "end": 21.5}]), W, DUR, F.cfg(max_time_to_payoff=8))
        self.assertTrue(p["late_payoff"]); self.assertEqual(p["decision"], "review")
        t = E.tighten(p, W, F.cfg(max_time_to_payoff=8, tighten_lead=4, tighten_tail=6, min_len=5), DUR)
        self.assertTrue(t["auto_tightened"]); self.assertLessEqual(t["time_to_payoff"], 8); self.assertEqual(E.boundary_report(t["segments"], W), [])

class Scores(unittest.TestCase):
    def test_energy_cannot_compensate(self):
        weak = {"hook": 3, "clarity": 3, "payoff": 3, "energy": 10}
        self.assertEqual(E.gate(weak, CFG)[0], "rejected"); self.assertLess(E.editorial_quality(weak), 6)
    def test_gate_levels(self):
        self.assertEqual(E.gate({"hook": 8, "clarity": 8, "payoff": 8, "energy": 1}, CFG)[0], "pass")
        self.assertEqual(E.gate({"hook": 6, "clarity": 8, "payoff": 8, "energy": 9}, CFG)[0], "needs_review")
        self.assertEqual(E.gate({"hook": 8, "clarity": 8, "payoff": 4, "energy": 9}, CFG)[0], "rejected")
    def test_quality_capped_by_weakest(self):
        self.assertLessEqual(E.editorial_quality({"hook": 10, "clarity": 10, "payoff": 4, "energy": 10}), 6.0)

class Boundaries(unittest.TestCase):
    def test_snapping_never_lands_inside_a_word(self):
        for t in [i * 0.07 for i in range(0, 360)]:
            with self.subTest(t=round(t, 2)):
                s = E.snap_start(W, t, CFG, DUR); e = E.snap_end(W, min(t + 6, DUR), CFG, DUR)
                self.assertFalse(any(w["s"] < s < w["e"] for w in W)); self.assertFalse(any(w["s"] < e < w["e"] for w in W))
    def test_snap_start_never_later_than_word(self):
        w = F.words("aa bb cc dd"); w[1]["s"] = w[0]["e"]            # touching words
        self.assertLessEqual(E.snap_start(w, (w[1]["s"] + w[1]["e"]) / 2, CFG, 10), w[1]["s"])
    def test_polish_trims_leading_filler_and_finishes_sentence(self):
        segs, notes = E.polish_segments([{"start": 0.0, "end": 2.6}], W, F.cfg(min_len=2), DUR)
        self.assertGreater(segs[0]["start"], 0.0)                                   # "so" dropped
        self.assertGreaterEqual(segs[0]["end"], 3.9)                                # "here." finished
        self.assertEqual(E.boundary_report(segs, W), [])
    def test_polish_respects_next_segment(self):
        segs, _ = E.polish_segments([{"start": 5.0, "end": 8.6}, {"start": 8.8, "end": 20.0}], W, F.cfg(min_len=2), DUR)
        self.assertLess(segs[0]["end"], segs[1]["start"])

class Remap(unittest.TestCase):
    def test_multi_segment_caption_remap(self):
        segs = [{"start": 5.0, "end": 10.4}, {"start": 14.0, "end": 17.0}]
        out, dropped = E.remap_words(W, segs); offs, total = E.segment_offsets(segs)
        self.assertAlmostEqual(total, 8.4, 3)
        first = next(w for w in out if w["w"] == "I"); self.assertAlmostEqual(first["s"], 0.0, 2)           # 'I' at 5.0 -> 0.0
        oh = next(w for w in out if w["w"] == "oh"); self.assertAlmostEqual(oh["s"], 5.4, 2)               # 14.0-14.0+5.4
        self.assertTrue(all(w["e"] <= total + 1e-6 for w in out)); self.assertTrue(all(a["s"] <= b["s"] for a, b in zip(out, out[1:])))
        self.assertNotIn("watch", [w["w"] for w in out])                                                   # fell in the cut
    def test_straddling_word_dropped_and_counted(self):
        out, dropped = E.remap_words(W, [{"start": 5.2, "end": 9.0}])
        self.assertEqual(dropped, 1); self.assertNotIn("I", [w["w"] for w in out])    # 'I' (5.0-5.4) straddles the start; 'away' starts exactly at the end (not dropped)
    def test_selected_transcript_matches_remap(self):
        segs = [{"start": 10.0, "end": 21.5}]
        self.assertEqual(E.selected_transcript(W, segs).split(), [w["w"] for w in E.remap_words(W, segs)[0]])

class Utility(unittest.TestCase):
    def test_clean_words_drops_garbage(self):
        out = E.clean_words([{"w": "a", "s": 1, "e": 2}, {"w": "", "s": 1, "e": 2}, {"w": "b", "s": float("nan"), "e": 2}, {"w": "c", "s": 3, "e": 2}, "x", None, {"w": "d", "s": -1, "e": 1}])
        self.assertEqual([w["w"] for w in out], ["a"])
    def test_hindi_quote_matching(self):
        hw = F.words("मेरा कंट्रोलर डिसकनेक्ट हो गया"); self.assertTrue(E.quote_in(hw, "कंट्रोलर डिसकनेक्ट हो गया", 0, 5))
        self.assertFalse(E.quote_in(hw, "बिल्कुल अलग बात", 0, 5))
    def test_heuristic_plan_is_unscored(self):
        p = E.heuristic_plan(W, 14.0, DUR, CFG); self.assertIsNone(p.get("scores")); self.assertEqual(E.boundary_report(p["segments"], W), [])

if __name__ == "__main__": unittest.main()
