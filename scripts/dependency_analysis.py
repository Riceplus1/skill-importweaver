#!/usr/bin/env python3
"""
dependency_analysis.py — 分析 Python 项目的依赖文件结构。

用法：
    python dependency_analysis.py <repo_path>

输出项目依赖文件的清单和关键内容摘要，帮助了解项目需要哪些依赖。
"""

import argparse
import tomllib
from pathlib import Path
from typing import List, Set


_EXCLUDED_DIR_PARTS: Set[str] = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".idea", ".vscode",
    "output", ".ruff_cache", ".tox", "node_modules",
}


def truncate_head_tail(text: str, limit: int = 3000, marker: str = "\n...[truncated]...\n") -> str:
    if len(text) <= limit:
        return text
    head_ratio = 0.6
    head_len = int(limit * head_ratio)
    tail_len = limit - head_len - len(marker)
    return text[:head_len] + marker + (text[-tail_len:] if tail_len > 0 else "")


def _summarize_pyproject(path: Path) -> str:
    """解析 pyproject.toml 提取关键依赖信息。"""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    try:
        data = tomllib.loads(raw)
    except Exception:
        data = None

    if not isinstance(data, dict):
        return truncate_head_tail("\n".join(raw.splitlines()[:120]), limit=2500)

    lines: List[str] = []
    project = data.get("project") if isinstance(data.get("project"), dict) else None
    if project:
        name = project.get("name")
        requires_python = project.get("requires-python")
        deps = project.get("dependencies") if isinstance(project.get("dependencies"), list) else []
        opt = project.get("optional-dependencies") if isinstance(project.get("optional-dependencies"), dict) else {}
        if name:
            lines.append(f"[project] name = {name!r}")
        if requires_python:
            lines.append(f"[project] requires-python = {requires_python!r}")
        if deps:
            preview = ", ".join(str(item) for item in deps[:20])
            suffix = " ..." if len(deps) > 20 else ""
            lines.append(f"[project] dependencies({len(deps)}): {preview}{suffix}")
        if opt:
            lines.append(f"[project] optional-dependencies groups: {', '.join(sorted(opt.keys()))}")

    dep_groups = data.get("dependency-groups") if isinstance(data.get("dependency-groups"), dict) else {}
    if dep_groups:
        lines.append(f"[dependency-groups] groups: {', '.join(sorted(dep_groups.keys()))}")

    text = "\n".join(lines).strip()
    return truncate_head_tail(text, limit=4000)


def _collect_dependency_context(repo_path: Path, max_chars: int = 30000) -> str:
    """扫描项目，生成依赖文件的摘要报告。"""
    if not repo_path.exists():
        return ""

    candidates = [
        "pyproject.toml", "setup.py", "setup.cfg",
        "requirements.txt", "constraints.txt",
        "Makefile", "tox.ini", "pytest.ini", "pyrightconfig.json",
    ]

    found = [name for name in candidates if (repo_path / name).exists()]

    lock_files: List[Path] = []
    for pattern in ("uv.lock", "poetry.lock", "pdm.lock", "Pipfile", "Pipfile.lock"):
        for path in sorted(repo_path.rglob(pattern)):
            if any(part in _EXCLUDED_DIR_PARTS for part in path.parts):
                continue
            lock_files.append(path)

    req_files: List[Path] = sorted(repo_path.glob("requirements*.txt"))
    req_dir = repo_path / "requirements"
    if req_dir.is_dir():
        req_files.extend(sorted(req_dir.glob("*.txt")))
    req_files = list(dict.fromkeys(req_files))

    sections: List[str] = []
    sections.append("Dependency files detected:")
    sections.append("- " + ", ".join(found + [str(p.relative_to(repo_path)) for p in req_files]))

    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        summary = _summarize_pyproject(pyproject)
        if summary:
            sections.append("\npyproject.toml summary:")
            sections.append(summary)

    for path in lock_files:
        rel = path.relative_to(repo_path)
        rel_dir = rel.parent.as_posix() or "."
        hints = {
            "uv.lock": f"cd {rel_dir} && uv export --frozen -o - | uv pip install -r -",
            "poetry.lock": f"cd {rel_dir} && poetry export --all-extras | uv pip install --system -r -",
            "pdm.lock": f"cd {rel_dir} && pdm export --all-extras -f requirements | uv pip install --system -r -",
        }
        cmd = hints.get(path.name)
        if cmd:
            sections.append(f"\n{path.name} present at {rel}: run `{cmd}`.")

    text = "\n".join(sections).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]..."
    return text


def main():
    parser = argparse.ArgumentParser(description="分析 Python 项目的依赖文件结构")
    parser.add_argument("repo_path", help="目标仓库路径")
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.exists():
        print(f"错误：路径不存在 {repo_path}", file=sys.stderr)
        sys.exit(1)

    result = _collect_dependency_context(repo_path)
    print(result)


if __name__ == "__main__":
    main()
