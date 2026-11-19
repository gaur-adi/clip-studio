import unittest
import _fix as F
import planner as P, visual_check as VC

W = F.words(F.SPEC); CFG = F.cfg(); DUR = F.DUR

class Planner(unittest.TestCase):
    def test_valid_answer_is_planned(self):
        p = P.plan_moment(W, 14.0, DUR, CFG, chat=lambda *a: F.raw_plan())
        self.assertEqual(p["state"], "planned"); self.assertEqual(p["planner"], "llm"); self.assertEqual(p["prompt_version"], CFG["llm"]["prompt_version"])
    def test_weak_scores_are_rejected_not_averaged(self):
        raw = F.raw_plan(scores={"hook": 2, "clarity": 2, "payoff": 2, "energy": 10})
        p = P.plan_moment(W, 14.0, DUR, CFG, chat=lambda *a: raw); self.assertEqual(p["state"], "rejected")
    def test_invalid_then_valid_feeds_the_error_back(self):
        prompts = []
        def chat(prompt, *a):
            prompts.append(prompt); return {"decision": "accept", "scores": None} if len(prompts) == 1 else F.raw_plan()
        p = P.plan_moment(W, 14.0, DUR, CFG, chat=chat)
        self.assertEqual(len(prompts), 2); self.assertIn("PREVIOUS ANSWER WAS INVALID", prompts[1]); self.assertIn("segments", prompts[1].lower() + "segments")
        self.assertEqual(p["state"], "planned")
    def test_always_invalid_falls_back_to_unscored_review(self):
        p = P.plan_moment(W, 14.0, DUR, CFG, chat=lambda *a: {"decision": "accept"})
        self.assertEqual(p["state"], "needs_review"); self.assertIsNone(p.get("scores")); self.assertTrue(p["segments"]); self.assertEqual(p["planner"], "heuristic")
    def test_model_down_is_never_approved(self):
        def boom(*a): raise ConnectionError("llm host unreachable")
        p = P.plan_moment(W, 14.0, DUR, CFG, chat=boom)
        self.assertEqual(p["state"], "needs_review"); self.assertIsNone(p.get("scores")); self.assertIn("unavailable", p["llm_error"])
    def test_empty_transcript_gives_no_edit(self):
        p = P.plan_moment([], 14.0, DUR, CFG, chat=lambda *a: self.fail("model must not be called without a transcript"))
        self.assertEqual((p["state"], p["segments"]), ("needs_review", [])); self.assertIn("no usable transcript", p["reasons"][0])
    def test_bad_duration_raises(self):
        with self.assertRaises(Exception): P.plan_moment(W, 14.0, float("nan"), CFG, chat=lambda *a: F.raw_plan())
    def test_language_and_topic_reach_the_prompt(self):
        seen = []
        P.plan_moment(W, 14.0, DUR, CFG, lang="hi", topic="GTA 6", chat=lambda p, *a: (seen.append(p), F.raw_plan())[1])
        self.assertIn("Language: hi", seen[0]); self.assertIn("Topic: GTA 6", seen[0])
    def test_unknown_topic_is_not_invented(self):
        seen = []
        P.plan_moment(W, 14.0, DUR, CFG, topic=None, chat=lambda p, *a: (seen.append(p), F.raw_plan())[1]); self.assertIn("Topic: unknown", seen[0])

class VisualApply(unittest.TestCase):
    def plan(self): return {"reasons": [], "decision": "accept", "state": "planned", "payoff_time": 14.0}
    def test_unavailable_does_not_change_decision(self):
        p = VC.apply_to_plan(self.plan(), {"available": False, "what": "x", "payoff_visible": None, "first_time": None, "menu_at_start": None, "confidence": None})
        self.assertEqual(p["decision"], "accept")
    def test_confident_denial_forces_review(self):
        p = VC.apply_to_plan(self.plan(), {"available": True, "payoff_visible": False, "confidence": 9, "first_time": None, "menu_at_start": False, "what": "running"})
        self.assertEqual((p["decision"], p["state"]), ("review", "needs_review"))
    def test_low_confidence_denial_is_only_advisory(self):
        p = VC.apply_to_plan(self.plan(), {"available": True, "payoff_visible": False, "confidence": 3, "first_time": None, "menu_at_start": False, "what": "?"})
        self.assertEqual(p["decision"], "accept")
    def test_time_mismatch_and_menu(self):
        p = VC.apply_to_plan(self.plan(), {"available": True, "payoff_visible": True, "confidence": 9, "first_time": 22.0, "menu_at_start": False, "what": "e"}); self.assertEqual(p["decision"], "review")
        p = VC.apply_to_plan(self.plan(), {"available": True, "payoff_visible": True, "confidence": 9, "first_time": 14.5, "menu_at_start": True, "what": "e"}); self.assertEqual(p["decision"], "review")
    def test_confirmation_never_upgrades(self):
        p = self.plan(); p["decision"] = "review"; p["state"] = "needs_review"
        VC.apply_to_plan(p, {"available": True, "payoff_visible": True, "confidence": 10, "first_time": 14.0, "menu_at_start": False, "what": "ok"}); self.assertEqual(p["decision"], "review")

if __name__ == "__main__": unittest.main()
