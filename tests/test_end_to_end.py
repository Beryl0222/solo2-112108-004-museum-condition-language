"""基于仓库合成资料的端到端业务场景测试。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loancheck.batch import run_batch  # noqa: E402
from loancheck.cases import build_receipt  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_batch(str(DATA))
        cls.by_loan = {
            conclusion.loan.id: conclusion for conclusion in cls.result.conclusions
        }
        cls.by_case = {
            decision.case_id: decision for decision in cls.result.case_decisions
        }

    def test_l1_photo_right_misread_resolves_to_old_fold(self):
        features = self.by_loan["L1"].features
        statuses = [feature.status for feature in features]
        self.assertIn("old_signed", statuses)
        self.assertIn("review_excluded", statuses)
        self.assertNotIn("new_pending", statuses)
        old_fold = next(feature for feature in features
                        if feature.status == "old_signed")
        # 中英双语、跨阶段多条描述合并为同一旧痕
        self.assertEqual(set(old_fold.distinct_sources),
                         {"I1", "M1", "O1", "O2"})

    def test_l1_exclusion_uses_independent_review_not_same_photo(self):
        excluded = next(
            feature for feature in self.by_loan["L1"].features
            if feature.status == "review_excluded"
        )
        self.assertEqual(set(excluded.distinct_sources), {"O1", "O2"})

    def test_l2_vague_quota_does_not_swallow_specific_new_lift(self):
        features = self.by_loan["L2"].features
        quota = next(feature for feature in features
                     if feature.status == "old_quota")
        self.assertEqual(quota.quota, 2)
        new_lifts = [feature for feature in features
                     if feature.status == "new_pending"]
        # 左上并入旧痕，右下作为不可抵消的新位点
        self.assertEqual(len(new_lifts), 1)
        self.assertEqual(new_lifts[0].locations[0].side, "right")
        self.assertEqual(new_lifts[0].locations[0].vertical, "bottom")

    def test_l3_recto_negative_coverage_and_sealed_release(self):
        features = self.by_loan["L3"].features
        self.assertTrue(any(feature.status == "coverage_note"
                            for feature in features))
        self.assertTrue(self.by_case["C2"].releasable)

    def test_l4_case_scratch_is_note_not_body_damage(self):
        features = self.by_loan["L4"].features
        self.assertTrue(any(feature.status == "case_note"
                            and feature.layer == "case"
                            for feature in features))
        self.assertFalse(any(feature.blocks_release for feature in features))

    def test_case_release_matrix(self):
        self.assertFalse(self.by_case["C1"].releasable)   # 无签字 + L2 新痕
        self.assertTrue(self.by_case["C2"].releasable)    # 已签封且无未决
        self.assertFalse(self.by_case["C3"].releasable)   # 仅拟改组无签字

    def test_recombinate_combination_needs_fresh_signature(self):
        c1 = self.by_case["C1"]
        self.assertIsNone(c1.matched_handover)
        proposal_actions = [
            handover.action for handover in c1.proposed_handovers
        ]
        self.assertIn("拟合箱", proposal_actions)

    def test_receipt_links_departure_to_evidence_basis(self):
        loans = [conclusion.loan for conclusion in self.result.conclusions]
        receipt = build_receipt(
            "L2", loans, self.result.conclusions, self.result.case_decisions
        )
        self.assertEqual(receipt.releasable_with, [])  # C1 阻断
        self.assertTrue(receipt.old_marks)
        self.assertTrue(receipt.new_or_open)
        self.assertIn("新增区分依据", receipt.basis_text)


if __name__ == "__main__":
    unittest.main()
