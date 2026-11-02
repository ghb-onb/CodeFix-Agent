"""报告生成：把一次修复流程压成人能直接读的几行。"""
from __future__ import annotations

from .models.fix import FixReport

SEVERITY_LABEL = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
}


class ReportGenerator:
    """终端友好的报告。刻意用纯文本对齐，不引入表格库依赖。"""

    WIDTH = 68

    def render(self, report: FixReport) -> str:
        lines: list[str] = []
        rule = "=" * self.WIDTH

        lines.append(rule)
        lines.append(f"  CodeFix Agent 报告 · {report.file or '<memory>'}")
        lines.append(rule)

        if not report.issues:
            lines.append("  未发现可识别的问题。")
            lines.append(rule)
            return "\n".join(lines)

        lines.append(f"  检测到 {len(report.issues)} 个问题")
        for issue in report.issues:
            label = SEVERITY_LABEL.get(issue.severity.value, issue.severity.value)
            lines.append(
                f"    [{label:<8}] {issue.rule_id}  L{issue.lineno:<3} {issue.message}"
            )
        lines.append("")

        lines.append(f"  修复建议 {len(report.suggestions)} 条")
        for suggestion in report.suggestions:
            lines.append(f"    L{suggestion.lineno:<3} {suggestion.summary}")
            lines.append(f"          {suggestion.original}")
            lines.append(f"       →  {suggestion.replacement}")
            lines.append(f"          置信度 {suggestion.confidence:.2f}")
        if not report.suggestions:
            lines.append("    无（当前规则集只对 CF001 提供确定性修复）")
        lines.append("")

        if report.before is not None:
            lines.append(
                f"  验证（修复前）: {report.before.brief():<10} "
                f"耗时 {report.before.duration_ms:.0f}ms"
            )
        if report.after is not None:
            lines.append(
                f"  验证（修复后）: {report.after.brief():<10} "
                f"耗时 {report.after.duration_ms:.0f}ms"
            )
        lines.append("")

        verdict = "测试全绿 ✓" if report.after and report.after.ok else "仍有测试失败 ✗"
        lines.append(f"  结论：已套用 {report.applied}/{len(report.issues)} 条修复，{verdict}")
        lines.append(f"  总耗时: {report.total_duration_ms / 1000:.2f}s")
        lines.append(rule)
        return "\n".join(lines)

    def to_dict(self, report: FixReport) -> dict:
        return {
            "file": report.file,
            "issues": [
                {
                    "rule_id": i.rule_id,
                    "category": i.category.value,
                    "severity": i.severity.value,
                    "lineno": i.lineno,
                    "message": i.message,
                    "snippet": i.snippet,
                }
                for i in report.issues
            ],
            "suggestions": [s.model_dump() for s in report.suggestions],
            "applied": report.applied,
            "before": report.before.model_dump() if report.before else None,
            "after": report.after.model_dump() if report.after else None,
            "total_duration_ms": report.total_duration_ms,
            "fixed_all": report.fixed_all,
        }
