"""封箱组合、签字绑定、放行与回查收据测试。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loancheck.cases import (  # noqa: E402
    build_receipt,
    combination_signature,
    decide_cases,
)
from loancheck.model import (  # noqa: E402
    Feature,
    Handover,
    Loan,
    LoanConclusion,
    ObjectLocation,
    RequiredView,
)
from loancheck.reconcile import NEW_PENDING  # noqa: E402


def make_loan(loan_id, case_id):
    return Loan(loan_id, loan_id, ["paper", "mount", "crate"], case_id, "北馆")


def conclusion_with_new_mark(loan_obj):
    feature = Feature(
        id=f"{loan_obj.id}-F1", loan_id=loan_obj.id, layer="body",
        family="lift", status=NEW_PENDING,
        location_key=("object", "right", "bottom"),
        locations=[ObjectLocation(frame="object", side="right",
                                  vertical="bottom", margin=True)],
        observation_ids=["O1"], evidence=[], distinct_sources=["O1"],
        photos=["V1"],
        required_views=[RequiredView(
            need_code="independent_review",
            description="保护人员独立复查", reason="测试",
            related_feature=f"{loan_obj.id}-F1",
        )],
    )
    return LoanConclusion(loan=loan_obj, features=[feature])


def seal(handover_id, case_id, loan_ids):
    return Handover(handover_id, "东馆", "case", [case_id, *loan_ids],
                    "已签封箱", "2026-11-24T15:00:00+08:00")


def proposal(handover_id, case_id, loan_ids):
    return Handover(handover_id, "借展库房", "case", [case_id, *loan_ids],
                    "拟改组", "2026-11-24T17:00:00+08:00")


class CaseTests(unittest.TestCase):
    def test_signature_is_stable_for_same_combination(self):
        first = combination_signature("C1", ["L1", "L2"])
        second = combination_signature("C1", ["L2", "L1"])
        self.assertEqual(first, second)
        self.assertNotEqual(first, combination_signature("C1", ["L1"]))

    def test_sealed_case_without_open_marks_is_releasable(self):
        loans = [make_loan("L3", "C2")]
        conclusions = [LoanConclusion(loan=loans[0])]
        handovers = [seal("s2", "C2", ["L3"])]
        decisions = decide_cases(loans, conclusions, handovers)
        self.assertTrue(decisions[0].releasable)
        self.assertEqual(decisions[0].matched_handover.id, "s2")

    def test_proposal_cannot_replace_seal(self):
        loans = [make_loan("L4", "C3")]
        conclusions = [LoanConclusion(loan=loans[0])]
        handovers = [proposal("p2", "C3", ["L4"])]
        decisions = decide_cases(loans, conclusions, handovers)
        self.assertFalse(decisions[0].releasable)
        self.assertIsNone(decisions[0].matched_handover)
        self.assertTrue(any("签字" in reason for reason in decisions[0].reasons))

    def test_old_seal_does_not_apply_to_recombined_set(self):
        loans = [make_loan("L1", "C1"), make_loan("L4", "C1")]
        conclusions = [LoanConclusion(loan=item) for item in loans]
        # 旧签字绑定的是 C1+L1+L2，当前组合已变为 C1+L1+L4
        handovers = [seal("s-old", "C1", ["L1", "L2"])]
        decisions = decide_cases(loans, conclusions, handovers)
        self.assertFalse(decisions[0].releasable)
        self.assertIsNone(decisions[0].matched_handover)

    def test_open_new_mark_blocks_case_until_reviews_complete(self):
        loans = [make_loan("L2", "C1")]
        conclusions = [conclusion_with_new_mark(loans[0])]
        handovers = [seal("s1", "C1", ["L2"])]
        decisions = decide_cases(loans, conclusions, handovers)
        self.assertFalse(decisions[0].releasable)
        self.assertEqual(decisions[0].blocking[0]["type"], NEW_PENDING)
        self.assertIn("保护人员独立复查",
                      decisions[0].blocking[0]["required_views"][0])

    def test_receipt_identifies_actual_departure_basis(self):
        loans = [make_loan("L3", "C2")]
        conclusions = [LoanConclusion(loan=loans[0])]
        decisions = decide_cases(
            loans, conclusions, [seal("s2", "C2", ["L3"])]
        )
        receipt = build_receipt("L3", loans, conclusions, decisions)
        self.assertEqual(receipt.releasable_with, ["L3"])
        self.assertIn("封箱依据", receipt.basis_text)
        self.assertIn(receipt.combination_signature, receipt.basis_text)


if __name__ == "__main__":
    unittest.main()
