"""
Phase 11N git snapshot, artifact boundary, and release packaging gate.

此 runner 不會自動 stage、commit 或 push。它會把目前 git 狀態、Phase 11M
evidence、artifact include/exclude 邊界與 release zip 打包成可審核的
release artifact。這是 release packaging gate，不是 CARLA Leaderboard、
正式 route benchmark 或 infraction benchmark。
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = REPO_ROOT / "runtime_logs" / "carla_runs" / "20260614T173740Z"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "release_artifacts"

SOURCE_DIRS = (
    "backend",
    "config",
    "docs",
    "frontend",
    "migrations",
    "scripts",
    "shared",
    "workers",
)
ROOT_FILES = (
    ".gitignore",
    "README.md",
    "task.md",
    "walkthrough.md",
)
EVIDENCE_FILES = (
    "manifest.json",
    "metrics.json",
    "events.jsonl",
    "commands.txt",
    "environment.txt",
    "regression.txt",
)
EXCLUDED_DIR_NAMES = {
    ".git",
    ".idea",
    ".next",
    "__pycache__",
    "images",
    "node_modules",
    "release_artifacts",
    "runtime_logs",
    "test_env",
}
EXCLUDED_FILE_NAMES = {
    ".env",
    "EncodeFile.p",
}
EXCLUDED_SUFFIXES = {
    ".log",
    ".pyc",
    ".pyo",
    ".tmp",
}
EXCLUDED_PATTERNS = (
    ".env*",
    "*.env",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
)
BENCHMARK_BOUNDARY_SCOPE = "structured_release_artifact_only_not_carla_leaderboard"


@dataclass(frozen=True)
class CommandResult:
    """外部命令執行結果。"""

    name: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_sec: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def command_text(self) -> str:
        return subprocess.list2cmdline(self.command)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_command(name: str, command: list[str], *, timeout_sec: float = 120.0) -> CommandResult:
    started = time.perf_counter()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        return CommandResult(
            name=name,
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
            duration_sec=round(time.perf_counter() - started, 3),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return CommandResult(
            name=name,
            command=command,
            returncode=124,
            stdout=stdout.strip(),
            stderr=(stderr.strip() or f"timeout after {timeout_sec}s"),
            duration_sec=round(time.perf_counter() - started, 3),
        )


def _timestamped_run_dir(output_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / stamp
    suffix = 1
    while run_dir.exists():
        run_dir = output_dir / f"{stamp}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_excluded(rel_path: Path) -> bool:
    parts = set(rel_path.parts)
    if parts & EXCLUDED_DIR_NAMES:
        return True
    if rel_path.name in EXCLUDED_FILE_NAMES:
        return True
    if rel_path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    text = rel_path.as_posix()
    return any(fnmatch.fnmatch(rel_path.name, pattern) or fnmatch.fnmatch(text, pattern) for pattern in EXCLUDED_PATTERNS)


def _copy_file(src: Path, dst: Path, release_dir: Path) -> dict[str, Any]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return {
        "path": dst.relative_to(release_dir).as_posix(),
        "size_bytes": dst.stat().st_size,
        "sha256": _sha256_file(dst),
    }


def _collect_source_files() -> list[Path]:
    files: list[Path] = []
    for name in ROOT_FILES:
        path = REPO_ROOT / name
        if path.exists() and not _is_excluded(Path(name)):
            files.append(path)

    for directory_name in SOURCE_DIRS:
        root = REPO_ROOT / directory_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel_path = path.relative_to(REPO_ROOT)
            if not _is_excluded(rel_path):
                files.append(path)
    return sorted(files, key=lambda item: item.relative_to(REPO_ROOT).as_posix().lower())


def _copy_source_tree(release_dir: Path) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    source_root = release_dir / "source"
    for path in _collect_source_files():
        rel_path = path.relative_to(REPO_ROOT)
        copied.append(_copy_file(path, source_root / rel_path, release_dir))
    return copied


def _copy_evidence(evidence_dir: Path, release_dir: Path) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    evidence_root = release_dir / "evidence" / "phase11m"
    for name in EVIDENCE_FILES:
        path = evidence_dir / name
        if not path.exists():
            raise RuntimeError(f"Phase 11N blocked: required evidence file missing: {path}")
        copied.append(_copy_file(path, evidence_root / name, release_dir))
    return copied


def _git_snapshot() -> dict[str, Any]:
    commands = {
        "repo_root": ["git", "rev-parse", "--show-toplevel"],
        "branch": ["git", "branch", "--show-current"],
        "head": ["git", "rev-parse", "HEAD"],
        "head_short": ["git", "rev-parse", "--short", "HEAD"],
        "head_subject": ["git", "show", "-s", "--format=%s"],
        "head_committed_at": ["git", "show", "-s", "--format=%cI"],
        "status_porcelain": ["git", "status", "--porcelain=v1", "-uall"],
        "diff_stat": ["git", "diff", "--stat"],
        "tracked_files": ["git", "ls-files"],
    }
    results = {name: _run_command(f"git_{name}", command, timeout_sec=60) for name, command in commands.items()}
    status_lines = [line for line in results["status_porcelain"].stdout.splitlines() if line.strip()]
    tracked_lines = [line for line in results["tracked_files"].stdout.splitlines() if line.strip()]
    return {
        "repo_root": results["repo_root"].stdout,
        "branch": results["branch"].stdout,
        "head": results["head"].stdout,
        "head_short": results["head_short"].stdout,
        "head_subject": results["head_subject"].stdout,
        "head_committed_at": results["head_committed_at"].stdout,
        "status_clean": len(status_lines) == 0,
        "status_entry_count": len(status_lines),
        "status_porcelain": status_lines,
        "tracked_file_count": len(tracked_lines),
        "diff_stat": results["diff_stat"].stdout,
    }


def _validate_phase11m_evidence(metrics: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "phase_is_11m": metrics.get("phase") == "Phase 11M" and manifest.get("phase") == "Phase 11M",
        "result_passed": metrics.get("result") == "passed" and manifest.get("result") == "passed",
        "grp_required": metrics.get("grp_route_required") is True,
        "grp_available": metrics.get("grp_route_available") is True,
        "grp_no_fallback": metrics.get("grp_fallback_used") is False,
        "grp_following_verified": metrics.get("grp_route_following_verified") is True,
        "goal_reached": metrics.get("fixed_route_goal_reached") is True,
        "completion_verified": metrics.get("fixed_route_completion_verified") is True,
        "best_distance_within_tolerance": float(metrics.get("best_distance_to_goal_m", 999.0)) <= 3.0,
        "benchmark_boundary_prepared": metrics.get("benchmark_boundary_prepared") is True,
        "no_route_benchmark_claim": metrics.get("route_benchmark_verified") is False,
        "no_infraction_benchmark_claim": metrics.get("infraction_benchmark_verified") is False,
        "no_leaderboard_claim": metrics.get("leaderboard_evaluated") is False,
        "regression_passed": metrics.get("regression_passed") is True,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "summary": {
            "evidence_status": manifest.get("status"),
            "steps_completed": metrics.get("steps_completed"),
            "grp_route_source": metrics.get("grp_route_source"),
            "grp_route_waypoint_count": metrics.get("grp_route_waypoint_count"),
            "goal_reach_step": metrics.get("goal_reach_step"),
            "best_distance_to_goal_m": metrics.get("best_distance_to_goal_m"),
            "lane_invasion_count": metrics.get("lane_invasion_count"),
            "collision_count": metrics.get("collision_count"),
        },
    }


def _build_artifact_boundary(
    *,
    evidence_dir: Path,
    source_files: list[dict[str, Any]],
    evidence_files: list[dict[str, Any]],
    validation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "Phase 11N",
        "artifact_boundary_prepared": True,
        "artifact_boundary_scope": "source_docs_phase11m_evidence_release_metadata",
        "included": {
            "source_dirs": list(SOURCE_DIRS),
            "root_files": list(ROOT_FILES),
            "phase11m_evidence_dir": str(evidence_dir),
            "phase11m_evidence_files": list(EVIDENCE_FILES),
            "source_file_count": len(source_files),
            "evidence_file_count": len(evidence_files),
        },
        "excluded": {
            "secret_files": [".env", "config/.env", "*.env"],
            "env_templates": [".env.example", "config/.env.example"],
            "runtime_logs_except_phase11m_evidence": True,
            "git_directory": True,
            "local_envs_and_caches": ["test_env", "__pycache__", "node_modules", ".next"],
            "legacy_face_assets": ["images", "EncodeFile.p"],
            "large_or_transient_logs": ["*.log"],
        },
        "secret_file_boundary_verified": True,
        "phase11m_evidence_validation": validation,
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        "leaderboard_routes_exported": False,
        "leaderboard_route_criteria_evaluated": False,
        "route_benchmark_verified": False,
        "infraction_benchmark_verified": False,
        "leaderboard_evaluated": False,
    }


def _write_git_snapshot_text(path: Path, snapshot: dict[str, Any]) -> None:
    lines = [
        "# Phase 11N Git Snapshot",
        "",
        f"repo_root: {snapshot['repo_root']}",
        f"branch: {snapshot['branch']}",
        f"head: {snapshot['head']}",
        f"head_short: {snapshot['head_short']}",
        f"head_subject: {snapshot['head_subject']}",
        f"head_committed_at: {snapshot['head_committed_at']}",
        f"status_clean: {snapshot['status_clean']}",
        f"status_entry_count: {snapshot['status_entry_count']}",
        f"tracked_file_count: {snapshot['tracked_file_count']}",
        "",
        "## Status Porcelain",
        "",
        *(snapshot["status_porcelain"] or ["(clean)"]),
        "",
        "## Diff Stat",
        "",
        snapshot["diff_stat"] or "(empty)",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_checksums(path: Path, release_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for file_path in sorted(release_dir.rglob("*"), key=lambda item: item.relative_to(release_dir).as_posix().lower()):
        if not file_path.is_file() or file_path.name == path.name or file_path.suffix == ".zip":
            continue
        rel_path = file_path.relative_to(release_dir).as_posix()
        digest = _sha256_file(file_path)
        entries.append({"path": rel_path, "sha256": digest, "size_bytes": file_path.stat().st_size})
    lines = [f"{entry['sha256']}  {entry['path']}" for entry in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return entries


def _create_zip(release_dir: Path, package_path: Path) -> None:
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file_path in sorted(release_dir.rglob("*"), key=lambda item: item.relative_to(release_dir).as_posix().lower()):
            if not file_path.is_file() or file_path == package_path:
                continue
            archive.write(file_path, file_path.relative_to(release_dir).as_posix())


def _build_text_report(title: str, results: list[CommandResult]) -> str:
    lines = [title, ""]
    for result in results:
        lines.extend(
            [
                f"## {result.name}",
                f"command: {result.command_text}",
                f"returncode: {result.returncode}",
                f"duration_sec: {result.duration_sec}",
                "",
                "stdout:",
                result.stdout or "(empty)",
                "",
                "stderr:",
                result.stderr or "(empty)",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _run_regressions() -> list[CommandResult]:
    return [
        _run_command(
            "phase11n_py_compile",
            [sys.executable, "-m", "py_compile", "scripts\\run_phase11n_release_packaging.py"],
            timeout_sec=60,
        ),
        _run_command(
            "base_phase11_carla_checks",
            [sys.executable, "scripts\\run_phase11_carla_checks.py"],
            timeout_sec=240,
        ),
        _run_command(
            "base_demo_checks",
            [sys.executable, "scripts\\run_demo_checks.py"],
            timeout_sec=360,
        ),
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 11N release packaging gate")
    parser.add_argument("--phase11m-evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--package-prefix", default="ma-vlna_phase11n_release")
    parser.add_argument("--require-clean-git", action="store_true")
    parser.add_argument("--run-regressions", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    evidence_dir = args.phase11m_evidence_dir.resolve()
    output_dir = args.output_dir.resolve()
    run_dir = _timestamped_run_dir(output_dir)

    metrics = _read_json(evidence_dir / "metrics.json")
    evidence_manifest = _read_json(evidence_dir / "manifest.json")
    validation = _validate_phase11m_evidence(metrics, evidence_manifest)
    git_snapshot = _git_snapshot()

    source_files = _copy_source_tree(run_dir)
    evidence_files = _copy_evidence(evidence_dir, run_dir)
    boundary = _build_artifact_boundary(
        evidence_dir=evidence_dir,
        source_files=source_files,
        evidence_files=evidence_files,
        validation=validation,
    )

    if args.require_clean_git and not git_snapshot["status_clean"]:
        boundary["git_clean_required"] = True
        boundary["git_clean_verified"] = False
    else:
        boundary["git_clean_required"] = bool(args.require_clean_git)
        boundary["git_clean_verified"] = bool(git_snapshot["status_clean"])

    regression_results = _run_regressions() if args.run_regressions else []
    regression_passed = bool(regression_results) and all(result.ok for result in regression_results)
    if args.run_regressions:
        (run_dir / "regression.txt").write_text(
            _build_text_report("# Phase 11N regression proof", regression_results),
            encoding="utf-8",
        )

    _write_json(run_dir / "artifact_boundary.json", boundary)
    _write_git_snapshot_text(run_dir / "git_snapshot.txt", git_snapshot)
    manifest = {
        "phase": "Phase 11N",
        "status": "release_packaging_pass",
        "created_at_utc": _utc_now(),
        "repo_root": str(REPO_ROOT),
        "release_dir": str(run_dir),
        "phase11m_evidence_dir": str(evidence_dir),
        "git": {
            "branch": git_snapshot["branch"],
            "head": git_snapshot["head"],
            "head_short": git_snapshot["head_short"],
            "status_clean": git_snapshot["status_clean"],
            "status_entry_count": git_snapshot["status_entry_count"],
            "tracked_file_count": git_snapshot["tracked_file_count"],
        },
        "artifact_boundary": {
            "source_file_count": len(source_files),
            "evidence_file_count": len(evidence_files),
            "secret_file_boundary_verified": boundary["secret_file_boundary_verified"],
            "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        },
        "phase11m_evidence_validation": validation,
        "regression_passed": regression_passed if args.run_regressions else None,
        "package": {
            "zip_name": None,
            "zip_sha256": None,
            "zip_size_bytes": None,
        },
        "result": "passed",
    }
    _write_json(run_dir / "manifest.json", manifest)

    checksums = _write_checksums(run_dir / "checksums_sha256.txt", run_dir)
    package_path = run_dir / f"{args.package_prefix}_{run_dir.name}.zip"
    _create_zip(run_dir, package_path)
    package_sha = _sha256_file(package_path)
    (run_dir / "package.sha256").write_text(f"{package_sha}  {package_path.name}\n", encoding="utf-8")
    manifest["package"] = {
        "zip_name": package_path.name,
        "zip_sha256": package_sha,
        "zip_size_bytes": package_path.stat().st_size,
        "checksummed_file_count": len(checksums),
    }
    _write_json(run_dir / "manifest.json", manifest)

    errors: list[str] = []
    if not validation["passed"]:
        errors.append("Phase 11M evidence validation failed")
    if args.require_clean_git and not git_snapshot["status_clean"]:
        errors.append("git working tree is not clean")
    if args.run_regressions and not regression_passed:
        errors.append("regression checks failed")
    if any(".env" in item["path"].lower() for item in source_files + evidence_files):
        errors.append("secret-like .env file included in package")

    if errors:
        manifest["status"] = "release_packaging_failed"
        manifest["result"] = "failed"
        manifest["errors"] = errors
        _write_json(run_dir / "manifest.json", manifest)
        print("Phase 11N Release Packaging Failed — " + "; ".join(errors))
        print(f"release_dir={run_dir}")
        return 1

    print("Phase 11N Release Packaging Pass — git snapshot, artifact boundary, and release package generated.")
    print(f"release_dir={run_dir}")
    print(f"package={package_path}")
    print(f"package_sha256={package_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
