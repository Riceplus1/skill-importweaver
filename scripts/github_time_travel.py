#!/usr/bin/env python3
"""
github_time_travel.py — 查某个 GitHub 仓库在参考时间前的 commit。

用法：
    python github_time_travel.py <owner/repo> <repo_path>

输出历史 commit 列表，帮助 git+https 依赖选兼容版本。
"""

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple


GITHUB_API = "https://api.github.com"


def get_repo_commit_time(repo_path: Path) -> datetime:
    """获取仓库 HEAD commit 的时间。"""
    try:
        dt_str = subprocess.run(
            ["git", "-C", str(repo_path), "show", "-s", "--format=%cI", "HEAD"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
        if dt_str:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        pass
    return datetime.now(timezone.utc)


def fetch_commits_before(owner: str, repo: str, ref_time: datetime, per_page: int = 30) -> List[dict]:
    """通过 GitHub API 获取参考时间前的 commit。"""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits?per_page={per_page}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "importweaver-skill/1.0",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        commits = json.loads(resp.read().decode("utf-8", errors="replace"))

    result = []
    for c in commits:
        if not isinstance(c, dict):
            continue
        date_str = c.get("commit", {}).get("committer", {}).get("date", "")
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt <= ref_time:
            sha = (c.get("sha") or "")[:12]
            msg = (c.get("commit", {}).get("message") or "").split("\n")[0]
            result.append((sha, dt, msg))

    return result


def main():
    parser = argparse.ArgumentParser(description="查某个 GitHub 仓库在参考时间前的 commit")
    parser.add_argument("repo", help="GitHub 仓库 (owner/repo)")
    parser.add_argument("repo_path", help="目标仓库路径（用于获取参考时间）")
    args = parser.parse_args()

    # 解析 owner/repo
    repo = args.repo.strip().rstrip(".git")
    if "/" not in repo:
        print(f"错误：仓库格式无效。请使用 owner/repo 格式", file=sys.stderr)
        sys.exit(1)

    parts = repo.split("/")
    if len(parts) < 2:
        print(f"错误：仓库格式无效", file=sys.stderr)
        sys.exit(1)
    owner, name = parts[-2], parts[-1]

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.exists():
        print(f"错误：路径不存在 {repo_path}", file=sys.stderr)
        sys.exit(1)

    ref_time = get_repo_commit_time(repo_path)
    print(f"[github_time_travel] GitHub commit suggestions by reference time")
    print(f"- repo: {owner}/{name}")
    print(f"- reference_time: {ref_time.isoformat()}")

    try:
        commits = fetch_commits_before(owner, name, ref_time)
    except Exception as e:
        print(f"\n获取 commit 失败: {e}")
        sys.exit(1)

    if not commits:
        print(f"\n在参考时间前未找到任何 commit。")
        return

    print(f"\n参考时间前的 commit (最多 {len(commits)} 条):")
    for sha, dt, msg in commits:
        print(f"  {sha} ({dt.isoformat()}) {msg}")


if __name__ == "__main__":
    main()
