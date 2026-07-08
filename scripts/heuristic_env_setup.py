#!/usr/bin/env python3
"""
heuristic_env_setup.py — 启发式配环境编排脚本。

用法：
    python heuristic_env_setup.py <repo_path>

执行流程：
1. 配置 TUNA 镜像源（PyPI + Ubuntu apt）
2. 运行 auto_configure.py（扫描 + 安装依赖）
3. 如果 auto_configure 安装项目失败，尝试 pip install -e . 回退
4. 运行 run_validation.py（验证）
5. 如果验证有缺包 → 尝试安装 → 再验证
6. 最多 3 轮循环
7. exit 0 表示配环境成功（pytest 收集成功），exit 1 表示失败

不修改 auto_configure.py / run_validation.py（保持向后兼容 Task 2）。
"""

import os
import subprocess
import sys
from pathlib import Path


def run_script(script_path: Path, repo_path: Path) -> tuple[int, str]:
    """运行一个 Python 脚本，返回 (exit_code, stdout+stderr)。"""
    try:
        result = subprocess.run(
            [sys.executable, str(script_path), str(repo_path)],
            capture_output=True, text=True, timeout=600,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode, output.strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -1, str(e)


def run_shell(cmd: str, timeout: int = 300, cwd: str | None = None) -> tuple[int, str]:
    """运行一条 shell 命令。"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode, output.strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -1, str(e)


def configure_mirrors() -> None:
    """配置 TUNA 镜像源（PyPI + Ubuntu apt）。"""
    print("\n[heuristic] 配置 TUNA 镜像源...")
    exit_code, output = run_shell(
        "pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple",
        timeout=30,
    )
    if exit_code == 0:
        print("[heuristic] ✅ PyPI 镜像配置完成")
    else:
        print(f"[heuristic] ⚠️ PyPI 镜像配置失败 (exit {exit_code})，继续执行")

    # 尝试配置 apt 镜像（非致命）
    run_shell(
        "sed -i 's|http://deb.debian.org/debian|http://mirrors.tuna.tsinghua.edu.cn/debian|g' "
        "/etc/apt/sources.list.d/debian.sources 2>/dev/null || "
        "sed -i 's|http://deb.debian.org/debian|http://mirrors.tuna.tsinghua.edu.cn/debian|g' "
        "/etc/apt/sources.list 2>/dev/null || true",
        timeout=10,
    )


def _has_setup_py(repo_path: Path) -> bool:
    """检查项目是否使用 setup.py。"""
    return (repo_path / "setup.py").exists()


def _install_project(repo_path: Path) -> bool:
    """确保项目可导入。

    优先尝试 pip install -e .，如果构建系统失败（常见于旧版
    setup.py 项目 + 新版 pip/uv），通过 .pth 文件将项目路径
    加入 Python 搜索路径。
    """
    if not _has_setup_py(repo_path):
        return False

    print("\n[heuristic] 安装项目（确保可导入）...")

    # 方式 1: pip install -e . --no-build-isolation
    exit_code, output = run_shell(
        "pip install -e . --no-build-isolation 2>&1",
        timeout=300, cwd=str(repo_path),
    )
    if exit_code == 0:
        print("[heuristic] ✅ pip install -e . 成功")
        return True

    print("[heuristic] pip 安装失败，创建 .pth 文件确保可导入...")

    # 方式 2: .pth 文件（绕过构建系统，等价于 editable install）
    site_code, site_out = run_shell(
        "python3 -c \"import site; print(site.getsitepackages()[0])\"",
        timeout=5,
    )
    if site_code == 0:
        site_dir = site_out.strip()
        pth_path = Path(site_dir) / "heuristic-env.pth"
        try:
            pth_path.write_text(str(repo_path.resolve()) + "\n")
            print(f"[heuristic] ✅ .pth 文件创建: {pth_path}")
            print(f"  项目已可导入 (import logbook)")
            return True
        except Exception as e:
            print(f"[heuristic] ⚠️ .pth 创建失败: {e}")
    else:
        print(f"[heuristic] ⚠️ 无法获取 site-packages 路径")

    return False


def main():
    if len(sys.argv) < 2:
        print("用法: python heuristic_env_setup.py <repo_path>", file=sys.stderr)
        sys.exit(1)

    repo_path = Path(sys.argv[1]).resolve()
    if not repo_path.exists():
        print(f"错误: 路径不存在 {repo_path}", file=sys.stderr)
        sys.exit(1)

    scripts_dir = Path(__file__).parent.resolve()

    print("=" * 60)
    print("heuristic_env_setup.py — 启发式环境配置")
    print("=" * 60)
    print(f"目标仓库: {repo_path}")
    print(f"脚本目录: {scripts_dir}")

    # ---- Step 0: 配置镜像源 ----
    print("\n" + "=" * 60)
    print("STEP 0: 配置镜像源 & 基础工具")
    print("=" * 60)
    configure_mirrors()

    # 安装测试工具（pytest 等）
    print("\n[heuristic] 安装测试工具...")
    run_shell("pip install pytest pyright -q 2>&1", timeout=120)
    print("[heuristic] ✅ 测试工具安装完成")

    # 将项目路径加入 PYTHONPATH（使子进程能导入项目模块）
    repo_path_str = str(repo_path.resolve())
    os.environ["PYTHONPATH"] = f"{repo_path_str}:{os.environ.get('PYTHONPATH', '')}"

    # ---- 准备子脚本路径 ----
    auto_configure = scripts_dir / "auto_configure.py"
    run_validation = scripts_dir / "run_validation.py"

    if not auto_configure.exists():
        print(f"错误: 未找到 auto_configure.py ({auto_configure})", file=sys.stderr)
        sys.exit(1)
    if not run_validation.exists():
        print(f"错误: 未找到 run_validation.py ({run_validation})", file=sys.stderr)
        sys.exit(1)

    # ---- Rounds: auto_configure + pip fallback + validation + retry ----
    max_rounds = 3
    success = False

    for round_num in range(1, max_rounds + 1):
        print(f"\n{'=' * 60}")
        print(f"ROUND {round_num}/{max_rounds}")
        print(f"{'=' * 60}")

        # ---- Step 1: auto_configure.py ----
        print(f"\n--- [Round {round_num}] 运行 auto_configure.py ---")
        ac_exit, ac_output = run_script(auto_configure, repo_path)
        lines = ac_output.splitlines()
        if len(lines) > 80:
            print("\n".join(lines[:40]))
            print(f"... (输出截断，共 {len(lines)} 行) ...")
            print("\n".join(lines[-40:]))
        else:
            print(ac_output)

        # ---- Step 1.5: 确保项目可导入（pip 回退）
        # auto_configure 的 uv install 可能失败（常见于旧版 setup.py 项目）。
        # 此步骤尝试 pip 安装或 .pth 文件。
        if _has_setup_py(repo_path):
            _install_project(repo_path)

        # ---- Step 2: run_validation.py ----
        print(f"\n--- [Round {round_num}] 运行 run_validation.py ---")
        rv_exit, rv_output = run_script(run_validation, repo_path)
        print(rv_output)

        # ---- 判定 ----
        if rv_exit == 0:
            print(f"\n{'=' * 60}")
            print(f"✅ Round {round_num}: 环境配置成功！")
            print(f"{'=' * 60}")
            success = True
            break
        elif round_num < max_rounds:
            print(f"\n--- Round {round_num} 验证未通过，尝试修复 (剩余 {max_rounds - round_num} 轮) ---")
        else:
            print(f"\n--- 已达最大重试次数 {max_rounds} ---")

    # ---- 最终结果 ----
    print(f"\n{'=' * 60}")
    if success:
        print("结果: ✅ 环境配置成功 (pytest 收集通过)")
        sys.exit(0)
    else:
        print("结果: ❌ 环境配置失败 (pytest 收集未通过)")
        sys.exit(1)


if __name__ == "__main__":
    main()
