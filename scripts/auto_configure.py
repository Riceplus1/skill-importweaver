#!/usr/bin/env python3
"""
auto_configure.py — 自动扫描并安装 Python 项目依赖。

用法：
    python auto_configure.py <repo_path>

执行流程：
1. 扫描依赖文件
2. 确定 Python 版本
3. 安装 requirements.txt
4. 安装项目 (uv pip install --system -e .)
5. 处理 lock 文件 (uv.lock / poetry.lock / pdm.lock / Pipfile)
6. 处理 extras / dependency groups
每步后执行快速 pytest 检查，通过了提前结束。
"""

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import List, Optional, Set, Tuple


_EXCLUDED_DIR_PARTS: Set[str] = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".idea", ".vscode",
    "output", ".ruff_cache", ".tox", "node_modules",
}


def run_cmd(cmd: str, cwd: Optional[Path] = None, timeout: int = 300) -> Tuple[int, str]:
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


def log(msg: str):
    print(f"  {msg}")


def step(title: str):
    print(f"\n{'=' * 60}")
    print(f"STEP: {title}")
    print(f"{'=' * 60}")


def scan_dependency_files(repo_path: Path) -> dict:
    """扫描项目中的依赖文件。"""
    found = {
        "pyproject": None,
        "setup_py": None,
        "setup_cfg": None,
        "requirements": [],
        "uv_lock": None,
        "poetry_lock": None,
        "pdm_lock": None,
        "pipfile": None,
        "makefile": None,
        "tox_ini": None,
        "extras": [],
        "dep_groups": [],
    }

    # 根目录直接查找
    for name in ["pyproject.toml", "setup.py", "setup.cfg",
                  "requirements.txt", "Makefile", "tox.ini"]:
        path = repo_path / name
        if path.exists():
            if name == "pyproject.toml":
                found["pyproject"] = path
            elif name == "setup.py":
                found["setup_py"] = path
            elif name == "setup.cfg":
                found["setup_cfg"] = path
            elif name == "requirements.txt":
                found["requirements"].append(path)
            elif name == "Makefile":
                found["makefile"] = path
            elif name == "tox.ini":
                found["tox_ini"] = path

    # requirements*.txt
    for path in sorted(repo_path.glob("requirements*.txt")):
        if path not in found["requirements"]:
            found["requirements"].append(path)
    req_dir = repo_path / "requirements"
    if req_dir.is_dir():
        for path in sorted(req_dir.glob("*.txt")):
            if path not in found["requirements"]:
                found["requirements"].append(path)

    # lock 文件（递归）
    for pattern, key in [("uv.lock", "uv_lock"), ("poetry.lock", "poetry_lock"),
                          ("pdm.lock", "pdm_lock"), ("Pipfile", "pipfile")]:
        for path in sorted(repo_path.rglob(pattern)):
            if any(part in _EXCLUDED_DIR_PARTS for part in path.parts):
                continue
            found[key] = path
            break  # 只取最顶层的一个

    # 解析 pyproject.toml 的 extras 和 dep groups
    if found["pyproject"]:
        try:
            data = tomllib.loads(found["pyproject"].read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                project = data.get("project") if isinstance(data.get("project"), dict) else None
                if project:
                    opt = project.get("optional-dependencies") if isinstance(project.get("optional-dependencies"), dict) else {}
                    if opt:
                        found["extras"] = list(opt.keys())
                dep_groups = data.get("dependency-groups") if isinstance(data.get("dependency-groups"), dict) else {}
                if dep_groups:
                    found["dep_groups"] = list(dep_groups.keys())
        except Exception:
            pass

    return found


def check_python_version(repo_path: Path) -> Optional[str]:
    """检查项目要求的 Python 版本，返回目标版本或 None。"""
    # 从 pyproject.toml 读取 requires-python
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                project = data.get("project") if isinstance(data.get("project"), dict) else None
                if project:
                    spec = project.get("requires-python")
                    if spec:
                        return extract_target_version(str(spec))
        except Exception:
            pass

    # runtime.txt / .python-version
    for name in ["runtime.txt", ".python-version"]:
        path = repo_path / name
        if path.exists():
            ver = path.read_text(encoding="utf-8").strip()
            m = re.search(r"(\d+\.\d+(?:\.\d+)?)", ver)
            if m:
                return m.group(1)

    return None


def extract_target_version(spec: str) -> Optional[str]:
    """从 requires-python spec (如 >=3.8, <4.0) 提取一个目标版本。"""
    nums = re.findall(r"(\d+)\.(\d+)", spec)
    if nums:
        versions = sorted((int(m[0]), int(m[1])) for m in nums)
        return f"{versions[-1][0]}.{versions[-1][1]}"
    return None


def run_pytest_check(cwd: Path) -> bool:
    """快速 pytest 检查，返回是否通过。"""
    exit_code, _ = run_cmd("python -m pytest -q --collect-only --maxfail=1 2>&1", cwd, timeout=60)
    return exit_code in (0, 5)


def main():
    parser = argparse.ArgumentParser(description="自动扫描并安装 Python 项目依赖")
    parser.add_argument("repo_path", help="目标仓库路径")
    args = parser.parse_args()

    cwd = Path(args.repo_path).resolve()
    if not cwd.exists():
        print(f"错误：路径不存在 {cwd}", file=sys.stderr)
        sys.exit(1)

    print(f"目标仓库: {cwd}")
    print(f"工作目录: {os.getcwd()}")

    # --- STEP 1: 扫描 ---
    step("1/6 扫描依赖文件")
    deps = scan_dependency_files(cwd)
    print(f"  pyproject.toml:     {'✓' if deps['pyproject'] else '—'}")
    print(f"  setup.py:           {'✓' if deps['setup_py'] else '—'}")
    print(f"  requirements.txt:   {len(deps['requirements'])} 文件")
    print(f"  uv.lock:            {'✓' if deps['uv_lock'] else '—'}")
    print(f"  poetry.lock:        {'✓' if deps['poetry_lock'] else '—'}")
    print(f"  pdm.lock:           {'✓' if deps['pdm_lock'] else '—'}")
    print(f"  Pipfile:            {'✓' if deps['pipfile'] else '—'}")
    print(f"  Makefile:           {'✓' if deps['makefile'] else '—'}")
    if deps["extras"]:
        print(f"  extras:             {', '.join(deps['extras'])}")

    # --- STEP 2: Python 版本 ---
    step("2/6 检查 Python 版本")
    current = run_cmd("python3 --version 2>&1", timeout=10)
    print(f"  当前: {current[1]}")

    target_ver = check_python_version(cwd)
    if target_ver:
        print(f"  项目要求: ~={target_ver}")
        cv = current[1].split()[-1] if current[1] else ""
        if cv and not cv.startswith(target_ver[:3]):
            print(f"  ⚠️ 注意: 当前 Python {cv} 可能与要求版本 {target_ver} 不兼容")
            print(f"  如需切换，请联系管理员更换 Docker 镜像")
    else:
        print(f"  未检测到 Python 版本要求")

    # --- STEP 3: 安装 requirements.txt ---
    if deps["requirements"]:
        step("3/6 安装 requirements")
        for req in deps["requirements"]:
            rel = req.relative_to(cwd)
            print(f"  安装 {rel}...")
            exit_code, output = run_cmd(f"uv pip install --system -r {shlex_quote(str(rel))}", cwd, timeout=300)
            if exit_code == 0:
                log(f"✓ {rel} 安装成功")
            else:
                log(f"⚠ {rel} 部分失败 (exit {exit_code})")
                tail = "\n".join(output.splitlines()[-5:])
                log(f"  最后输出: {tail}")

        if run_pytest_check(cwd):
            print(f"\n✓ pytest 通过！环境已可用。")
            return

    # --- STEP 4: 安装项目 ---
    has_project = deps["pyproject"] or deps["setup_py"] or deps["setup_cfg"]
    if has_project:
        step("4/6 安装项目 (editable)")
        exit_code, output = run_cmd("uv pip install --system -e .", cwd, timeout=300)
        if exit_code == 0:
            log("✓ 项目安装成功")
        else:
            log(f"⚠ 项目安装失败 (exit {exit_code})，尝试不隔离构建...")
            exit_code, output = run_cmd("uv pip install --system -e . --no-build-isolation", cwd, timeout=300)
            if exit_code == 0:
                log("✓ 项目安装成功 (--no-build-isolation)")
            else:
                log(f"✗ 项目安装失败，请手动检查")

        if run_pytest_check(cwd):
            print(f"\n✓ pytest 通过！环境已可用。")
            return

    # --- STEP 5: Lock 文件 ---
    lock_handlers = {
        "uv_lock": ("uv.lock", "cd {dir} && uv export --frozen -o - | uv pip install -r -"),
        "poetry_lock": ("poetry.lock", "cd {dir} && poetry export --all-extras | uv pip install --system -r -"),
        "pdm_lock": ("pdm.lock", "cd {dir} && pdm export --all-extras -f requirements | uv pip install --system -r -"),
        "pipfile": ("Pipfile", "cd {dir} && pipenv requirements | uv pip install --system -r -"),
    }

    for key, (name, cmd_template) in lock_handlers.items():
        path = deps[key]
        if path:
            step(f"5/6 处理 {name}")
            lock_dir = path.parent.relative_to(cwd) if path.parent != cwd else Path(".")
            cmd = cmd_template.format(dir=shlex_quote(str(lock_dir)) if lock_dir != Path(".") else ".")
            exit_code, output = run_cmd(cmd, cwd, timeout=300)
            if exit_code == 0:
                log(f"✓ {name} 安装成功")
            else:
                log(f"⚠ {name} 安装失败 (exit {exit_code})")

            if run_pytest_check(cwd):
                print(f"\n✓ pytest 通过！环境已可用。")
                return

    # --- STEP 6: Extras ---
    if deps["extras"]:
        step("6/6 安装 extras")
        for ext in deps["extras"]:
            log(f"  安装 .[{ext}]...")
            exit_code, output = run_cmd(f"uv pip install --system -e .[{ext}]", cwd, timeout=300)
            if exit_code == 0:
                log(f"  ✓ .[{ext}] 安装成功")
            else:
                log(f"  ⚠ .[{ext}] 安装失败 (exit {exit_code})")

            if run_pytest_check(cwd):
                print(f"\n✓ pytest 通过！环境已可用。")
                return

    if deps["dep_groups"]:
        for grp in deps["dep_groups"]:
            log(f"  安装 --group {grp}...")
            exit_code, output = run_cmd(f"uv pip install --system --group {grp}", cwd, timeout=300)
            if exit_code == 0:
                log(f"  ✓ --group {grp} 安装成功")
            else:
                log(f"  ⚠ --group {grp} 安装失败 (exit {exit_code})")

            if run_pytest_check(cwd):
                print(f"\n✓ pytest 通过！环境已可用。")
                return

    print(f"\n{'=' * 60}")
    print("自动配置完成。运行 run_validation.py 查看详细结果。")
    print(f"{'=' * 60}")


def shlex_quote(s: str) -> str:
    """简单的 shell 转义。"""
    if not s:
        return '""'
    if re.match(r'^[a-zA-Z0-9_./-]+$', s):
        return s
    escaped = s.replace("'", "'\\''")
    return f"'{escaped}'"


if __name__ == "__main__":
    main()
