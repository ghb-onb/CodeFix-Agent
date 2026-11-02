"""Bug 检测：AST + 规则引擎，不调用任何模型。

设计取舍：**只报能给出确定修复方案的问题**。静态分析能报的东西很多，
但报了修不了的噪音会让人直接关掉工具，所以这里的规则集刻意保持很小，
每条规则都配一个 fixer 里的替换策略。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import List, Optional, Union

from .models.issue import BugCategory, CodeIssue, DetectionResult, Severity

# 折扣 / 优惠相关的变量名。命中即认为它可能是"率"而不是"系数"
DISCOUNT_PATTERN = re.compile(r"(discount|rebate|promo|coupon|off_rate)", re.IGNORECASE)
# 金额 / 比率相关的命名，用于浮点相等比较规则
MONEY_PATTERN = re.compile(
    r"(price|total|amount|revenue|cost|balance|discount|rate|tax)", re.IGNORECASE
)


class BugDetector:
    """基于 AST 的规则引擎。每条规则返回 0..N 个 CodeIssue。"""

    def detect_file(self, path: Union[str, Path]) -> DetectionResult:
        file_path = Path(path)
        source = file_path.read_text(encoding="utf-8")
        result = self.detect_source(source)
        result.file = str(file_path)
        return result

    def detect_source(self, source: str, filename: str = "") -> DetectionResult:
        tree = ast.parse(source, filename=filename or "<string>")
        issues: List[CodeIssue] = []
        issues.extend(self._rule_discount_multiplier(tree, source))
        issues.extend(self._rule_mutable_default(tree, source))
        issues.extend(self._rule_bare_except(tree, source))
        issues.extend(self._rule_float_equality(tree, source))
        issues.sort(key=lambda i: (i.lineno, i.col_offset))
        return DetectionResult(file=filename, issues=issues)

    # ------------------------------------------------------------- CF001

    def _rule_discount_multiplier(self, tree: ast.AST, source: str) -> List[CodeIssue]:
        """折扣率被当成折后系数直接相乘。

        `subtotal * discount_rate` 在 discount_rate=0.1 时得到的是"一成价"，
        正确写法是 `subtotal * (1 - discount_rate)`。
        正确写法的右操作数是 BinOp 而不是 Name，所以按"直接子节点是 Name"
        判断即可天然区分两种写法，不会误伤修好之后的代码。
        """
        issues: List[CodeIssue] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mult):
                continue
            bad = self._discount_operand(node)
            if bad is None:
                continue
            issues.append(
                CodeIssue(
                    rule_id="CF001",
                    category=BugCategory.DISCOUNT_CALC,
                    severity=Severity.CRITICAL,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    end_lineno=node.end_lineno or node.lineno,
                    end_col_offset=node.end_col_offset or node.col_offset,
                    snippet=ast.get_source_segment(source, node) or "",
                    message=f"折扣率 {bad} 被当作折后系数直接相乘",
                    explanation=(
                        f"`{ast.get_source_segment(source, node)}` 把折扣率本身当成了价格系数。"
                        f"当 {bad}=0.1（优惠 10%）时，结果只剩原价的一成，折扣越大力度的订单亏得越多。"
                    ),
                    hint=f"应改为 `金额 * (1 - {bad})`",
                )
            )
        return issues

    @staticmethod
    def _discount_operand(node: ast.BinOp) -> Optional[str]:
        for side in (node.left, node.right):
            if not isinstance(side, ast.Name):
                continue
            name = side.id
            if DISCOUNT_PATTERN.search(name):
                return name
        return None

    # ------------------------------------------------------------- CF002

    def _rule_mutable_default(self, tree: ast.AST, source: str) -> List[CodeIssue]:
        """可变默认参数：默认值在函数定义时只求值一次，会被跨调用共享。"""
        mutable = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
        issues: List[CodeIssue] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
                if isinstance(default, mutable):
                    issues.append(
                        CodeIssue(
                            rule_id="CF002",
                            category=BugCategory.MUTABLE_DEFAULT,
                            severity=Severity.HIGH,
                            lineno=default.lineno,
                            col_offset=default.col_offset,
                            end_lineno=default.end_lineno or default.lineno,
                            end_col_offset=default.end_col_offset or default.col_offset,
                            snippet=ast.get_source_segment(source, default) or "",
                            message=f"函数 {node.name} 使用可变对象作为默认参数",
                            explanation=(
                                "默认值在函数定义时求值一次，所有调用共享同一个对象。"
                                "函数内部一旦修改它，下一次调用的初始状态就被污染了。"
                            ),
                            hint="改为 None 作为默认值，在函数体内 `if x is None: x = []`",
                        )
                    )
        return issues

    # ------------------------------------------------------------- CF003

    def _rule_bare_except(self, tree: ast.AST, source: str) -> List[CodeIssue]:
        """裸 except：连 KeyboardInterrupt 和 SystemExit 一起吞掉。"""
        issues: List[CodeIssue] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append(
                    CodeIssue(
                        rule_id="CF003",
                        category=BugCategory.BARE_EXCEPT,
                        severity=Severity.MEDIUM,
                        lineno=node.lineno,
                        col_offset=node.col_offset,
                        end_lineno=node.end_lineno or node.lineno,
                        end_col_offset=node.end_col_offset or node.col_offset,
                        snippet="except:",
                        message="裸 except 会吞掉所有异常",
                        explanation=(
                            "裸 except 同时捕获 KeyboardInterrupt / SystemExit，"
                            "Ctrl+C 失效，真实错误被静默成一条空分支，线上排查会非常痛苦。"
                        ),
                        hint="改为 `except Exception as exc:` 并至少记录日志",
                    )
                )
        return issues

    # ------------------------------------------------------------- CF004

    def _rule_float_equality(self, tree: ast.AST, source: str) -> List[CodeIssue]:
        """金额 / 比率用 == 比较。0.1+0.2 != 0.3 的经典坑。"""
        issues: List[CodeIssue] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if not any(isinstance(op, ast.Eq) for op in node.ops):
                continue
            names = [n.id for n in ast.walk(node) if isinstance(n, ast.Name)]
            hit = next((n for n in names if MONEY_PATTERN.search(n)), None)
            if hit is None:
                continue
            issues.append(
                CodeIssue(
                    rule_id="CF004",
                    category=BugCategory.FLOAT_EQUALITY,
                    severity=Severity.MEDIUM,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    end_lineno=node.end_lineno or node.lineno,
                    end_col_offset=node.end_col_offset or node.col_offset,
                    snippet=ast.get_source_segment(source, node) or "",
                    message=f"浮点数 {hit} 使用 == 精确比较",
                    explanation=(
                        "二进制浮点无法精确表示 0.1 这类十进制小数，"
                        "`0.1 + 0.2 == 0.3` 为 False。金额比较应走 Decimal 或 round 后比对，"
                        "或使用 math.isclose。"
                    ),
                    hint="改用 math.isclose(a, b, rel_tol=1e-9) 或 Decimal 比较",
                )
            )
        return issues
