"""命令行入口：check / parse / packet / receipt 四个子命令，按借件批次复用。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .batch import run_batch
from .cases import build_receipt
from .loader import load_batch
from .parser import parse_reports
from .report import render_packet, render_receipt


def _cmd_check(args: argparse.Namespace) -> int:
    result = run_batch(args.data)
    output = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)
    blocked = [decision for decision in result.case_decisions if not decision.releasable]
    summary = {
        decision.case_id: ("放行" if decision.releasable else "阻断")
        for decision in result.case_decisions
    }
    print(json.dumps({"箱结论": summary, "数据告警": result.data_warnings},
                     ensure_ascii=False), file=sys.stderr)
    if args.strict and blocked:
        return 1
    return 0


def _cmd_parse(args: argparse.Namespace) -> int:
    loans, views, reports, _handovers, warnings = load_batch(args.data)
    materials = {loan.id: loan.body_material for loan in loans}
    parsed = parse_reports(reports, views, materials)
    payload = [
        {
            "report_id": item.report_id,
            "loan": item.loan_id,
            "phase": item.phase,
            "layer": item.layer,
            "family": item.family,
            "certainty": item.certainty,
            "temporal": item.temporal,
            "count": item.count,
            "location": item.location.__dict__,
            "view_refs": item.view_refs,
            "alternatives": item.alternatives,
            "review": item.review,
            "clause": item.clause,
            "span": list(item.span),
            "note": item.note,
        }
        for item in parsed.observations
    ]
    print(json.dumps({"observations": payload, "warnings": warnings + parsed.warnings},
                     ensure_ascii=False, indent=2))
    return 0


def _cmd_packet(args: argparse.Namespace) -> int:
    result = run_batch(args.data)
    text = render_packet(result)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


def _cmd_receipt(args: argparse.Namespace) -> int:
    result = run_batch(args.data)
    loans = [conclusion.loan for conclusion in result.conclusions]
    receipt = build_receipt(args.loan, loans, result.conclusions, result.case_decisions)
    if receipt is None:
        print(f"未找到借件 {args.loan}", file=sys.stderr)
        return 2
    text = render_receipt(receipt)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loancheck",
        description="借件归还前双语状况记录核对工具（按借件批次复用）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="整批核对，输出机器可读 JSON 与放行结论")
    check.add_argument("--data", default="data", help="含 index.json 的资料目录")
    check.add_argument("--output", help="JSON 结果输出路径，缺省打印到标准输出")
    check.add_argument("--strict", action="store_true",
                       help="存在阻断箱时以退出码 1 结束，便于脚本拦截")
    check.set_defaults(func=_cmd_check)

    parse_cmd = sub.add_parser("parse", help="只做文字解析，供登记员复核抽取质量")
    parse_cmd.add_argument("--data", default="data")
    parse_cmd.set_defaults(func=_cmd_parse)

    packet = sub.add_parser("packet", help="生成两馆签字用 Markdown 交接包")
    packet.add_argument("--data", default="data")
    packet.add_argument("--output", help="Markdown 输出路径")
    packet.set_defaults(func=_cmd_packet)

    receipt = sub.add_parser("receipt", help="按借件号生成回查收据")
    receipt.add_argument("loan", help="借件编号，如 L1")
    receipt.add_argument("--data", default="data")
    receipt.add_argument("--output", help="Markdown 输出路径")
    receipt.set_defaults(func=_cmd_receipt)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
