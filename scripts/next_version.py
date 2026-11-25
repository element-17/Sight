"""
自动语义化版本计算与 Release Notes 生成脚本

规则（Conventional Commits）：
  - 若 commit 含 `BREAKING CHANGE:` / `BREAKING-CHANGE:` 或前缀带 `!:`（如 `feat!:`）→ 主版本号 +1 (X+1.0.0)
  - 否则若存在 `feat:` / `feat(...):` 提交 → 次版本号 +1 (X.Y+1.0)
  - 否则（fix / refactor / perf / docs / ci / chore 等）→ 修订号 +1 (X.Y.Z+1)
  - 若最近一次提交包含 `[skip release]` 或 `[no release]`（仅 push 模式），则跳过发版
  - 若 HEAD 已经存在语义化标签（仅 push 模式），则跳过发版避免重复发布

用法：
    python scripts/next_version.py --event push --repo element-17/Sight --notes-file release_notes.md
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
RELEASE_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?$")
CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s*(?P<desc>.+)$"
)
SKIP_MARKERS = ("[skip release]", "[no release]", "[release skip]")

_COMMIT_RECORD_SEP = "\x1e"
_COMMIT_FIELD_SEP = "\x1f"


@dataclasses.dataclass(frozen=True)
class CommitInfo:
    sha: str
    subject: str
    body: str = ""

    @property
    def short_sha(self) -> str:
        return self.sha[:7]


@dataclasses.dataclass(frozen=True)
class ReleasePlan:
    should_release: bool
    tag: str
    version: str
    prev_tag: str
    bump: str
    skip_reason: str
    commits: tuple[CommitInfo, ...]


def parse_semver(tag: str) -> tuple[int, int, int] | None:
    match = SEMVER_RE.match(tag.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def validate_manual_tag(raw: str) -> tuple[str, str]:
    text = raw.strip()
    if not RELEASE_TAG_RE.match(text):
        raise ValueError(f"非法版本号格式: {raw!r}（期望如 v0.2.0 或 0.2.0 或 v0.2.0-rc.1）")
    clean = text.lstrip("vV")
    return f"v{clean}", clean


def highest_semver_tag(tags: Sequence[str], *, exclude: str = "") -> str:
    parsed: list[tuple[tuple[int, int, int], str]] = []
    for t in tags:
        if exclude and t == exclude:
            continue
        ver = parse_semver(t)
        if ver is not None:
            parsed.append((ver, t))
    if not parsed:
        return ""
    parsed.sort(key=lambda item: item[0], reverse=True)
    return parsed[0][1]


def determine_bump(commits: Sequence[CommitInfo]) -> str:
    """根据提交集合推断版本递增级别：major / minor / patch。"""
    has_minor = False
    for c in commits:
        subject = c.subject.strip()
        body = c.body or ""
        if "BREAKING CHANGE:" in body or "BREAKING-CHANGE:" in body:
            return "major"
        m = CONVENTIONAL_RE.match(subject)
        if m:
            if m.group("breaking"):
                return "major"
            if m.group("type").lower() == "feat":
                has_minor = True
    return "minor" if has_minor else "patch"


def bump_semver(base: tuple[int, int, int], level: str) -> tuple[int, int, int]:
    major, minor, patch = base
    if level == "major":
        return major + 1, 0, 0
    if level == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def compute_next_tag(
    base_tag: str,
    commits: Sequence[CommitInfo],
    existing_tags: set[str] | None = None,
) -> tuple[str, str, str]:
    """基于基准标签与提交历史计算下一个不冲突的版本标签，返回 (tag, clean_version, bump)。"""
    existing = existing_tags or set()
    if not base_tag:
        candidate = (0, 1, 0)
        bump = "initial"
    else:
        parsed = parse_semver(base_tag)
        if parsed is None:
            raise ValueError(f"基准标签不是标准语义化版本: {base_tag!r}")
        bump = determine_bump(commits)
        candidate = bump_semver(parsed, bump)

    while f"v{candidate[0]}.{candidate[1]}.{candidate[2]}" in existing:
        candidate = (candidate[0], candidate[1], candidate[2] + 1)

    clean = f"{candidate[0]}.{candidate[1]}.{candidate[2]}"
    return f"v{clean}", clean, bump


def has_skip_marker(commit: CommitInfo) -> bool:
    combined = f"{commit.subject}\n{commit.body}".lower()
    return any(marker in combined for marker in SKIP_MARKERS)


def format_release_notes(
    tag: str,
    prev_tag: str,
    commits: Sequence[CommitInfo],
    repo: str = "",
) -> str:
    """生成分组清晰的 Markdown Release Notes。"""
    sections: dict[str, list[str]] = {
        "feat": [],
        "fix": [],
        "refactor": [],
        "docs": [],
        "other": [],
    }
    breaking_notes: list[str] = []

    for c in commits:
        subject = c.subject.strip()
        if not subject:
            continue
        m = CONVENTIONAL_RE.match(subject)
        line_tail = f" (`{c.short_sha}`)"
        if m:
            ctype = m.group("type").lower()
            scope = m.group("scope")
            desc = m.group("desc").strip()
            prefix = f"**{scope}**: " if scope else ""
            bullet = f"- {prefix}{desc}{line_tail}"
            if m.group("breaking") or "BREAKING CHANGE:" in c.body or "BREAKING-CHANGE:" in c.body:
                breaking_notes.append(bullet)
            if ctype == "feat":
                sections["feat"].append(bullet)
            elif ctype == "fix":
                sections["fix"].append(bullet)
            elif ctype in ("refactor", "perf"):
                sections["refactor"].append(bullet)
            elif ctype in ("docs", "ci", "chore", "build", "test", "style"):
                sections["docs"].append(bullet)
            else:
                sections["other"].append(bullet)
        else:
            if "BREAKING CHANGE:" in c.body or "BREAKING-CHANGE:" in c.body:
                breaking_notes.append(f"- {subject}{line_tail}")
            sections["other"].append(f"- {subject}{line_tail}")

    lines: list[str] = [
        f"## Sight {tag}",
        "",
        "自动构建并发布的 Sight 全平台独立可执行版本（内置前端界面与 Python 运行时，解压即用）。",
        "",
    ]

    if breaking_notes:
        lines.extend(["### ⚠️ 破坏性变更 (Breaking Changes)", *breaking_notes, ""])
    if sections["feat"]:
        lines.extend(["### ✨ 新功能 (Features)", *sections["feat"], ""])
    if sections["fix"]:
        lines.extend(["### 🐛 问题修复 (Bug Fixes)", *sections["fix"], ""])
    if sections["refactor"]:
        lines.extend(["### ♻️ 重构与优化 (Refactor & Performance)", *sections["refactor"], ""])
    if sections["docs"]:
        lines.extend(["### 📚 文档与工程维护 (Docs, CI & Chore)", *sections["docs"], ""])
    if sections["other"]:
        lines.extend(["### 📦 其他变更 (Other Changes)", *sections["other"], ""])

    if not any(sections.values()):
        lines.extend(["- 例行重新打包发布。", ""])

    lines.extend(
        [
            "### 📥 下载与使用",
            "",
            "| 平台 | 发行包 | 启动方式 |",
            "| :--- | :--- | :--- |",
            f"| Windows (x64) | `Sight-{tag}-windows-x64.zip` | 解压后双击 `Sight.exe`（或 `start.bat`） |",
            f"| macOS (Apple Silicon) | `Sight-{tag}-macos-arm64.tar.gz` | 解压后运行 `./Sight` 或双击 `start.command` |",
            f"| Linux (x64) | `Sight-{tag}-linux-x64.tar.gz` | 解压后运行 `./Sight` 或 `./start.sh` |",
            "",
            "- 默认访问地址：`http://127.0.0.1:5001`（支持 `--port` / `--host` / `--no-browser` 参数）。",
            "- 凭证 (`credentials/`)、SQLite 数据库 (`data/`) 与日志 (`logs/`) 默认保存在程序同级目录。",
            "- 可选依赖：小红书与抖音部分 JS 签名接口需本机安装 Node.js 22+，未安装时其余平台不受影响。",
            "- 下载完整性可通过附件中的 `SHA256SUMS.txt` 校验。",
        ]
    )

    if repo:
        lines.append("")
        if prev_tag:
            lines.append(f"**Full Changelog**: https://github.com/{repo}/compare/{prev_tag}...{tag}")
        else:
            lines.append(f"**Full Changelog**: https://github.com/{repo}/commits/{tag}")

    return "\n".join(lines) + "\n"


def _run_git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return proc.stdout


def _list_git_tags(cwd: Path, *, merged_ref: str = "", points_at: str = "") -> list[str]:
    cmd = ["tag", "--list"]
    if merged_ref:
        cmd.extend(["--merged", merged_ref])
    if points_at:
        cmd.extend(["--points-at", points_at])
    out = _run_git(cmd, cwd)
    return [line.strip() for line in out.splitlines() if line.strip()]


def _is_ancestor(cwd: Path, ref: str, descendant: str = "HEAD") -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ref, descendant],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _commit_timestamp(cwd: Path, ref: str) -> int | None:
    try:
        out = _run_git(["show", "-s", "--format=%ct", ref], cwd).strip()
        return int(out)
    except Exception:
        return None


def _list_git_commits(
    cwd: Path,
    rev_range: str,
    *,
    include_merges: bool = False,
    since_ts: int | None = None,
) -> list[CommitInfo]:
    fmt = f"%H{_COMMIT_FIELD_SEP}%s{_COMMIT_FIELD_SEP}%b{_COMMIT_RECORD_SEP}"
    cmd = ["log"]
    if not include_merges:
        cmd.append("--no-merges")
    if since_ts is not None:
        cmd.append(f"--since=@{since_ts}")
    cmd.extend([f"--format={fmt}", rev_range])
    out = _run_git(cmd, cwd)
    commits: list[CommitInfo] = []
    for raw_rec in out.split(_COMMIT_RECORD_SEP):
        rec = raw_rec.strip("\r\n")
        if not rec:
            continue
        parts = rec.split(_COMMIT_FIELD_SEP)
        if len(parts) < 2:
            continue
        sha = parts[0].strip()
        subject = parts[1].strip()
        body = parts[2].strip() if len(parts) > 2 else ""
        if sha:
            commits.append(CommitInfo(sha=sha, subject=subject, body=body))
    return commits


def _commits_since_tag(cwd: Path, prev_tag: str) -> list[CommitInfo]:
    """收集自 prev_tag 以来到 HEAD 的提交；若历史发生过 rebase 导致标签脱离祖先链，按时间戳兜底。"""
    if not prev_tag:
        return _list_git_commits(cwd, "HEAD")
    if _is_ancestor(cwd, prev_tag, "HEAD"):
        return _list_git_commits(cwd, f"{prev_tag}..HEAD")
    ts = _commit_timestamp(cwd, prev_tag)
    if ts is not None:
        return _list_git_commits(cwd, "HEAD", since_ts=ts + 1)
    return _list_git_commits(cwd, f"{prev_tag}..HEAD")


def build_release_plan(
    repo_root: Path,
    *,
    event: str = "push",
    ref_name: str = "",
    manual_version: str = "",
) -> ReleasePlan:
    all_tags = _list_git_tags(repo_root)
    all_tags_set = set(all_tags)
    merged_tags = _list_git_tags(repo_root, merged_ref="HEAD")
    head_tags = _list_git_tags(repo_root, points_at="HEAD")

    # 场景 1：手动指定版本号（workflow_dispatch）
    if manual_version.strip():
        tag, clean = validate_manual_tag(manual_version)
        prev_tag = highest_semver_tag(merged_tags, exclude=tag) or highest_semver_tag(all_tags, exclude=tag)
        commits = tuple(_commits_since_tag(repo_root, prev_tag))
        return ReleasePlan(
            should_release=True,
            tag=tag,
            version=clean,
            prev_tag=prev_tag,
            bump="manual",
            skip_reason="",
            commits=commits,
        )

    # 场景 2：显式推送 v* 标签
    if event == "tag":
        if not ref_name.strip():
            raise ValueError("event=tag 时必须提供 --ref-name")
        tag, clean = validate_manual_tag(ref_name)
        prev_tag = highest_semver_tag(merged_tags, exclude=tag) or highest_semver_tag(all_tags, exclude=tag)
        commits = tuple(_commits_since_tag(repo_root, prev_tag))
        return ReleasePlan(
            should_release=True,
            tag=tag,
            version=clean,
            prev_tag=prev_tag,
            bump="tag",
            skip_reason="",
            commits=commits,
        )

    # 场景 3：push 到主分支 或 workflow_dispatch 自动计算
    head_commits = _list_git_commits(repo_root, "-n1", include_merges=True)
    head_commit = head_commits[0] if head_commits else None

    if event == "push":
        if head_commit and has_skip_marker(head_commit):
            return ReleasePlan(
                should_release=False,
                tag="",
                version="",
                prev_tag=highest_semver_tag(merged_tags) or highest_semver_tag(all_tags),
                bump="",
                skip_reason="最新提交包含跳过发布标记 ([skip release])",
                commits=(),
            )
        existing_head_semver = highest_semver_tag(head_tags)
        if existing_head_semver:
            return ReleasePlan(
                should_release=False,
                tag=existing_head_semver,
                version=existing_head_semver.lstrip("vV"),
                prev_tag=existing_head_semver,
                bump="",
                skip_reason=f"当前提交已绑定版本标签 {existing_head_semver}",
                commits=(),
            )

    prev_tag = highest_semver_tag(merged_tags) or highest_semver_tag(all_tags)
    commits = tuple(_commits_since_tag(repo_root, prev_tag))

    if event == "push" and prev_tag and not commits:
        return ReleasePlan(
            should_release=False,
            tag="",
            version="",
            prev_tag=prev_tag,
            bump="",
            skip_reason=f"自 {prev_tag} 以来无新增提交",
            commits=(),
        )

    # 若存在比 reachable tag 更高的全局标签，以两者中较高者为基准，避免版本号倒退
    global_latest = highest_semver_tag(all_tags)
    base_tag = highest_semver_tag([t for t in (prev_tag, global_latest) if t])
    tag, clean, bump = compute_next_tag(base_tag, commits, existing_tags=all_tags_set)

    return ReleasePlan(
        should_release=True,
        tag=tag,
        version=clean,
        prev_tag=prev_tag,
        bump=bump,
        skip_reason="",
        commits=commits,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="计算下一个 Sight 发布版本并生成 Release Notes")
    parser.add_argument("--repo-root", default=".", help="Git 仓库根目录")
    parser.add_argument(
        "--event",
        choices=("push", "tag", "workflow_dispatch"),
        default="push",
        help="触发事件类型",
    )
    parser.add_argument("--ref-name", default="", help="Git 标签名（event=tag 时传入）")
    parser.add_argument("--manual-version", default="", help="手动指定版本号（可选）")
    parser.add_argument("--repo", default="", help="GitHub 仓库路径（owner/repo），用于生成变更对比链接")
    parser.add_argument("--notes-file", default="", help="输出 Release Notes Markdown 文件路径")
    parser.add_argument("--github-output", default="", help="写入 GitHub Actions GITHUB_OUTPUT 的文件路径")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    plan = build_release_plan(
        repo_root,
        event=args.event,
        ref_name=args.ref_name,
        manual_version=args.manual_version,
    )

    print(f"[next_version] should_release={plan.should_release}")
    if plan.should_release:
        print(
            f"[next_version] prev_tag={plan.prev_tag or '(none)'} -> "
            f"tag={plan.tag} (bump={plan.bump}, commits={len(plan.commits)})"
        )
    else:
        print(f"[next_version] skip_reason={plan.skip_reason}")

    if plan.should_release and args.notes_file:
        notes = format_release_notes(plan.tag, plan.prev_tag, plan.commits, repo=args.repo)
        notes_path = Path(args.notes_file)
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        notes_path.write_text(notes, encoding="utf-8")
        print(f"[next_version] Release notes written to {notes_path}")

    gh_out = args.github_output or os.environ.get("GITHUB_OUTPUT", "").strip()
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"should_release={'true' if plan.should_release else 'false'}\n")
            f.write(f"tag={plan.tag}\n")
            f.write(f"version={plan.version}\n")
            f.write(f"prev_tag={plan.prev_tag}\n")
            f.write(f"bump={plan.bump}\n")
            f.write(f"skip_reason={plan.skip_reason}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
