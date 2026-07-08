#!/usr/bin/env python3
"""
run_validation.py — 运行 pytest + pyright 验证环境配置是否成功。

用法：
    python run_validation.py <repo_path>

依次执行：
1. pytest --collect-only -q（检查测试收集）
2. pyright --outputjson（扫描 missing-imports）
3. pytest（正式运行测试）
缺模块时自动尝试 pip install。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple


BATCH_SIZE = 50


def run_cmd(cmd: str, cwd: Path, timeout: int = 300) -> Tuple[int, str]:
    """运行一条命令，返回 (exit_code, output_text)。"""
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode, output.strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -1, str(e)


def extract_missing_modules(output: str) -> List[str]:
    """从 pytest/pyright 输出中提取缺失的模块名。"""
    modules = set()

    # pytest missing module pattern
    for m in re.finditer(r"ModuleNotFoundError.*?: No module named ['\"]([^'\"]+)['\"]", output):
        modules.add(m.group(1))
    for m in re.finditer(r"ImportError.*?: No module named ['\"]([^'\"]+)['\"]", output):
        modules.add(m.group(1))
    for m in re.finditer(r"ModuleNotFoundError.*?:.*?No module named ['\"]([^'\"]+)['\"]", output):
        modules.add(m.group(1))

    # pyright missing import pattern
    for m in re.finditer(r"Import\s+\"([^\"]+)\"\s+could not be resolved", output):
        modules.add(m.group(1).split(".")[0])

    return list(modules)


def try_install_missing(modules: List[str], cwd: Path) -> str:
    """尝试安装缺失的模块，记录成功/失败。"""
    if not modules:
        return ""

    log = []
    # 分批发装
    remaining = list(modules)
    while remaining:
        batch = remaining[:BATCH_SIZE]
        remaining = remaining[BATCH_SIZE:]
        specs = " ".join(batch)
        exit_code, out = run_cmd(f"uv pip install --system {specs}", cwd, timeout=120)
        if exit_code == 0:
            log.append(f"  [ok] installed: {', '.join(batch)}")
        else:
            # 单个尝试
            for mod in batch:
                ec, _ = run_cmd(f"uv pip install --system {mod}", cwd, timeout=120)
                if ec == 0:
                    log.append(f"  [ok] installed: {mod}")
                else:
                    log.append(f"  [fail] {mod}")

    return "\n".join(log)


def run_pytest_collect(cwd: Path) -> Tuple[int, str, List[str]]:
    """运行 pytest 收集，返回 (exit_code, output, missing_modules)。"""
    exit_code, output = run_cmd(
        "python -m pytest --collect-only -q 2>&1", cwd, timeout=120
    )
    missing = extract_missing_modules(output)
    return exit_code, output, missing


def run_pyright(cwd: Path) -> Tuple[int, str, List[str]]:
    """运行 pyright，返回 (exit_code, output, missing_modules)。"""
    exit_code, output = run_cmd("pyright --outputjson 2>&1", cwd, timeout=120)
    missing = extract_missing_modules(output)
    return exit_code, output, missing


def run_pytest(cwd: Path) -> Tuple[int, str]:
    """运行 pytest。"""
    return run_cmd("python -m pytest -q --tb=short 2>&1", cwd, timeout=600)


def count_tests(output: str) -> Tuple[int, int, int]:
    """统计测试结果：passed, failed, errors。"""
    passed = failed = errors = 0
    for line in output.splitlines():
        m = re.search(r"(\d+) passed", line)
        if m:
            passed += int(m.group(1))
        m = re.search(r"(\d+) failed", line)
        if m:
            failed += int(m.group(1))
        m = re.search(r"(\d+) error", line)
        if m:
            errors += int(m.group(1))
    return passed, failed, errors


def main():
    parser = argparse.ArgumentParser(description="运行 pytest + pyright 验证")
    parser.add_argument("repo_path", help="目标仓库路径")
    args = parser.parse_args()

    cwd = Path(args.repo_path).resolve()
    if not cwd.exists():
        print(f"错误：路径不存在 {cwd}", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("STEP 1: pytest 收集")
    print("=" * 60)
    collect_exit, collect_out, missing = run_pytest_collect(cwd)
    print(f"exit code: {collect_exit}")

    if missing:
        print(f"\n发现 {len(missing)} 个缺失模块，尝试自动安装...")
        install_log = try_install_missing(missing, cwd)
        print(install_log)
        # 装完后重试收集
        collect_exit, collect_out, missing = run_pytest_collect(cwd)
        print(f"\n重试后 exit code: {collect_exit}")
        if missing:
            print(f"仍缺失: {', '.join(missing)}")

    print("\n" + "=" * 60)
    print("STEP 2: pyright 检查")
    print("=" * 60)
    pyright_exit, pyright_out, pyright_missing = run_pyright(cwd)
    try:
        data = json.loads(pyright_out) if pyright_out else {}
        diag_count = len(data.get("generalDiagnostics", [])) if isinstance(data, dict) else 0
        print(f"pyright diagnostics: {diag_count}")
    except json.JSONDecodeError:
        print(f"pyright exit: {pyright_exit}")

    print("\n" + "=" * 60)
    print("STEP 3: pytest 运行")
    print("=" * 60)
    if collect_exit not in (0, 5):
        print("pytest 收集失败，跳过正式运行。")
        print("请先修复收集错误。")
        sys.exit(1)

    if collect_exit == 5:
        print("没有测试可收集 (exit 5)，跳过。")
        sys.exit(0)

    test_exit, test_out = run_pytest(cwd)
    passed, failed, errors = count_tests(test_out)
    print(f"pytest exit: {test_exit}")
    print(f"passed: {passed}, failed: {failed}, errors: {errors}")

    # 最终判定
    print("\n" + "=" * 60)
    if test_exit == 0:
        print("结果: ✅ 测试全部通过")
    elif collect_exit == 5:
        print("结果: ⚠️ 没有测试可收集")
    else:
        print(f"结果: ❌ 测试未通过 (exit {test_exit})")
        if failed:
            print(f"  失败: {failed} 个测试")
        if errors:
            print(f"  错误: {errors} 个")
        print("\n提示：")
        print("- 检查缺失的依赖是否安装正确")
        print("- 检查 Python 版本是否兼容")
        print("- 检查是否需要系统包 (apt-get install)")
        print("- 检查是否有配置示例文件需要参考")


if __name__ == "__main__":
    main()
