"""双语解析器测试：材质受限同义、肯定程度、证据保留。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loancheck.model import CERT_NEGATED, CERT_UNCERTAIN, Report, View  # noqa: E402
from loancheck.parser import parse_report  # noqa: E402


def view(view_id, right="right", top="top", scope=None):
    return View(view_id, "Lx", right, top, scope or ["paper", "mount"])


class ParserTests(unittest.TestCase):
    def test_zh_clause_keeps_raw_evidence_and_old_temporal(self):
        report = Report("R1", "Lx", "in", "登记", "zh", 1, ["V1"],
                        "本体左上外沿旧浅折。")
        result = parse_report(report, {"V1": view("V1")}, "paper")
        self.assertEqual(len(result.observations), 1)
        observation = result.observations[0]
        self.assertEqual(observation.family, "fold")
        self.assertEqual(observation.temporal, "old")
        self.assertEqual(observation.location.side, "left")
        self.assertEqual(observation.location.vertical, "top")
        self.assertTrue(observation.location.margin)
        self.assertEqual(observation.clause, "本体左上外沿旧浅折")
        self.assertIsInstance(observation.span, tuple)

    def test_english_bare_right_margin_is_photo_frame(self):
        report = Report("R2", "Lx", "out", "reg", "en", 1, ["V1"],
                        "Old faint fold at right margin.")
        result = parse_report(report, {"V1": view("V1", right="left")}, "paper")
        observation = result.observations[0]
        # 裸写 right margin 按照片坐标处理；镜像照片换算后落到物件左，
        # 不得当作画作右缘
        self.assertEqual(observation.location.frame, "object")
        self.assertEqual(observation.location.side, "left")
        self.assertTrue(observation.location.resolved)
        self.assertEqual(observation.location.reference_view, "V1")
        self.assertIn("margin", observation.location.raw)

    def test_bare_margin_without_reference_stays_unresolved(self):
        no_ref = View("Vu", "Lx", None, "top", ["paper"])
        report = Report("R2b", "Lx", "out", "reg", "en", 1, ["Vu"],
                        "A line at right margin.")
        result = parse_report(report, {"Vu": no_ref}, "paper")
        observation = next(item for item in result.observations
                           if item.family in ("fold", "lift"))
        self.assertEqual(observation.location.frame, "photo")
        self.assertFalse(observation.location.resolved)

    def test_line_synonym_only_valid_in_body_material(self):
        report = Report("R3", "Lx", "out", "reg", "en", 1, ["V1"],
                        "A second line looks raised.")
        paper = parse_report(report, {"V1": view("V1")}, "paper")
        families = {item.family for item in paper.observations}
        self.assertIn("lift", families)
        # 装裱层面下 line 不按本体折痕家族处理
        mount_report = Report("R4", "Lx", "out", "reg", "en", 1, ["V1"],
                              "A line in the mount shadow.")
        mount = parse_report(mount_report, {"V1": view("V1")}, "paper")
        self.assertTrue(all(item.layer != "body" or item.family != "fold"
                            for item in mount.observations))

    def test_uncertain_shadow_alternative_is_recorded(self):
        report = Report("R5", "Lx", "out", "reg", "en", 1, ["V1"],
                        "A second line looks raised in V1; could be a mount shadow.")
        result = parse_report(report, {"V1": view("V1")}, "paper")
        lift = next(item for item in result.observations if item.family == "lift")
        self.assertEqual(lift.certainty, CERT_UNCERTAIN)
        self.assertIn("shadow", lift.alternatives)
        shadow = next(item for item in result.observations
                      if item.family == "shadow")
        self.assertEqual(shadow.certainty, CERT_UNCERTAIN)

    def test_no_new_marks_is_coverage_not_damage(self):
        report = Report("R6", "Lx", "out", "reg", "en", 1, ["V1"],
                        "No new marks discernible on recto.")
        result = parse_report(report, {"V1": view("V1")}, "paper")
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(result.observations[0].family, "coverage_none")
        self.assertEqual(result.observations[0].certainty, CERT_NEGATED)

    def test_multi_location_clause_is_split_with_evidence(self):
        report = Report("R7", "Lx", "out", "登记", "zh", 1, ["V1"],
                        "织物左上和右下各有一处翘起。")
        result = parse_report(report, {"V1": view("V1")}, "cloth")
        lifts = [item for item in result.observations if item.family == "lift"]
        self.assertEqual(len(lifts), 2)
        self.assertEqual({(item.location.side, item.location.vertical)
                          for item in lifts}, {("left", "top"), ("right", "bottom")})
        self.assertTrue(all(item.count == 1 for item in lifts))
        self.assertTrue(all("拆出" in (item.note or "") for item in lifts))

    def test_confinement_negation_keeps_case_damage(self):
        report = Report("R8", "Lx", "out", "reg", "en", 1, ["V1"],
                        "Case scratch does not reach artwork.")
        views = {"V1": View("V1", "Lx", "right", "top", ["paper", "crate"])}
        result = parse_report(report, views, "paper")
        scratch = next(item for item in result.observations
                       if item.family == "scratch")
        self.assertEqual(scratch.layer, "case")
        self.assertNotEqual(scratch.certainty, CERT_NEGATED)

    def test_review_clause_marks_optical_observation(self):
        report = Report("R9", "Lx", "out", "保护组", "zh", 1, ["V1"],
                        "翻看了背面，右侧线来自装裱投影。")
        result = parse_report(report, {"V1": view("V1")}, "paper")
        shadow = next(item for item in result.observations
                      if item.family == "shadow")
        self.assertTrue(shadow.review)


if __name__ == "__main__":
    unittest.main()
