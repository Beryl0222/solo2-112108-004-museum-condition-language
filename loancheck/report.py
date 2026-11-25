"""渲染两馆下次签字时使用的 Markdown 交接包与回查收据。

交接包必须列出归还前本次核对适用的全部证据，以及仍有分歧的位置；
不把同一张照片的不同转述当作互相独立的确认。
"""
from __future__ import annotations

from .cases import ReceiptRecord
from .model import BatchResult
from .reconcile import BLOCKING_STATUSES

STATUS_LABELS = {
    "old_signed": "入场已签认旧痕",
    "old_recorded": "入场/展中记录旧痕",
    "old_quota": "笼统旧痕配额",
    "review_excluded": "复查排除（非新增）",
    "optical_excluded": "光学现象排除（投影/反光）",
    "new_pending": "待确认新痕（阻断放行）",
    "new_confirmed": "已确认新增（复核完成）",
    "disputed": "归属分歧（阻断放行）",
    "unresolved_located": "位点未解析（缺照片参照，阻断放行）",
    "case_note": "外箱层变化（未达本体）",
    "coverage_note": "覆盖性陈述（未见新增）",
}

LAYER_LABELS = {"body": "作品本体", "mount": "装裱", "case": "外箱"}


def render_packet(result: BatchResult) -> str:
    lines: list[str] = ["# 借件归还前状况核对交接包", ""]
    lines.append("本包由核对工具生成，所有结论均附报告登记号、原文小句与照片号；")
    lines.append("同一报告登记号视为一个独立来源，同一张照片的不同转述不重复计为确认。")
    lines.append("")

    for conclusion in result.conclusions:
        loan = conclusion.loan
        lines.append(f"## {loan.id} {loan.label}（所有方：{loan.owner}，当前箱号：{loan.case}）")
        lines.append("")
        lines.append(f"声明层面：{', '.join(loan.layers)}")
        lines.append("")
        if not conclusion.features:
            lines.append("- 未抽取到状况描述。")
            lines.append("")
            continue

        lines.append("### 状况特征与证据")
        for feature in conclusion.features:
            label = STATUS_LABELS.get(feature.status, feature.status)
            layer = LAYER_LABELS.get(feature.layer or "", feature.layer or "层面未判定")
            lines.append(
                f"- **{feature.id}｜{layer}｜{feature.family}｜{label}**"
            )
            locations = []
            for location in feature.locations:
                if location.frame == "unknown":
                    locations.append("未给定位点")
                elif not location.resolved:
                    locations.append(
                        f"照片坐标未解析（原文“{location.raw}”，参照缺失，禁止硬配）"
                    )
                else:
                    positions = [item for item in (location.side, location.vertical) if item]
                    face = f"{location.face}/" if location.face else ""
                    positions_text = "-".join(positions) if positions else "部位未细化"
                    edge = "边沿" if location.margin else ""
                    via = f"（经 {location.reference_view} 参照换算）" if location.reference_view else ""
                    locations.append(f"{face}{positions_text}{edge} {via}".strip())
            if locations:
                lines.append(f"  - 位点：{'；'.join(dict.fromkeys(locations))}")
            lines.append(
                f"  - 独立来源（按报告登记号）：{', '.join(feature.distinct_sources) or '无'}；"
                f"涉及照片：{', '.join(feature.photos) or '无'}"
            )
            if feature.quota is not None:
                lines.append(
                    f"  - 笼统旧痕配额：{feature.used_quota}/{feature.quota}"
                    f"（仅可吸收未定位描述，不得抵消明确新位点）"
                )
            lines.append("  - 原文证据：")
            for evidence in feature.evidence:
                lines.append(
                    f"    - [{evidence['report_id']}/{evidence['phase']}/{evidence['lang']}] "
                    f"“{evidence['clause']}”（肯定程度：{evidence['certainty']}，"
                    f"时间性：{evidence['temporal'] or '未声明'}，照片："
                    f"{', '.join(evidence['view_refs']) or '无'}）"
                )
            if feature.required_views:
                lines.append("  - 最少还需核对：")
                for need in feature.required_views:
                    lines.append(f"    - {need.description}——{need.reason}")
            if feature.note:
                lines.append(f"  - 备注：{feature.note}")
        lines.append("")

        open_features = [
            feature for feature in conclusion.features if feature.status in BLOCKING_STATUSES
        ]
        lines.append("### 仍有分歧/未决位置")
        if open_features:
            for feature in open_features:
                lines.append(
                    f"- {feature.id}（{STATUS_LABELS[feature.status]}）："
                    f"{feature.note or '需两馆在下次签字时确认'}"
                )
        else:
            lines.append("- 无阻断性未决项。")
        lines.append("")

        if conclusion.coverage_gaps:
            lines.append("### 视角/层面覆盖提示（非新增结论）")
            for gap in conclusion.coverage_gaps:
                lines.append(f"- {gap.description}")
            lines.append("")

    lines.append("## 封箱组合放行结论")
    for decision in result.case_decisions:
        verdict = "可放行" if decision.releasable else "不可放行"
        lines.append(
            f"### {decision.case_id}：{verdict}｜组合 {decision.loan_ids}"
            f"｜指纹 `{decision.combination_signature}`"
        )
        for reason in decision.reasons:
            lines.append(f"- {reason}")
        if decision.blocking:
            lines.append("- 阻断明细：")
            for item in decision.blocking:
                lines.append(f"  - {item}")
        lines.append("")
    return "\n".join(lines)


def render_receipt(receipt: ReceiptRecord) -> str:
    lines = [
        f"# 回查收据：{receipt.loan_id} {receipt.label}",
        "",
        f"- 所有方：{receipt.owner}",
        f"- 离馆箱号：{receipt.case_id}",
        f"- 实际放行组合：{receipt.releasable_with or '当前不可放行'}",
        f"- 封箱组合指纹：`{receipt.combination_signature}`",
        "",
        "## 离馆时旧痕与新增变化的区分依据",
        receipt.basis_text,
        "",
        f"## 旧痕（{len(receipt.old_marks)}）",
    ]
    for item in receipt.old_marks:
        lines.append(
            f"- {item['feature']}｜{LAYER_LABELS.get(item['layer'] or '', item['layer'])}"
            f"｜{item['family']}｜{STATUS_LABELS[item['status']]}"
            f"｜来源 {', '.join(item['sources'])}"
        )
    lines.append(f"## 新增或未决（{len(receipt.new_or_open)}）")
    if not receipt.new_or_open:
        lines.append("- 无")
    for item in receipt.new_or_open:
        lines.append(
            f"- {item['feature']}｜{item['family']}｜{STATUS_LABELS[item['status']]}"
            f"｜来源 {', '.join(item['sources'])}"
        )
    lines.append(f"## 排除项与留痕（{len(receipt.exclusions)}）")
    if not receipt.exclusions:
        lines.append("- 无")
    for item in receipt.exclusions:
        lines.append(
            f"- {item['feature']}｜{item['family']}｜{STATUS_LABELS[item['status']]}"
        )
    return "\n".join(lines)
