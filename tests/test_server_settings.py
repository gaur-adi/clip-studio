import json, os, tempfile, unittest
import _fix as F
import server as S

class Settings(unittest.TestCase):
    def setUp(self): self.old = S.ROOT; S.ROOT = tempfile.mkdtemp(); S.C.ROOT = S.ROOT
    def tearDown(self): S.ROOT = self.old; S.C.ROOT = self.old
    def test_valid_change_is_saved_and_merged(self):
        c = S.save_settings({"thresholds": {"hook": 6}, "auto_approve": True, "framing": {"default": "gameplay"}})
        self.assertEqual(c["thresholds"]["hook"], 6); self.assertEqual(c["thresholds"]["clarity"], 7); self.assertTrue(c["auto_approve"]); self.assertEqual(c["framing"]["default"], "gameplay")
        S.save_settings({"thresholds": {"payoff": 8}}); self.assertEqual(json.load(open(os.path.join(S.ROOT, "config.json")))["thresholds"], {"hook": 6.0, "payoff": 8.0})
    def test_out_of_range_and_unknown_rejected(self):
        for bad in ({"thresholds": {"hook": 11}}, {"edit": {"min_len": 1}}, {"framing": {"default": "weird"}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError): S.save_settings(bad)
    def test_unknown_keys_are_ignored(self):
        S.save_settings({"llm": {"max_tokens": 1}, "secrets": "x"}); self.assertFalse(os.path.exists(os.path.join(S.ROOT, "config.json")) and "secrets" in open(os.path.join(S.ROOT, "config.json")).read())

if __name__ == "__main__": unittest.main()
