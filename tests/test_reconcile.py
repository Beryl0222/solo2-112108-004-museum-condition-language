"""核对引擎测试：旧痕归并、配额、复查排除、缺参照、最少补核。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loancheck.model import (  # noqa: E402
    CERT_CONFIRMED,
    CERT_UNCERTAIN,
    Handover,
    Loan,
    ObjectLocation,
    Observation,
    View,
)
from loancheck.reconcile import (  # noqa: E402
    NEW_PENDING,
    OLD_QUOTA,
    OLD_SIGNED,
    REVIEW_EXCLUDED,
    UNRESOLVED_LOCATED,
    _EntrySigning,
    reconcile_loan,
)


def loan(loan_id="Lx", layers=None):
    return Loan(loan_id, "测试件", layers or ["paper", "mount", "crate"],
                "Cx", "北馆")


def obs(report_id, phase, family, certainty=CERT_CONFIRMED, temporal=None,
        layer="body", location=None, refs=None, alternatives=None,
        review=False, clause="", count=None):
    return Observation(
        report_id=report_id, loan_id="Lx", phase=phase, lang="zh",
        clause=clause or report_id, span=(0, 1), layer=layer, family=family,
        certainty=certainty,
        location=location or ObjectLocation(frame="unknown"),
        count=count, view_refs=refs or [], evidence_phrases=[],
        alternatives=alternatives or [], temporal=temporal, review=review,
        note=None,
    )


def signing(report_ids):
    return _EntrySigning(signed_report_ids=set(report_ids), warnings=[])


VIEWS = {
    "V1": View("V1", "Lx", "right", "top", ["paper", "mount"]),
    "V2": View("V2", "Lx", "left", "top", ["paper", "mount"]),
    "Vu": View("Vu", "Lx", None, "top", ["paper"]),
}


class ReconcileTests(unittest.TestCase):
    def test_multilingual_descriptions_merge_into_one_old_mark(self):
        observations = [
            obs("I1", "in", "fold", temporal="old",
                location=ObjectLocation(frame="object", side="left",
                                        vertical="top", margin=True),
                refs=["V1"], clause="本体左上外沿旧浅折"),
            obs("M1", "mid", "fold", temporal="old",
                location=ObjectLocation(frame="object", vertical="top",
                                        margin=True),
                refs=["V1"], clause="upper edge crease remains"),
            obs("O1", "out", "fold", temporal="old",
                location=ObjectLocation(frame="object", side="left",
                                        margin=True, reference_view="V2"),
                refs=["V2"], clause="旧折未变"),
        ]
        conclusion = reconcile_loan(loan(), observations, VIEWS, signing(["I1"]))
        folds = [f for f in conclusion.features if f.family == "fold"]
        self.assertEqual(len(folds), 1)
        self.assertEqual(folds[0].status, OLD_SIGNED)
        self.assertEqual(folds[0].distinct_sources, ["I1", "M1", "O1"])

    def test_vague_two_lifts_cannot_offset_specific_new_position(self):
        observations = [
            obs("I2", "in", "lift", count=2,
                location=ObjectLocation(frame="object", margin=True),
                refs=["V1"], clause="边缘两处起翘"),
            obs("O3", "out", "lift",
                location=ObjectLocation(frame="object", side="right",
                                        vertical="bottom", margin=True),
                refs=["V1"], clause="右下一处翘起"),
        ]
        conclusion = reconcile_loan(loan(), observations, VIEWS, signing(["I2"]))
        quota = next(f for f in conclusion.features if f.status == OLD_QUOTA)
        self.assertEqual(quota.quota, 2)
        self.assertEqual(quota.used_quota, 0)  # 明确新位点不走配额
        new = next(f for f in conclusion.features if f.status == NEW_PENDING)
        self.assertTrue(new.blocks_release)
        self.assertTrue(new.required_views)

    def test_independent_verso_review_excludes_new_suspect(self):
        observations = [
            obs("O1", "out", "lift", CERT_UNCERTAIN, temporal="new",
                location=ObjectLocation(frame="unknown"),
                refs=["Vu"], alternatives=["shadow"],
                clause="A second line looks raised in Vu"),
            obs("O2", "out", "shadow", CERT_CONFIRMED, layer="mount",
                location=ObjectLocation(frame="object", side="right"),
                refs=["V1"], review=True, clause="右侧线来自装裱投影"),
        ]
        conclusion = reconcile_loan(loan(), observations, VIEWS, signing([]))
        statuses = [f.status for f in conclusion.features]
        self.assertIn(REVIEW_EXCLUDED, statuses)
        self.assertNotIn(NEW_PENDING, statuses)
        excluded = next(f for f in conclusion.features
                        if f.status == REVIEW_EXCLUDED)
        self.assertEqual(set(excluded.distinct_sources), {"O1", "O2"})

    def test_same_photo_paraphrase_is_not_independent_confirmation(self):
        # 同一报告登记号、同一照片的两份转述只能算一个来源，不能自行排除
        observations = [
            obs("O1", "out", "lift", CERT_UNCERTAIN, temporal="new",
                location=ObjectLocation(frame="unknown"),
                refs=["Vu"], alternatives=["shadow"],
                clause="looks raised"),
            obs("O1b", "out", "shadow", CERT_CONFIRMED, layer="mount",
                location=ObjectLocation(frame="unknown"),
                refs=["Vu"], review=True, clause="same report shadow call"),
        ]
        conclusion = reconcile_loan(loan(), observations, VIEWS, signing([]))
        self.assertFalse(
            any(f.status == REVIEW_EXCLUDED for f in conclusion.features)
        )

    def test_missing_photo_reference_blocks_hard_matching(self):
        observations = [
            obs("I1", "in", "fold", temporal="old",
                location=ObjectLocation(frame="object", side="left",
                                        vertical="top", margin=True),
                refs=["V1"], clause="左上旧折"),
            obs("O1", "out", "fold", temporal="new",
                location=ObjectLocation(frame="photo", side="right",
                                        resolved=False, raw="photo right"),
                refs=["Vu"], clause="photo right 有新折"),
        ]
        conclusion = reconcile_loan(loan(), observations, VIEWS, signing(["I1"]))
        unresolved = next(
            f for f in conclusion.features if f.status == UNRESOLVED_LOCATED
        )
        self.assertTrue(unresolved.blocks_release)
        self.assertTrue(
            any(need.need_code == "photo_reference"
                for need in unresolved.required_views)
        )

    def test_minimum_required_views_are_deduplicated(self):
        observations = [
            obs("O1", "out", "lift", CERT_UNCERTAIN, temporal="new",
                location=ObjectLocation(frame="unknown"),
                refs=["Vu"], alternatives=["shadow"]),
        ]
        conclusion = reconcile_loan(loan(), observations, VIEWS, signing([]))
        feature = conclusion.features[0]
        codes = [need.need_code for need in feature.required_views]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertIn("verso_review", codes)

    def test_same_report_paraphrases_count_as_one_source(self):
        location = ObjectLocation(frame="object", side="left", vertical="top",
                                  margin=True)
        observations = [
            obs("I1", "in", "fold", temporal="old", location=location,
                refs=["V1"], clause="第一份转述"),
            obs("I1", "in", "fold", temporal="old", location=location,
                refs=["V1"], clause="同报告的另一份转述"),
            obs("M1", "mid", "fold", temporal="old", location=location,
                refs=["V1"], clause="另一登记号确认"),
        ]
        conclusion = reconcile_loan(loan(), observations, VIEWS, signing(["I1"]))
        fold = next(feature for feature in conclusion.features
                    if feature.family == "fold")
        self.assertEqual(fold.distinct_sources, ["I1", "M1"])
        # 照片号仍完整保留，证据链不丢失
        self.assertEqual(fold.photos, ["V1"])
        self.assertEqual(len(fold.evidence), 3)


if __name__ == "__main__":
    unittest.main()
