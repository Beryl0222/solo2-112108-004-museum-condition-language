"""封箱组合、签字绑定与放行规则。

业务约束：
- 一个借箱允许合装多件；签收对象是“实际可放行的封箱组合”。
- 签字绑定在签字时 snapshot 所见的箱号+借件号组合上；组合改变后旧签字
  不可套用，必须重新签字。
- 发现归还中的新变化时，只有该箱内相关物件所需复核均已完成且与该组合一致，
  才能放行受影响的箱。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from .model import (
    CaseDecision,
    Handover,
    Loan,
    LoanConclusion,
)
from .reconcile import (
    CASE_NOTE,
    COVERAGE_NOTE,
    OPTICAL_EXCLUDED,
    REVIEW_EXCLUDED,
)


def combination_signature(case_id: str, loan_ids: list[str]) -> str:
    """封箱组合的稳定指纹：箱号 + 排序后的借件号集合。"""
    payload = case_id + "|" + ",".join(sorted(loan_ids))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _snapshot_combo(handover: Handover) -> tuple[Optional[str], list[str]]:
    case_id = next((item for item in handover.snapshot if item.startswith("C")), None)
    loan_ids = sorted(item for item in handover.snapshot if item.startswith("L"))
    return case_id, loan_ids


def _combo_equal(case_id: str, loan_ids: list[str], handover: Handover) -> bool:
    signed_case, signed_loans = _snapshot_combo(handover)
    return signed_case == case_id and signed_loans == sorted(loan_ids)


def decide_cases(
    loans: list[Loan],
    conclusions: list[LoanConclusion],
    handovers: list[Handover],
) -> list[CaseDecision]:
    by_loan = {conclusion.loan.id: conclusion for conclusion in conclusions}
    current_cases: dict[str, list[str]] = {}
    for loan in loans:
        current_cases.setdefault(loan.case, []).append(loan.id)

    decisions: list[CaseDecision] = []
    for case_id in sorted(current_cases):
        loan_ids = sorted(current_cases[case_id])
        signature = combination_signature(case_id, loan_ids)
        reasons: list[str] = []
        blocking: list[dict] = []

        matched: Optional[Handover] = None
        proposals: list[Handover] = []
        for handover in handovers:
            signed_case, _ = _snapshot_combo(handover)
            if signed_case != case_id:
                continue
            if _combo_equal(case_id, loan_ids, handover):
                if handover.is_sealing:
                    matched = handover
                else:
                    proposals.append(handover)

        if matched is None:
            reasons.append(
                "当前封箱组合没有与之严格一致的已签字封箱记录；"
                "拟箱/改组记录不能代替签字，旧签字也不得套用到不同组合"
            )
            blocking.append({"type": "missing_seal", "case": case_id, "loans": loan_ids})
        else:
            reasons.append(
                f"封箱签字 {matched.id}（{matched.signer}，{matched.at}）"
                f"与当前组合 {case_id}+{loan_ids} 一致"
            )

        for loan_id in loan_ids:
            conclusion = by_loan[loan_id]
            for feature in conclusion.blocking_features():
                needs = [need.description for need in feature.required_views]
                blocking.append(
                    {
                        "type": feature.status,
                        "loan": loan_id,
                        "feature": feature.id,
                        "family": feature.family,
                        "layer": feature.layer,
                        "required_views": needs,
                        "distinct_sources": feature.distinct_sources,
                    }
                )
                reasons.append(
                    f"{loan_id} 的 {feature.id}（{feature.family}）"
                    f"尚未完成所需复核：{'；'.join(needs) or '需两馆确认归属'}"
                )

        releasable = not blocking
        if releasable:
            reasons.append("箱内物件无阻断性新增/分歧，所需复核均已完成，组合一致")

        decisions.append(
            CaseDecision(
                case_id=case_id,
                loan_ids=loan_ids,
                releasable=releasable,
                reasons=reasons,
                blocking=blocking,
                matched_handover=matched,
                proposed_handovers=proposals,
                combination_signature=signature,
            )
        )
    return decisions


@dataclass
class ReceiptRecord:
    """回查收据：实际离馆物件及其旧痕/新增区分依据。"""

    loan_id: str
    label: str
    case_id: str
    owner: str
    releasable_with: list[str]
    old_marks: list[dict]
    new_or_open: list[dict]
    exclusions: list[dict]
    basis_text: str
    combination_signature: str


def build_receipt(
    loan_id: str,
    loans: list[Loan],
    conclusions: list[LoanConclusion],
    decisions: list[CaseDecision],
) -> Optional[ReceiptRecord]:
    loan = next((item for item in loans if item.id == loan_id), None)
    if loan is None:
        return None
    conclusion = next(item for item in conclusions if item.loan.id == loan_id)
    decision = next(item for item in decisions if item.case_id == loan.case)

    old_marks, new_or_open, exclusions = [], [], []
    for feature in conclusion.features:
        payload = {
            "feature": feature.id,
            "layer": feature.layer,
            "family": feature.family,
            "status": feature.status,
            "sources": feature.distinct_sources,
            "photos": feature.photos,
            "evidence": feature.evidence,
        }
        if feature.status in {"old_signed", "old_recorded", "old_quota"}:
            old_marks.append(payload)
        elif feature.status in {REVIEW_EXCLUDED, OPTICAL_EXCLUDED, CASE_NOTE, COVERAGE_NOTE}:
            exclusions.append(payload)
        else:
            new_or_open.append(payload)

    basis_lines = [
        f"旧痕依据：{len(old_marks)} 项，来自入场/展中记录并经同位归并",
        "新增区分依据：退场观察先按物件坐标与旧痕比对，未命中且无独立复查"
        "排除者方列为新增/分歧；同照片转述只计一个来源",
    ]
    if decision.matched_handover:
        basis_lines.append(
            f"封箱依据：签字 {decision.matched_handover.id} 绑定组合指纹 "
            f"{decision.combination_signature}"
        )
    else:
        basis_lines.append("封箱依据：当前组合缺少一致签字，不得沿用其他组合的签字")

    return ReceiptRecord(
        loan_id=loan.id,
        label=loan.label,
        case_id=loan.case,
        owner=loan.owner,
        releasable_with=decision.loan_ids if decision.releasable else [],
        old_marks=old_marks,
        new_or_open=new_or_open,
        exclusions=exclusions,
        basis_text="；".join(basis_lines),
        combination_signature=decision.combination_signature,
    )


def open_required_views(decision: CaseDecision, conclusions: list[LoanConclusion]) -> list[str]:
    """汇总一个箱仍缺的最少复核视角。"""
    needs: list[str] = []
    by_loan = {item.loan.id: item for item in conclusions}
    for item in decision.blocking:
        loan_id = item.get("loan")
        feature_id = item.get("feature")
        if not loan_id or not feature_id:
            continue
        for feature in by_loan[loan_id].features:
            if feature.id == feature_id:
                for need in feature.required_views:
                    if need.description not in needs:
                        needs.append(need.description)
    return needs
