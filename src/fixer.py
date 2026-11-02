"""修复建议生成：只对「能确定怎么改」的规则给出可套用的替换。

CF001（折扣乘反）是唯一支持自动修复的规则——它的正确写法是唯一的，
而 CF002/CF003/CF004 的改法取决于上下文（用什么默认值、记什么日志、
用 Decimal 还是 isclose），硬套模板只会制造新的错误，所以这几类只给建议文本。
"""
from __future__ import annotations

import ast
from typing import List, Optional, Tuple

from .detector import BugDetector
from .models.fix import FixSuggestion
from .models.issue import CodeIssue


class UnfixableIssueError(ValueError):
    """该规则没有确定性的自动修复方案。"""


class CodeFixer:
    """把 CodeIssue 变成可套用的文本替换。"""

    # 规则 -> (置信度, 是否支持自动套用)
    SUPPORTED = {
        "CF001": (0.95, True),
    }

    def supports_auto_fix(self, issue: CodeIssue) -> bool:
        return self.SUPPORTED.get(issue.rule_id, (0.0, False))[1]

    def suggest(self, issue: CodeIssue, source: str) -> Optional[FixSuggestion]:
        """生成修复建议。不支持的规则返回 None。"""
        confidence, auto = self.SUPPORTED.get(issue.rule_id, (0.0, False))
        if not auto:
            return None

        if issue.rule_id == "CF001":
            return self._suggest_discount(issue, source, confidence)
        return None

    def suggest_all(self, issues: List[CodeIssue], source: str) -> List[FixSuggestion]:
        out: List[FixSuggestion] = []
        for issue in issues:
            suggestion = self.suggest(issue, source)
            if suggestion is not None:
                out.append(suggestion)
        return out

    # ------------------------------------------------------------- CF001

    def _suggest_discount(
        self, issue: CodeIssue, source: str, confidence: float
    ) -> Optional[FixSuggestion]:
        node = self._locate_binop(source, issue.lineno, issue.col_offset)
        if node is None:
            return None

        # 折扣操作数的判定与检测规则共用同一套逻辑，避免两处漂移
        discount_name = BugDetector._discount_operand(node)
        if discount_name is None:
            return None

        discount = None
        discount_is_left = False
        for side, is_left in ((node.left, True), (node.right, False)):
            if isinstance(side, ast.Name) and side.id == discount_name:
                discount, discount_is_left = side, is_left
                break
        if discount is None:
            return None
        other = node.right if discount_is_left else node.left

        other_src = ast.get_source_segment(source, other) or ast.unparse(other)
        # 另一侧如果是表达式（如 1 + TAX_RATE），加括号保证运算优先级不被改掉
        if isinstance(other, (ast.BinOp, ast.BoolOp, ast.Compare, ast.IfExp)):
            other_src = f"({other_src})"
        original = ast.get_source_segment(source, node) or ""

        if discount_is_left:
            replacement = f"(1 - {discount.id}) * {other_src}"
        else:
            replacement = f"{other_src} * (1 - {discount.id})"

        return FixSuggestion(
            rule_id=issue.rule_id,
            lineno=issue.lineno,
            original=original,
            replacement=replacement,
            summary=f"把折扣率改为折后系数：{discount.id} → (1 - {discount.id})",
            rationale=(
                "折扣率表示「优惠掉的比例」，价格系数应为 1 - 折扣率。"
                f"原写法在 {discount.id}=0 时会得到 0 元（本该是原价），"
                f"在 {discount.id}=0.9 时得到九成价（本该是一成价）。"
            ),
            confidence=confidence,
        )

    @staticmethod
    def _locate_binop(source: str, lineno: int, col_offset: int) -> Optional[ast.BinOp]:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Mult)
                and node.lineno == lineno
                and node.col_offset == col_offset
            ):
                return node
        return None

    # --------------------------------------------------------------- apply

    @staticmethod
    def count_applied(source: str, suggestions: List[FixSuggestion]) -> int:
        """统计真正落到源码上的替换条数（原文没找到的不算）。"""
        lines = source.splitlines()
        applied = 0
        for suggestion in suggestions:
            index = suggestion.lineno - 1
            if not 0 <= index < len(lines):
                continue
            if suggestion.original and suggestion.original in lines[index]:
                applied += 1
        return applied

    def apply(self, source: str, suggestions: List[FixSuggestion]) -> str:
        """按行套用替换。同一行多条时从后往前改，避免列偏移失效。"""
        if not suggestions:
            return source

        lines = source.splitlines(keepends=True)
        # 先按行号倒序、再按出现位置倒序，保证前面的替换不影响后面的定位
        ordered = sorted(suggestions, key=lambda s: (s.lineno, s.original), reverse=True)

        for suggestion in ordered:
            index = suggestion.lineno - 1
            if not 0 <= index < len(lines):
                continue
            line = lines[index]
            if suggestion.original and suggestion.original in line:
                lines[index] = line.replace(
                    suggestion.original, suggestion.replacement, 1
                )

        fixed = "".join(lines)
        ast.parse(fixed)  # 修完还要语法正确，否则宁可不改
        return fixed

    # ------------------------------------------------------------ pipeline

    def fix_source(
        self, issues: List[CodeIssue], source: str
    ) -> Tuple[str, List[FixSuggestion]]:
        """一步到位：出建议 + 套用。返回 (修复后源码, 已套用建议)。"""
        suggestions = self.suggest_all(issues, source)
        return self.apply(source, suggestions), suggestions
