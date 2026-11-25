"""整批核对的编排：装载 -> 解析 -> 逐件核对 -> 封箱判定。"""
from __future__ import annotations

from .cases import decide_cases
from .loader import load_batch
from .model import BatchResult, LoanConclusion
from .parser import parse_reports
from .reconcile import entry_signed_reports, reconcile_loan


def run_batch(directory: str) -> BatchResult:
    loans, views, reports, handovers, data_warnings = load_batch(directory)
    body_materials = {loan.id: loan.body_material for loan in loans}
    parsed = parse_reports(reports, views, body_materials)
    signing = entry_signed_reports(handovers)

    conclusions: list[LoanConclusion] = []
    for loan in loans:
        observations = [item for item in parsed.observations if item.loan_id == loan.id]
        conclusion = reconcile_loan(loan, observations, views, signing)
        conclusion.warnings = parsed.warnings + conclusion.warnings
        conclusions.append(conclusion)

    decisions = decide_cases(loans, conclusions, handovers)
    return BatchResult(
        conclusions=conclusions,
        case_decisions=decisions,
        data_warnings=data_warnings + parsed.warnings,
    )
