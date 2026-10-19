import unittest

from agents_store.more.profile import load_profile


class ProfileFromSpec(unittest.TestCase):
    """The profile is read from lean-model/kernel-proposal.json, not restated."""

    @classmethod
    def setUpClass(cls):
        cls.p = load_profile()

    def test_spec_version_is_v4(self):
        self.assertEqual(self.p.spec_version, 4)

    def test_nine_levels_in_order(self):
        self.assertEqual(self.p.levels, ("Fachgebiet", "Anwendungsfall", "BP", "CM", "UI",
                                         "API", "TC", "AC", "DEC"))

    def test_parents(self):
        self.assertIsNone(self.p.parent["Fachgebiet"])
        self.assertEqual(self.p.parent["Anwendungsfall"], "Fachgebiet")
        for lvl in ("BP", "CM", "UI", "API", "TC", "AC", "DEC"):
            self.assertEqual(self.p.parent[lvl], "Anwendungsfall")

    def test_one_english_question_per_level(self):
        for lvl in self.p.levels:
            self.assertTrue(self.p.questions[lvl].en.strip(), lvl)
        self.assertEqual(self.p.questions["AC"].de, "Wann ist die Anforderung fachlich erfüllt?")

    def test_jwf_status_model_is_profile_data(self):
        m = self.p.status_model
        self.assertEqual(len(m.states), 15)
        self.assertEqual(len(set(m.states)), 15)
        self.assertEqual(m.states[0], "Neu")
        self.assertEqual(m.states[-1], "Geschlossen")
        self.assertEqual(sorted(m.gates), ["QG1", "QG2", "QG3"])
        self.assertEqual(len(m.phases), 4)

    def test_no_reflow_or_cutover_state(self):
        for s in self.p.status_model.states:
            self.assertNotRegex(s.casefold(), r"reflow|cut-?over")


if __name__ == "__main__":
    unittest.main()
