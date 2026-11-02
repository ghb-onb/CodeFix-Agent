"""CodeFix Agent Demo：检测折扣 Bug -> 自动修复 -> 跑测试验证。

运行： python run_demo.py
"""

from __future__ import annotations

import difflib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.agent import CodeFixAgent  # noqa: E402

BASE = Path(__file__).resolve().parent
BUGGY_FILE = BASE / "demo_data" / "buggy_code.py"
TEST_FILE = BASE / "demo_data" / "test_order_pricing.py"


def print_banner() -> None:
    print("=" * 68)
    print("  CodeFix Agent Demo · 折扣计算 Bug 的检测与自动修复")
    print("=" * 68)
    print(f"  待修文件: {BUGGY_FILE.relative_to(BASE)}")
    print(f"  验收测试: {TEST_FILE.relative_to(BASE)}")
    print()


def print_diff(original: str, fixed: str) -> None:
    print("  代码变更:")
    diff = difflib.unified_diff(
        original.splitlines(),
        fixed.splitlines(),
        fromfile="修复前",
        tofile="修复后",
        lineterm="",
        n=1,
    )
    for line in diff:
        if line.startswith(("---", "+++")):
            continue
        print(f"    {line}")
    print()


def main() -> None:
    started = time.perf_counter()
    print_banner()

    original = BUGGY_FILE.read_text(encoding="utf-8")
    test_files = {TEST_FILE.name: TEST_FILE.read_text(encoding="utf-8")}

    agent = CodeFixAgent()
    report = agent.repair_file(BUGGY_FILE, test_files=test_files)

    print(agent.reporter.render(report))
    print()
    print_diff(original, report.fixed_source)

    print("  关键校验")
    print(f"    检测到 Bug 数        : {len(report.issues)}  {'✓' if len(report.issues) == 1 else '✗'}")
    print(f"    自动修复条数         : {report.applied}  {'✓' if report.applied == 1 else '✗'}")
    if report.before is not None:
        print(f"    修复前测试           : {report.before.brief()}  {'✓' if not report.before.ok else '✗'}")
    if report.after is not None:
        print(f"    修复后测试           : {report.after.brief()}  {'✓' if report.after.ok else '✗'}")
    elapsed = time.perf_counter() - started
    print(f"    端到端耗时           : {elapsed:.2f}s")
    print("=" * 68)

    assert report.after is not None and report.after.ok, "修复后测试未全部通过"
    assert report.applied == 1, "应当恰好修掉 1 处"
    print("\n  Demo complete!")


if __name__ == "__main__":
    main()
