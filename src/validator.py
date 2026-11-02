"""修复验证：把候选代码放进隔离目录，真跑一遍 pytest。

为什么用子进程而不是 `pytest.main()`：同进程跑测试会污染当前解释器的
模块缓存（修好的 `buggy_code` 可能命中旧的 sys.modules），而"修完还是失败"
这种假阴性会直接毁掉整套工具的可信度。子进程是干净的。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Union

from .models.fix import ValidationResult

_COUNT_PATTERNS = {
    "passed": re.compile(r"(\d+) passed"),
    "failed": re.compile(r"(\d+) failed"),
    "errors": re.compile(r"(\d+) error"),
}


class FixValidator:
    """在指定目录里跑 pytest，把结果收敛成 ValidationResult。"""

    def __init__(self, timeout: int = 120, disable_plugin_autoload: bool = True):
        self.timeout = timeout
        # 关掉第三方插件自动加载：内置 fixture（tmp_path 等）不受影响，
        # 但能省掉每次启动 ~0.6s 的插件扫描——修复验证是高频操作，这个开销很值钱。
        self.disable_plugin_autoload = disable_plugin_autoload

    def prepare_workspace(
        self,
        directory: Union[str, Path],
        module_name: str,
        module_source: str,
        test_files: Dict[str, str],
    ) -> Path:
        """把待测模块和测试文件落到同一个目录，返回该目录。"""
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{module_name}.py").write_text(module_source, encoding="utf-8")
        for filename, content in test_files.items():
            (root / filename).write_text(content, encoding="utf-8")
        return root

    def run_tests(self, workdir: Union[str, Path], target: str = ".") -> ValidationResult:
        """在 workdir 下执行 pytest，返回解析后的结果。"""
        root = Path(workdir).resolve()
        env = os.environ.copy()
        # 让测试文件能直接 import 同目录模块，不依赖安装
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(root) + (os.pathsep + existing if existing else "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if self.disable_plugin_autoload:
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

        command = [
            sys.executable, "-m", "pytest", target,
            "-q", "--no-header", "-p", "no:cacheprovider",
        ]

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
            )
            returncode = completed.returncode
            output = (completed.stdout or "") + (completed.stderr or "")
        except subprocess.TimeoutExpired:
            returncode = -1
            output = f"pytest 超时（>{self.timeout}s）"

        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        return self._parse(output, returncode, duration_ms)

    @staticmethod
    def _parse(output: str, returncode: int, duration_ms: float) -> ValidationResult:
        counts = {}
        for key, pattern in _COUNT_PATTERNS.items():
            match = pattern.search(output)
            counts[key] = int(match.group(1)) if match else 0

        tail = "\n".join(line for line in output.strip().splitlines()[-12:] if line.strip())
        return ValidationResult(
            total=counts["passed"] + counts["failed"] + counts["errors"],
            passed=counts["passed"],
            failed=counts["failed"],
            errors=counts["errors"],
            returncode=returncode,
            duration_ms=duration_ms,
            output_tail=tail,
        )
