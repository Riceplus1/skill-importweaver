#!/usr/bin/env python3
"""
pypi_time_travel.py — 查某个 PyPI 包在仓库 commit 时间附近的版本。

用法：
    python pypi_time_travel.py <pkg_name> <repo_path>

输出候选版本列表，帮助选择与项目时间匹配的兼容版本。
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple


def get_repo_commit_time(repo_path: Path) -> Tuple[Optional[str], datetime]:
    """获取仓库 HEAD commit 的时间和 SHA。"""
    try:
        sha = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
        dt_str = subprocess.run(
            ["git", "-C", str(repo_path), "show", "-s", "--format=%cI", "HEAD"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
        if dt_str:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return sha or None, dt
    except Exception:
        pass
    return None, datetime.now(timezone.utc)


def fetch_pypi_json(project: str) -> dict:
    """从 PyPI API 获取包信息。"""
    url = f"https://pypi.org/pypi/{project}/json"
    req = urllib.request.Request(url, headers={
        "User-Agent": "importweaver-skill/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def main():
    parser = argparse.ArgumentParser(description="查某个 PyPI 包在仓库 commit 时间附近的版本")
    parser.add_argument("pkg_name", help="PyPI 包名")
    parser.add_argument("repo_path", help="目标仓库路径（用于获取 commit 时间）")
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.exists():
        print(f"错误：路径不存在 {repo_path}", file=sys.stderr)
        sys.exit(1)

    sha, ref_time = get_repo_commit_time(repo_path)
    print(f"[pypi_time_travel] PyPI version suggestions by repo commit time")
    print(f"- package: {args.pkg_name}")
    print(f"- reference_time: {ref_time.isoformat()}")
    if sha:
        print(f"- repo_sha: {sha}")

    try:
        data = fetch_pypi_json(args.pkg_name)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            alt = args.pkg_name.replace("_", "-")
            alt2 = args.pkg_name.replace("-", "_")
            print(f"\n项目未在 PyPI 找到。")
            print(f"  请求: {args.pkg_name!r}")
            print(f"  试试: {alt!r} 或 {alt2!r}")
        else:
            print(f"\nPyPI 查询失败 (HTTP {e.code})")
        sys.exit(1)
    except Exception as e:
        print(f"\nPyPI 查询失败: {e}")
        sys.exit(1)

    info = data.get("info", {}) if isinstance(data, dict) else {}
    releases_map = data.get("releases", {}) if isinstance(data, dict) else {}

    canonical_name = info.get("name") or args.pkg_name
    summary = (info.get("summary") or "").strip()

    if summary:
        print(f"- summary: {summary}")
    print(f"- canonical_name: {canonical_name}")

    # 解析版本
    releases = []
    for ver, files in (releases_map or {}).items():
        if not isinstance(files, list) or not files:
            continue
        upload_times = []
        for entry in files:
            if not isinstance(entry, dict):
                continue
            ts = entry.get("upload_time_iso_8601") or entry.get("upload_time") or ""
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                upload_times.append(dt)
            except ValueError:
                pass
        if upload_times:
            releases.append((ver, min(upload_times)))

    releases.sort(key=lambda x: x[1])

    before = [(v, t) for v, t in releases if t <= ref_time]
    after = [(v, t) for v, t in releases if t > ref_time]

    if not before:
        if after:
            first = after[0]
            print(f"\n没有在 commit 时间前发布的版本。")
            print(f"commit 后第一个版本: {first[0]} ({first[1].date().isoformat()})")
        else:
            print(f"\n没有找到任何版本。")
        return

    recent = sorted(before, key=lambda x: x[1], reverse=True)[:6]
    print(f"\n在 commit 时间前的最新版本:")
    for v, t in recent:
        delta = (ref_time - t).days
        print(f"  {v} ({t.date().isoformat()}, {delta}d before)")

    if after:
        print(f"\ncommit 后的第一个版本: {after[0][0]} ({after[0][1].date().isoformat()})")

    # 前一个 minor / major 版本
    def parse_ver(v: str) -> Optional[Tuple]:
        try:
            parts = [int(x) for x in v.lstrip("v").split(".")]
            return tuple(parts)
        except ValueError:
            return None

    base_parsed = parse_ver(recent[0][0])
    if base_parsed and len(base_parsed) >= 2:
        major, minor = base_parsed[0], base_parsed[1]
        prev_minor = None
        prev_major = None
        for v, _ in before:
            p = parse_ver(v)
            if p and len(p) >= 2:
                if p[0] == major and p[1] < minor:
                    if prev_minor is None or p > parse_ver(prev_minor[0]):
                        prev_minor = (v, p)
                if p[0] < major:
                    if prev_major is None or p > parse_ver(prev_major[0]):
                        prev_major = (v, p)
        print(f"\n上一个 minor: {prev_minor[0] if prev_minor else '未找到'}")
        print(f"上一个 major: {prev_major[0] if prev_major else '未找到'}")


if __name__ == "__main__":
    main()
