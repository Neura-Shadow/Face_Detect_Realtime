"""
Phase 11O source commit boundary and draft PR preparation gate.

此檢查用於建立可審查的 source-only commit 邊界。它不會自動 stage、
commit、tag、push 或建立 GitHub PR；只驗證目前 staged files 是否落在
允許的 source/docs/config 範圍內，並擋下 runtime logs、release artifacts、
本機環境、密鑰檔與暫存檔。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

ALLOWED_STAGE_ROOTS = {
    "backend",
    "config",
    "docs",
    "embedded",
    "frontend",
    "migrations",
    "scripts",
    "shared",
    "workers",
}
ALLOWED_ROOT_FILES = {
    ".gitignore",
    "README.md",
    "task.md",
    "walkthrough.md",
}
BLOCKED_PREFIXES = (
    ".git/",
    ".idea/",
    ".next/",
    "node_modules/",
    "release_artifacts/",
    "runtime_logs/",
    "test_env/",
)
BLOCKED_PARTS = {
    "__pycache__",
}
BLOCKED_FILE_NAMES = {
    ".env",
    "EncodeFile.p",
}
BLOCKED_SUFFIXES = {
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".pyo",
    ".tmp",
}
REQUIRED_FILES = (
    "docs/phase11o_source_commit_boundary_draft_pr.md",
    "scripts/run_phase11o_source_commit_checks.py",
)
REQUIRED_GITIGNORE_LINES = (
    ".env",
    "runtime_logs/",
    "release_artifacts/",
    "test_env/",
    "__pycache__/",
    "*.pyc",
    "*.log",
    "node_modules/",
    "experiments/phase13/*/",
)


@dataclass(frozen=True)
class GitCommandResult:
    """Git 命令的執行結果。"""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _run_git(args: list[str]) -> GitCommandResult:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return GitCommandResult(
        command=["git", *args],
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _git_lines(args: list[str]) -> list[str]:
    result = _run_git(args)
    if not result.ok:
        raise RuntimeError(result.stderr.strip() or f"git command failed: {' '.join(result.command)}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_env_like_file(path: str) -> bool:
    name = Path(path).name
    if name == ".env.example":
        return False
    return name.startswith(".env") or name.endswith(".env")


def _is_blocked_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    path_obj = Path(normalized)
    if normalized.startswith(BLOCKED_PREFIXES):
        return True
    if any(part in BLOCKED_PARTS for part in path_obj.parts):
        return True
    if path_obj.name in BLOCKED_FILE_NAMES:
        return True
    if path_obj.suffix.lower() in BLOCKED_SUFFIXES:
        return True
    return _is_env_like_file(normalized)


def _is_allowed_stage_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if _is_blocked_path(normalized):
        return False
    path_obj = Path(normalized)
    if len(path_obj.parts) == 1:
        return path_obj.name in ALLOWED_ROOT_FILES
    return path_obj.parts[0] in ALLOWED_STAGE_ROOTS


def _gitignore_status() -> dict[str, Any]:
    path = REPO_ROOT / ".gitignore"
    if not path.exists():
        return {
            "exists": False,
            "missing_required_lines": list(REQUIRED_GITIGNORE_LINES),
            "boundary_verified": False,
        }

    lines = {line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()}
    missing = [line for line in REQUIRED_GITIGNORE_LINES if line not in lines]
    return {
        "exists": True,
        "missing_required_lines": missing,
        "boundary_verified": not missing,
    }


def _collect_status() -> dict[str, Any]:
    staged_files = _git_lines(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    untracked_files = _git_lines(["ls-files", "--others", "--exclude-standard"])
    status_short = _git_lines(["status", "--short"])
    branch = _git_lines(["branch", "--show-current"])
    head = _git_lines(["rev-parse", "--short", "HEAD"])

    blocked_staged = [path for path in staged_files if _is_blocked_path(path)]
    outside_boundary = [path for path in staged_files if not _is_allowed_stage_path(path)]
    missing_required = [path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists()]

    return {
        "phase": "11O",
        "branch": branch[0] if branch else "",
        "head_short": head[0] if head else "",
        "staged_file_count": len(staged_files),
        "untracked_non_ignored_file_count": len(untracked_files),
        "status_entry_count": len(status_short),
        "staged_files": staged_files,
        "blocked_staged_files": blocked_staged,
        "outside_source_boundary_files": outside_boundary,
        "required_files_missing": missing_required,
        "gitignore": _gitignore_status(),
        "source_commit_boundary_verified": not blocked_staged
        and not outside_boundary
        and not missing_required
        and _gitignore_status()["boundary_verified"],
        "draft_pr_prepared": not missing_required,
        "remote_pr_created": False,
        "tag_created": False,
        "leaderboard_evaluated": False,
        "route_benchmark_verified": False,
        "infraction_benchmark_verified": False,
    }


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 11O source commit boundary gate")
    parser.add_argument(
        "--require-staged",
        action="store_true",
        help="要求目前至少有一個 staged file，適合在 git add 後、git commit 前執行。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="可選：將檢查摘要寫入 JSON 檔。預設只輸出到 stdout。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload = _collect_status()

    errors: list[str] = []
    if args.require_staged and payload["staged_file_count"] == 0:
        errors.append("require-staged enabled but no staged files were found")
    if payload["blocked_staged_files"]:
        errors.append("blocked files are staged")
    if payload["outside_source_boundary_files"]:
        errors.append("files outside the source commit boundary are staged")
    if payload["required_files_missing"]:
        errors.append("required Phase 11O files are missing")
    if not payload["gitignore"]["boundary_verified"]:
        errors.append("gitignore boundary is incomplete")

    payload["passed"] = not errors
    payload["errors"] = errors

    if args.output:
        _write_output(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if payload["passed"]:
        print("phase11o source commit boundary passed")
        return 0

    print("Phase 11O Source Commit Boundary Blocked", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
