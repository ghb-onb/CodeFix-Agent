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
DISCOUNT_PATTERN = re.compile(r"(discount|rebate|promo|off_rate|coupon)", re.IGNORECASE)


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
