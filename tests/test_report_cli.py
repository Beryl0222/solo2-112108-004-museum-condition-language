"""报告渲染与 CLI 输出测试。"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loancheck.batch import run_batch  # noqa: E402
from loancheck.cases import build_receipt  # noqa: E402
from loancheck.cli import main  # noqa: E402
from loancheck.report import render_packet, render_receipt  # noqa: E402

DATA = str(Path(__file__).resolve().parents[1] / "data")


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_batch(DATA)

    def test_packet_lists_all_evidence_and_open_positions(self):
        text = render_packet(self.result)
        self.assertIn("仍有分歧/未决位置", text)
        # 每条结论都带报告登记号原文证据
        self.assertIn("[O3/out/zh]", text)
        self.assertIn("L2-F4", text)
        # 缺参照不得硬配的提示进入交接包
        self.assertIn("最少还需核对", text)

    def test_receipt_contains_distinction_basis(self):
        loans = [conclusion.loan for conclusion in self.result.conclusions]
        receipt = build_receipt("L1", loans, self.result.conclusions,
                                self.result.case_decisions)
        text = render_receipt(receipt)
        self.assertIn("旧痕与新增变化的区分依据", text)
        self.assertIn("组合指纹", text)
        self.assertIn("L1-F1", text)

    def test_cli_check_strict_exit_code(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["check", "--data", DATA, "--strict"])
        self.assertEqual(code, 1)  # 合成批次含阻断箱

    def test_cli_packet_to_stdout(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["packet", "--data", DATA])
        self.assertEqual(code, 0)
        self.assertIn("交接包", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
