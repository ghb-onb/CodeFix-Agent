"""Fix models: 修复建议、验证结果、最终报告。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .issue import CodeIssue, DetectionResult


class FixSuggestion(BaseModel):
    """一条针对具体 issue 的替换式修复。"""

    rule_id: str
    lineno: int
    original: str
    replacement: str
    summary: str = ""
    rationale: str = ""
    confidence: float = 0.0  # 0~1，低于 0.6 的实现不建议自动套用


class ValidationResult(BaseModel):
    """一次 pytest 运行的结果。"""

    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    returncode: int = 0
    duration_ms: float = 0.0
    output_tail: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.failed == 0 and self.errors == 0

    def brief(self) -> str:
        return f"{self.passed}/{self.total} 通过"


class FixReport(BaseModel):
    """一次完整修复流程的产物。"""

    file: str = ""
    detection: DetectionResult = Field(default_factory=DetectionResult)
    suggestions: List[FixSuggestion] = Field(default_factory=list)
    applied: int = 0
    before: Optional[ValidationResult] = None
    after: Optional[ValidationResult] = None
    total_duration_ms: float = 0.0
    fixed_source: str = ""

    @property
    def fixed_all(self) -> bool:
        """检测到的问题是否全部被修掉，且测试全绿。"""
        if self.after is None:
            return False
        residual = len(self.detection.issues) - self.applied
        return residual == 0 and self.after.ok

    @property
    def issues(self) -> List[CodeIssue]:
        return self.detection.issues
