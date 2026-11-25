"""按资料说明装载 JSONL 批次资料并做引用完整性校验。"""
from __future__ import annotations

import json
from pathlib import Path

from .model import Handover, Loan, Report, View


def _read_jsonl(root: Path, name: str, fields: list[str]) -> list[dict]:
    rows: list[dict] = []
    with (root / f"{name}.jsonl").open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{name} 第 {line_number} 行不是有效的 JSON") from error
            if not isinstance(record, dict) or set(record.keys()) != set(fields):
                raise ValueError(f"{name} 第 {line_number} 行字段与资料索引不符")
            rows.append(record)
    return rows


def load_batch(directory: str) -> tuple[list[Loan], dict[str, View], list[Report],
                                        list[Handover], list[str]]:
    """返回借件、照片（按 id 索引）、报告、签字记录与数据告警。"""
    root = Path(directory)
    manifest = json.loads((root / "index.json").read_text(encoding="utf-8"))
    warnings: list[str] = []

    loans = [Loan(**row) for row in _read_jsonl(root, "loans", manifest["loans"])]
    views = {
        row["id"]: View(**row)
        for row in _read_jsonl(root, "views", manifest["views"])
    }
    reports = [Report(**row) for row in _read_jsonl(root, "reports", manifest["reports"])]
    handovers = [
        Handover(**row) for row in _read_jsonl(root, "handovers", manifest["handovers"])
    ]

    loan_ids = {loan.id for loan in loans}
    # 引用完整性
    for view in views.values():
        if view.loan not in loan_ids:
            warnings.append(f"views {view.id} 指向不存在的借件 {view.loan}")
        for scope in view.scope:
            loan = next((item for item in loans if item.id == view.loan), None)
            if loan and scope not in loan.layers:
                warnings.append(
                    f"views {view.id} 的 scope {scope} 不在 {view.loan} 声明层面内"
                )
    for report in reports:
        if report.loan not in loan_ids:
            warnings.append(f"reports {report.id} 指向不存在的借件 {report.loan}")
        for ref in report.references:
            if ref not in views:
                warnings.append(f"reports {report.id} 引用不存在的照片 {ref}")
            elif views[ref].loan != report.loan:
                warnings.append(f"reports {report.id} 引用了他件照片 {ref}")
    for handover in handovers:
        for item in handover.snapshot:
            if item.startswith("L") and item not in loan_ids:
                warnings.append(f"handovers {handover.id} 快照含不存在借件 {item}")
            if item.startswith("V") and item not in views:
                warnings.append(f"handovers {handover.id} 快照含不存在照片 {item}")
        if handover.scope == "record":
            report_ids = {report.id for report in reports}
            for item in handover.snapshot:
                if item not in report_ids:
                    warnings.append(
                        f"handovers {handover.id} 签字记录 {item} 在 reports 中不存在"
                    )
    return loans, views, reports, handovers, warnings
