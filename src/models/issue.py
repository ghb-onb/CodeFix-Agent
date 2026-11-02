"""Issue models: 一条检测结果长什么样。"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """严重程度。决定报告排序，也决定是否值得自动修。"""

    CRITICAL = "critical"  # 算错了钱、写穿了数据
    HIGH = "high"          # 特定输入下必然出错
    MEDIUM = "medium"      # 有条件触发
    LOW = "low"            # 风格 / 可维护性


class BugCategory(str, Enum):
    """Bug 类别。和规则一一对应，方便统计与扩展。"""

    DISCOUNT_CALC = "discount_calc"      # 折扣 / 百分比算反
    MUTABLE_DEFAULT = "mutable_default"  # 可变默认参数
    BARE_EXCEPT = "bare_except"          # 裸 except 吞异常
    FLOAT_EQUALITY = "float_equality"    # 浮点数用 == 比较


class CodeIssue(BaseModel):
    """一条被规则命中的代码问题。"""

    rule_id: str
    category: BugCategory
    severity: Severity
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int
    snippet: str = ""
    message: str = ""
    explanation: str = ""
    hint: str = ""

    @property
    def location(self) -> str:
        return f"L{self.lineno}:{self.col_offset}"

    def brief(self) -> str:
        return f"[{self.rule_id}] L{self.lineno} {self.severity.value}: {self.message}"


class DetectionResult(BaseModel):
    """一次检测的汇总。"""

    file: str = ""
    issues: list[CodeIssue] = Field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.issues)

    def by_severity(self) -> dict[str, int]:
        stats: dict[str, int] = {s.value: 0 for s in Severity}
        for issue in self.issues:
            stats[issue.severity.value] += 1
        return stats

    def critical(self) -> Optional[CodeIssue]:
        for issue in self.issues:
            if issue.severity is Severity.CRITICAL:
                return issue
        return self.issues[0] if self.issues else None
