"""CodeFix Agent 测试套件：11 个用例覆盖检测 / 修复 / 验证 / 报告 / 集成。

分层：Detector 5、Fixer 2、Validator 2、Reporter 1、Integration 1。
重点在边界而不是 happy path —— 静态分析工具最大的风险是误报，
所以"不该报的代码没被报"和"该报的报出来了"同样重要。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from src.agent import CodeFixAgent  # noqa: E402
from src.detector import BugDetector  # noqa: E402
from src.fixer import CodeFixer  # noqa: E402
from src.models.issue import BugCategory, Severity  # noqa: E402
from src.reporter import ReportGenerator  # noqa: E402
from src.validator import FixValidator  # noqa: E402

DEMO_DIR = BASE / "demo_data"
BUGGY_PATH = DEMO_DIR / "buggy_code.py"
TEST_PATH = DEMO_DIR / "test_order_pricing.py"
BUGGY_SOURCE = BUGGY_PATH.read_text(encoding="utf-8")
TEST_FILES = {TEST_PATH.name: TEST_PATH.read_text(encoding="utf-8")}


# ===== Detector (5) =====
class TestDetector:
    def test_detects_discount_multiplication(self):
        report = BugDetector().detect_source(BUGGY_SOURCE, str(BUGGY_PATH))
        assert len(report.issues) == 1
        issue = report.issues[0]
        assert issue.rule_id == "CF001"
        # 报的行号必须真的落在出问题的那一行上
        assert "subtotal * discount_rate" in BUGGY_SOURCE.splitlines()[issue.lineno - 1]

    def test_ignores_precomputed_multiplier(self):
        source = "def f(price, discount_factor):\n    return price * discount_factor\n"
        assert BugDetector().detect_source(source).issues == []

    def test_ignores_derived_discount_value(self):
        """discounted 已经是算完的结果，拿去做乘法不是 Bug，不能报。"""
        source = (
            "def f(discounted, tax):\n"
            "    return round(discounted * (1 + tax), 2)\n"
        )
        assert BugDetector().detect_source(source).issues == []

    def test_detects_mutable_default_argument(self):
        source = "def collect(item, bucket=[]):\n    bucket.append(item)\n    return bucket\n"
        issues = BugDetector().detect_source(source).issues
        assert [i.rule_id for i in issues] == ["CF002"]
        assert issues[0].category is BugCategory.MUTABLE_DEFAULT

    def test_detects_bare_except_and_float_equality(self):
        source = (
            "def pay(total, expected):\n"
            "    try:\n"
            "        return total == expected\n"
            "    except:\n"
            "        return False\n"
        )
        rules = {i.rule_id for i in BugDetector().detect_source(source).issues}
        assert rules == {"CF003", "CF004"}


# ===== Fixer (2) =====
class TestFixer:
    def test_suggests_parenthesized_fix(self):
        detector, fixer = BugDetector(), CodeFixer()
        issue = detector.detect_source(BUGGY_SOURCE).issues[0]
        suggestion = fixer.suggest(issue, BUGGY_SOURCE)

        assert suggestion is not None
        assert suggestion.original == "subtotal * discount_rate"
        assert suggestion.replacement == "subtotal * (1 - discount_rate)"
        assert suggestion.confidence >= 0.9

    def test_apply_fixes_and_source_still_parses(self):
        fixer = CodeFixer()
        issues = BugDetector().detect_source(BUGGY_SOURCE).issues
        fixed = fixer.apply(BUGGY_SOURCE, fixer.suggest_all(issues, BUGGY_SOURCE))

        assert "total = subtotal * (1 - discount_rate)" in fixed
        assert "subtotal * discount_rate\n" not in fixed
        ast.parse(fixed)  # 修完必须还是合法 Python，否则宁可不改
        assert fixer.count_applied(BUGGY_SOURCE, fixer.suggest_all(issues, BUGGY_SOURCE)) == 1


# ===== Validator (2) =====
@pytest.fixture(scope="module")
def validation_pair(tmp_path_factory):
    """同一份源码只跑两次 pytest：before 一份、after 一份，供两个用例共用。"""
    validator = FixValidator()
    fixer = CodeFixer()
    issues = BugDetector().detect_source(BUGGY_SOURCE).issues
    fixed = fixer.apply(BUGGY_SOURCE, fixer.suggest_all(issues, BUGGY_SOURCE))

    root = tmp_path_factory.mktemp("validation")
    before_dir = validator.prepare_workspace(root / "before", "buggy_code", BUGGY_SOURCE, TEST_FILES)
    after_dir = validator.prepare_workspace(root / "after", "buggy_code", fixed, TEST_FILES)
    return validator.run_tests(before_dir), validator.run_tests(after_dir)


class TestValidator:
    def test_buggy_source_fails_all_tests(self, validation_pair):
        before, _ = validation_pair
        assert before.total == 4
        assert before.failed == 4
        assert not before.ok

    def test_fixed_source_passes_all_tests(self, validation_pair):
        _, after = validation_pair
        assert after.total == 4
        assert after.passed == 4
        assert after.ok


# ===== Reporter (1) =====
class TestReporter:
    def test_report_render_contains_key_facts(self):
        report = CodeFixAgent().repair_source(
            BUGGY_SOURCE, test_files=TEST_FILES, module_name="buggy_code"
        )
        text = ReportGenerator().render(report)

        assert "CF001" in text
        assert "4/4 通过" in text
        assert "测试全绿" in text
        assert "已套用 1/1" in text


# ===== Integration (1) =====
class TestIntegration:
    def test_end_to_end_repair(self):
        report = CodeFixAgent().repair_source(
            BUGGY_SOURCE,
            test_files=TEST_FILES,
            module_name="buggy_code",
            filename=str(BUGGY_PATH),
        )

        assert len(report.issues) == 1
        assert report.issues[0].severity is Severity.CRITICAL
        assert report.applied == 1
        assert report.before is not None and not report.before.ok
        assert report.after is not None and report.after.ok
        assert report.fixed_all
        assert "subtotal * (1 - discount_rate)" in report.fixed_source
