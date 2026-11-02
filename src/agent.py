"""CodeFix Agent 编排层：检测 -> 出建议 -> 修复 -> 验证 -> 出报告。"""
from __future__ import annotations

import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional, Union

from .detector import BugDetector
from .fixer import CodeFixer
from .models.fix import FixReport
from .reporter import ReportGenerator
from .validator import FixValidator


class CodeFixAgent:
    """一条链跑完：发现问题、改掉它、用测试证明改对了。"""

    def __init__(
        self,
        detector: Optional[BugDetector] = None,
        fixer: Optional[CodeFixer] = None,
        validator: Optional[FixValidator] = None,
        reporter: Optional[ReportGenerator] = None,
    ):
        self.detector = detector or BugDetector()
        self.fixer = fixer or CodeFixer()
        self.validator = validator or FixValidator()
        self.reporter = reporter or ReportGenerator()

    def repair_file(
        self,
        module_path: Union[str, Path],
        test_files: Optional[Dict[str, str]] = None,
        module_name: Optional[str] = None,
    ) -> FixReport:
        path = Path(module_path)
        name = module_name or path.stem
        return self.repair_source(
            path.read_text(encoding="utf-8"),
            test_files=test_files or {},
            module_name=name,
            filename=str(path),
        )

    def repair_source(
        self,
        source: str,
        test_files: Optional[Dict[str, str]] = None,
        module_name: str = "target",
        filename: str = "",
    ) -> FixReport:
        tests = test_files or {}
        started = time.perf_counter()

        detection = self.detector.detect_source(source, filename)
        suggestions = self.fixer.suggest_all(detection.issues, source)
        fixed_source = self.fixer.apply(source, suggestions)
        applied = self.fixer.count_applied(source, suggestions)

        before = None
        after = None
        if tests:
            # 两个独立沙箱并行跑：before 用原始源码，after 用修复后源码。
            # 串行要 2×pytest 冷启动，并行只多花一个进程的边际成本。
            with ThreadPoolExecutor(max_workers=2) as pool:
                future_before = pool.submit(
                    self._validate_in_sandbox, source, tests, module_name, "before"
                )
                future_after = pool.submit(
                    self._validate_in_sandbox, fixed_source, tests, module_name, "after"
                )
                before = future_before.result()
                after = future_after.result()

        total_ms = round((time.perf_counter() - started) * 1000, 1)
        return FixReport(
            file=filename,
            detection=detection,
            suggestions=suggestions,
            applied=applied,
            before=before,
            after=after,
            total_duration_ms=total_ms,
            fixed_source=fixed_source,
        )

    def _validate_in_sandbox(
        self,
        source: str,
        tests: Dict[str, str],
        module_name: str,
        label: str,
    ):
        """在一次性临时目录里跑测试。目录用完即删，互不干扰。"""
        with tempfile.TemporaryDirectory(prefix=f"codefix_{label}_") as tmp:
            workdir = self.validator.prepare_workspace(tmp, module_name, source, tests)
            return self.validator.run_tests(workdir)

    def repair_and_report(self, *args, **kwargs) -> str:
        """便利方法：直接拿到可打印的报告文本。"""
        report = self.repair_file(*args, **kwargs)
        return self.reporter.render(report)
