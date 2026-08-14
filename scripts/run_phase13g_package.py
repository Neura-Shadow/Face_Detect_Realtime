"""Phase 13G release packager: turn a commit into an immutable release.

A package contains only repository-owned runtime files. Engines and model
weights are **referenced by validated path**, never copied: the FP16 engine is
52 MB, it is identical across releases, and duplicating it per release would
turn a 2 MB update into a 54 MB one while adding a second copy that can drift
from the one the manifest hashes.

The package hash is computed over the finished tarball and recorded in the
manifest, which is stored alongside it rather than inside it — a file cannot
contain its own hash.

This provides integrity, not authenticity. Anyone who can write the package can
write the manifest beside it. Signing is Phase 13H.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.release_manifest import (  # noqa: E402
    ReleaseManifest,
    build_release_manifest,
    describe_schema,
    scan_for_secrets,
    sha256_file,
    target_facts,
)

PHASE = "13G-OTA-A-B-ROLLBACK-VERSION-COMPATIBILITY"

#: Repository-owned runtime content. Everything the service needs to run and
#: nothing else -- no tests, no docs, no git metadata, no evidence.
PACKAGE_INCLUDE = (
    "scripts",
    "workers",
    "simulation",
    "config",
    "deployment",
    "embedded",
)

#: Excluded wherever they appear inside the included trees.
PACKAGE_EXCLUDE_DIRS = frozenset({
    "__pycache__", ".git", ".pytest_cache", "tests", "experiments",
    "node_modules", ".idea", "test_env",
})
PACKAGE_EXCLUDE_SUFFIXES = (
    ".pyc", ".pyo", ".engine", ".onnx", ".plan", ".pth", ".weights",
    ".log", ".jsonl", ".env",
)

#: Generated, host-specific files that must never travel inside a release.
#:
#: ``phase13f_service_manifest.json`` is the Phase 13F startup manifest. It is
#: generated on the target and pins an absolute engine path and the commit the
#: *service* was built for, which is why it is gitignored rather than committed.
#: Packaging it put a copy pinning ``dabbbaba`` (the frozen Phase 13F runtime)
#: inside a release whose own ``source_git_sha`` was a later commit -- two
#: contradictory answers to "which commit is this?" in the same directory.
#:
#: The release manifest already does the right thing with it: records
#: ``engine_manifest_path`` and ``engine_manifest_sha256`` and references it as
#: an external asset, exactly as it does the engine. So it is referenced, not
#: copied.
#:
#: ``release.manifest.json`` is written *beside* the package and installed at the
#: release root. A package cannot contain a file whose value includes the
#: package's own hash.
PACKAGE_EXCLUDE_NAMES = frozenset({
    "phase13f_service_manifest.json",
    "release.manifest.json",
})


def git_sha(repo_root: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.decode("utf-8", "replace").strip() if completed.returncode == 0 else ""


def worktree_provenance(repo_root: str) -> Dict[str, Any]:
    """Whether the package this tree produces will match ``source_git_sha``.

    The question is not "is the worktree pristine" but "will the bytes we ship
    be the bytes of that commit". Those differ:

    * A **modified tracked file** breaks provenance wherever it is: the commit
      no longer describes the tree.
    * An **untracked file inside a packaged tree** breaks it too, because the
      packager copies whole directories and would ship a file the commit does
      not contain.
    * An untracked file **outside** the packaged trees changes nothing that
      ships. Build leftovers, editor droppings and CTest output live there, and
      a real target always has some. Refusing on those makes the check
      superstition rather than provenance -- Gate B was blocked by a stray
      ``Testing/`` directory that could not reach a package.

    All three are reported either way, so the distinction is visible rather
    than implicit in a boolean.
    """

    report = {
        "tracked_modifications": [],
        "untracked_in_package": [],
        "untracked_outside_package": [],
        "clean_for_packaging": False,
    }  # type: Dict[str, Any]
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo_root,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        return report
    if completed.returncode != 0:
        report["error"] = completed.stderr.decode("utf-8", "replace").strip()[-200:]
        return report

    for line in completed.stdout.decode("utf-8", "replace").splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:].strip().strip('"')
        top = path.split("/", 1)[0]
        if status == "??":
            if top in PACKAGE_INCLUDE:
                report["untracked_in_package"].append(path)
            else:
                report["untracked_outside_package"].append(path)
        else:
            report["tracked_modifications"].append({"status": status.strip(), "path": path})

    report["clean_for_packaging"] = not (
        report["tracked_modifications"] or report["untracked_in_package"]
    )
    return report


def collect_payload(repo_root: str, destination: str) -> Dict[str, Any]:
    """Copy the runtime tree into ``destination``, excluding what must not ship."""

    import shutil

    copied = 0
    skipped_dirs = 0
    skipped_files = 0
    for top in PACKAGE_INCLUDE:
        source_top = os.path.join(repo_root, top)
        if not os.path.isdir(source_top):
            continue
        for base, dirs, files in os.walk(source_top):
            pruned = [name for name in dirs if name in PACKAGE_EXCLUDE_DIRS]
            for name in pruned:
                dirs.remove(name)
                skipped_dirs += 1
            relative = os.path.relpath(base, repo_root)
            target_dir = os.path.join(destination, relative)
            os.makedirs(target_dir, exist_ok=True)
            for name in files:
                if name.endswith(PACKAGE_EXCLUDE_SUFFIXES) or name in PACKAGE_EXCLUDE_NAMES:
                    skipped_files += 1
                    continue
                shutil.copy2(os.path.join(base, name), os.path.join(target_dir, name))
                copied += 1
    return {
        "files_packaged": copied,
        "directories_skipped": skipped_dirs,
        "files_skipped": skipped_files,
        "included_trees": list(PACKAGE_INCLUDE),
    }


def build_package(payload_dir: str, package_path: str, release_id: str) -> Dict[str, Any]:
    """Tar and gzip the payload deterministically enough to be comparable."""

    os.makedirs(os.path.dirname(os.path.abspath(package_path)), exist_ok=True)
    with tarfile.open(package_path, "w:gz") as archive:
        # A single top-level directory named for the release, so unpacking
        # anywhere cannot scatter files.
        archive.add(payload_dir, arcname=release_id)
    return {
        "package_path": package_path,
        "package_bytes": os.path.getsize(package_path),
        "package_sha256": sha256_file(package_path),
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13G release packager")
    parser.add_argument("--release-id", default="")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", default="/home/myjetsonnx/ma-vlna-packages")
    parser.add_argument(
        "--engine",
        default="/home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1-trt852-fp16.engine",
    )
    parser.add_argument(
        "--engine-manifest", default="config/phase13f_service_manifest.json",
        help="Phase 13F startup manifest; hashed and referenced, not packaged.",
    )
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    repo_root = os.path.abspath(args.repo_root)
    sha = git_sha(repo_root)
    provenance = worktree_provenance(repo_root)
    release_id = args.release_id or "r%s-%s" % (
        time.strftime("%Y%m%d%H%M%S", time.gmtime()), (sha or "unknown")[:8]
    )

    report = {
        "phase": PHASE,
        "release_id": release_id,
        "source_git_sha": sha,
        "worktree_provenance": provenance,
        "package_matches_commit": provenance["clean_for_packaging"],
        "integrity_only": True,
        "signed": False,
        "secure_boot": False,
        "bootloader_ab": False,
        "anti_rollback_security": False,
    }  # type: Dict[str, Any]

    if not provenance["clean_for_packaging"] and not args.allow_dirty:
        report["ok"] = False
        report["error"] = (
            "worktree does not correspond to %s: %d tracked modification(s), "
            "%d untracked file(s) inside packaged trees"
            % (
                (sha or "HEAD")[:8],
                len(provenance["tracked_modifications"]),
                len(provenance["untracked_in_package"]),
            )
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2
    if not sha:
        report["ok"] = False
        report["error"] = "could not determine source_git_sha"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    engine_path = os.path.abspath(args.engine)
    if not os.path.isfile(engine_path):
        report["ok"] = False
        report["error"] = "engine not found: %s" % engine_path
        print(json.dumps(report, indent=2, sort_keys=True))
        return 3
    engine_manifest = args.engine_manifest
    if not os.path.isabs(engine_manifest):
        engine_manifest = os.path.join(repo_root, engine_manifest)
    if not os.path.isfile(engine_manifest):
        report["ok"] = False
        report["error"] = "startup manifest not found: %s" % engine_manifest
        print(json.dumps(report, indent=2, sort_keys=True))
        return 3

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    package_path = os.path.join(output_dir, "%s.tar.gz" % release_id)

    staging = tempfile.mkdtemp(prefix="phase13g-pkg-")
    try:
        payload_dir = os.path.join(staging, "payload")
        os.makedirs(payload_dir, exist_ok=True)
        report["payload"] = collect_payload(repo_root, payload_dir)

        # Refuse to ship a package containing anything credential-shaped.
        offenders = scan_for_secrets(payload_dir)
        report["secret_scan_offenders"] = offenders
        if offenders:
            report["ok"] = False
            report["error"] = "package contains credential-shaped files"
            print(json.dumps(report, indent=2, sort_keys=True))
            return 4

        report.update(build_package(payload_dir, package_path, release_id))
    finally:
        import shutil

        shutil.rmtree(staging, ignore_errors=True)

    facts = target_facts()
    manifest_payload = build_release_manifest(
        release_id=release_id,
        source_git_sha=sha,
        created_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        package_sha256=report["package_sha256"],
        engine_path=engine_path,
        engine_sha256=sha256_file(engine_path),
        engine_manifest_sha256=sha256_file(engine_manifest),
        facts=facts,
        extra={
            "engine_manifest_path": engine_manifest,
            "packaged_on_arch": facts.get("arch"),
            "packaged_on_python": facts.get("python"),
        },
    )
    # Parse what we built, so an unloadable manifest is never written.
    manifest = ReleaseManifest(manifest_payload)
    manifest_path = os.path.join(output_dir, "%s.manifest.json" % release_id)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest_payload, handle, indent=2, sort_keys=True)
        handle.write("\n")

    report["ok"] = True
    report["manifest_path"] = manifest_path
    report["manifest_sha256"] = manifest.manifest_sha256
    report["engine_path"] = engine_path
    report["engine_sha256"] = manifest.engine_sha256
    report["target_facts"] = facts
    report["schema"] = describe_schema()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
