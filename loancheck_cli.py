#!/usr/bin/env python3
"""命令行薄封装，便于 `python3 loancheck_cli.py check --data data` 直接调用。

也支持隔离模式：`python3 -I loancheck_cli.py ...`，避免资料目录中的
同名模块被解释器加载（隔离模式下脚本目录不在 sys.path，这里显式补入）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loancheck.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
