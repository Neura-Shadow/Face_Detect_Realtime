"""Phase 13G Gate B: build and validate real releases on the Jetson, activate nothing.

Gate B proves the parts of an update that can be proved without risking the
running service: that a release can be built from a commit, installed
immutably, hashed, and checked against the actual machine — and that a
candidate which fails any check is refused.

The safety property this gate rests on is that **production authority does not
move**. The installed Phase 13F unit runs the node from the git checkout, not
from ``/opt/ma-vlna/current``, so populating the release store cannot affect
what is running. That is asserted here rather than assumed: the service's PID
and state are recorded before and after, and the unit's ExecStart is inspected
to confirm it still points at the checkout.

Negative cases are run against the real target too, because a compatibility
check that only rejects things in a unit test is not a check.

Runtime compatibility: PC-side Python 3.10+; everything on the Jetson runs under
its own 3.8.10 venv.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13d_checks import new_run_id, pc_git_sha, run_command_utf8, utc_now_iso  # noqa: E402

PHASE = "13G-OTA-A-B-ROLLBACK-VERSION-COMPATIBILITY"
STATUS_STAGING_PASS = "Staging Pass"
STATUS_BLOCKED = "Blocked"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]


class Jetson:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.target = "%s@%s" % (args.jetson_user, args.jetson_host)

    def ssh(self, remote: str, *, timeout: int = 600) -> Dict[str, Any]:
        return run_command_utf8(["ssh"] + SSH_OPTS + [self.target, remote], timeout=timeout)

    def venv(self, command: str, *, timeout: int = 600) -> Dict[str, Any]:
        return self.ssh(
            "cd %s && source %s/bin/activate && %s"
            % (shlex.quote(self.args.jetson_repo), shlex.quote(self.args.jetson_venv), command),
            timeout=timeout,
        )

    def json_venv(self, command: str, *, timeout: int = 600) -> Dict[str, Any]:
        result = self.venv(command, timeout=timeout)
        text = (result.get("stdout") or "").strip()
        start = text.find("{")
        if start >= 0:
            try:
                return json.loads(text[start:])
            except ValueError:
                pass
        return {
            "ok": False,
            "error": "unparsable output",
            "returncode": result["returncode"],
            "stdout_tail": text[-400:],
            "stderr_tail": (result.get("stderr") or "")[-400:],
        }

    def deploy(self, operation: str, extra: str = "", *, timeout: int = 900) -> Dict[str, Any]:
        return self.json_venv(
            "python scripts/run_phase13g_deploy.py %s --root %s --unit %s"
            " --skip-service-status %s"
            % (operation, shlex.quote(self.args.release_root), shlex.quote(self.args.unit), extra),
            timeout=timeout,
        )

    def service_snapshot(self) -> Dict[str, Any]:
        result = self.ssh(
            "systemctl show %s --no-pager -p ActiveState -p SubState -p MainPID"
            " -p NRestarts -p ExecStart -p WorkingDirectory" % shlex.quote(self.args.unit),
            timeout=120,
        )
        payload = {}  # type: Dict[str, Any]
        for line in (result.get("stdout") or "").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                payload[key.strip()] = value.strip()
        return payload


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13G Gate B staging")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--jetson-user", default="myjetsonnx")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--jetson-repo", default="/home/myjetsonnx/Face_Detect_Realtime")
    parser.add_argument("--jetson-venv", default="/home/myjetsonnx/venvs/ma-vlna")
    parser.add_argument("--release-root", default="/opt/ma-vlna")
    parser.add_argument("--package-dir", default="/home/myjetsonnx/ma-vlna-packages")
    parser.add_argument("--unit", default="ma-vlna-jetson-node.service")
    parser.add_argument("--release-a", default="")
    parser.add_argument("--release-b", default="")
    parser.add_argument("--output-dir", default="experiments/phase13")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or ("%s-13g-gateb" % new_run_id())
    jetson = Jetson(args)

    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / args.output_dir
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    release_a = args.release_a or "relA-%s" % stamp
    release_b = args.release_b or "relB-%s" % stamp

    summary = {
        "phase": PHASE,
        "gate": "B",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "runtime_pc_git_sha": pc_git_sha(),
        "release_a_id": release_a,
        "release_b_id": release_b,
        # The boundary, restated where it could be misread.
        "integrity_only": True,
        "signed": False,
        "secure_boot": False,
        "bootloader_ab": False,
        "rootfs_ota": False,
        "anti_rollback_security": False,
        "production_authority_switched": False,
        "sudo_executed": False,
        "etc_modified": False,
        "reboot_performed": False,
    }  # type: Dict[str, Any]

    blockers = []  # type: List[str]

    sha = jetson.ssh("cd %s && git rev-parse HEAD" % shlex.quote(args.jetson_repo), timeout=120)
    jetson_sha = ""
    for line in (sha.get("stdout") or "").splitlines():
        if len(line.strip()) == 40:
            jetson_sha = line.strip()
    summary["runtime_jetson_git_sha"] = jetson_sha
    summary["runtime_git_sha_match"] = jetson_sha == summary["runtime_pc_git_sha"]
    if not summary["runtime_git_sha_match"]:
        summary["status"] = STATUS_BLOCKED
        summary["blockers"] = ["runtime_git_sha_mismatch"]
        (run_dir / "gate_b_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("%s Blocked: Jetson %s vs PC %s" % (PHASE, jetson_sha, summary["runtime_pc_git_sha"]))
        return 1

    print("%s Gate B run_id=%s" % (PHASE, run_id))
    summary["service_before"] = jetson.service_snapshot()
    print("  service before: %s/%s pid=%s" % (
        summary["service_before"].get("ActiveState"),
        summary["service_before"].get("SubState"),
        summary["service_before"].get("MainPID")))

    for label, release_id in (("a", release_a), ("b", release_b)):
        print("  packaging release %s (%s)" % (label.upper(), release_id))
        package = jetson.json_venv(
            "python scripts/run_phase13g_package.py --release-id %s --output-dir %s"
            % (shlex.quote(release_id), shlex.quote(args.package_dir)),
            timeout=900,
        )
        summary["package_%s" % label] = package
        if not package.get("ok"):
            blockers.append("package_%s_failed" % label)
            print("    packaging FAILED: %s" % package.get("error"))
            continue
        print("    package_sha256=%s bytes=%s files=%s" % (
            package.get("package_sha256", "")[:16], package.get("package_bytes"),
            (package.get("payload") or {}).get("files_packaged")))

        staged = jetson.deploy(
            "stage",
            "--package %s --manifest %s"
            % (shlex.quote(package["package_path"]), shlex.quote(package["manifest_path"])),
        )
        summary["stage_%s" % label] = staged
        if not staged.get("ok"):
            blockers.append("stage_%s_failed" % label)
            print("    stage FAILED: %s" % staged.get("classification"))
            continue

        validated = jetson.deploy(
            "validate", "--release-id %s --expected-source-sha %s"
            % (shlex.quote(release_id), jetson_sha),
        )
        summary["validate_%s" % label] = validated
        if not validated.get("ok"):
            blockers.append("validate_%s_failed" % label)
            print("    validation FAILED: %s"
                  % (validated.get("compatibility") or {}).get("failed_checks"))
        else:
            checks = (validated.get("compatibility") or {}).get("checks", [])
            print("    validated: %d compatibility checks, 0 failures" % len(checks))

    # Make A the store baseline. The installed Phase 13F unit still runs the
    # node from the git checkout, so this changes nothing about what is
    # running; Gate C is where authority moves to a release.
    baseline = jetson.venv(
        "python -c \"import sys; sys.path.insert(0,'.');"
        "from workers.core.release_store import ReleaseStore, CURRENT_LINK, LAST_KNOWN_GOOD_LINK;"
        "s=ReleaseStore('%s');"
        "s.set_link_atomic(CURRENT_LINK,'%s');"
        "s.set_link_atomic(LAST_KNOWN_GOOD_LINK,'%s');"
        "print('baseline set')\""
        % (args.release_root, release_a, release_a),
        timeout=300,
    )
    summary["baseline_links_returncode"] = baseline["returncode"]
    if baseline["returncode"] != 0:
        blockers.append("baseline_link_failed")
        summary["baseline_stderr"] = (baseline.get("stderr") or "")[-400:]

    status = jetson.deploy("status")
    summary["store_status"] = status
    store = status.get("store", {})
    print("  store: current=%s previous=%s last-known-good=%s releases=%s partial=%s" % (
        store.get("current_release_id"), store.get("previous_release_id"),
        store.get("last_known_good_release_id"), store.get("release_count"),
        store.get("partial_release_count")))

    negatives = {}  # type: Dict[str, Any]
    package_b = summary.get("package_b") or {}
    if package_b.get("ok"):
        manifest_b = package_b["manifest_path"]
        package_path = package_b["package_path"]

        corrupt = "%s.corrupt" % package_path
        jetson.ssh("cp %s %s && printf 'tampered' >> %s"
                   % (shlex.quote(package_path), shlex.quote(corrupt), shlex.quote(corrupt)),
                   timeout=300)
        negatives["package_hash_mismatch"] = jetson.deploy(
            "stage", "--package %s --manifest %s" % (shlex.quote(corrupt), shlex.quote(manifest_b))
        )
        jetson.ssh("rm -f %s" % shlex.quote(corrupt), timeout=120)

        bad_engine = "%s.badengine.json" % manifest_b
        jetson.venv(
            "python -c \"import json;d=json.load(open('%s'));"
            "d['engine_sha256']='%s';d['release_id']='badengine-%s';"
            "json.dump(d,open('%s','w'))\""
            % (manifest_b, "d" * 64, stamp, bad_engine),
            timeout=180,
        )
        staged_bad_engine = jetson.deploy(
            "stage", "--package %s --manifest %s"
            % (shlex.quote(package_path), shlex.quote(bad_engine))
        )
        if staged_bad_engine.get("ok"):
            negatives["engine_hash_mismatch"] = jetson.deploy(
                "validate", "--release-id badengine-%s" % stamp
            )
        else:
            negatives["engine_hash_mismatch"] = staged_bad_engine

        bad_int8 = "%s.int8.json" % manifest_b
        jetson.venv(
            "python -c \"import json;d=json.load(open('%s'));"
            "d['int8_authority_allowed']=True;d['release_id']='int8-%s';"
            "json.dump(d,open('%s','w'))\"" % (manifest_b, stamp, bad_int8),
            timeout=180,
        )
        negatives["int8_authority_requested"] = jetson.deploy(
            "stage", "--package %s --manifest %s"
            % (shlex.quote(package_path), shlex.quote(bad_int8))
        )

        bad_proto = "%s.proto.json" % manifest_b
        jetson.venv(
            "python -c \"import json;d=json.load(open('%s'));"
            "d['command_packet_size']=32;d['release_id']='proto-%s';"
            "json.dump(d,open('%s','w'))\"" % (manifest_b, stamp, bad_proto),
            timeout=180,
        )
        staged_proto = jetson.deploy(
            "stage", "--package %s --manifest %s"
            % (shlex.quote(package_path), shlex.quote(bad_proto))
        )
        if staged_proto.get("ok"):
            negatives["protocol_mismatch"] = jetson.deploy(
                "validate", "--release-id proto-%s" % stamp
            )
        else:
            negatives["protocol_mismatch"] = staged_proto

        bad_sha = "%s.sha.json" % manifest_b
        jetson.venv(
            "python -c \"import json;d=json.load(open('%s'));"
            "d['source_git_sha']='%s';d['release_id']='badsha-%s';"
            "json.dump(d,open('%s','w'))\"" % (manifest_b, "f" * 40, stamp, bad_sha),
            timeout=180,
        )
        staged_sha = jetson.deploy(
            "stage", "--package %s --manifest %s"
            % (shlex.quote(package_path), shlex.quote(bad_sha))
        )
        if staged_sha.get("ok"):
            negatives["source_sha_mismatch"] = jetson.deploy(
                "validate", "--release-id badsha-%s --expected-source-sha %s" % (stamp, jetson_sha)
            )
        else:
            negatives["source_sha_mismatch"] = staged_sha

        jetson.ssh(
            "rm -f %s %s %s %s" % (shlex.quote(bad_engine), shlex.quote(bad_int8),
                                   shlex.quote(bad_proto), shlex.quote(bad_sha)),
            timeout=120,
        )

    summary["negative_cases"] = negatives
    for name, result in negatives.items():
        rejected = not result.get("ok")
        detail = result.get("classification") or (
            (result.get("compatibility") or {}).get("failed_checks")
        )
        print("  negative %-26s rejected=%-5s (%s)" % (name, rejected, detail))
        if not rejected:
            blockers.append("negative_case_accepted_%s" % name)

    summary["service_after"] = jetson.service_snapshot()
    before, after = summary["service_before"], summary["service_after"]
    unchanged = (
        before.get("MainPID") == after.get("MainPID")
        and after.get("ActiveState") == "active"
        and before.get("ExecStart") == after.get("ExecStart")
    )
    summary["production_service_unchanged"] = unchanged
    summary["production_runs_from_release_store"] = args.release_root in str(
        after.get("WorkingDirectory", "")
    )
    print("  service after: %s/%s pid=%s unchanged=%s runs_from_release=%s" % (
        after.get("ActiveState"), after.get("SubState"), after.get("MainPID"),
        unchanged, summary["production_runs_from_release_store"]))
    if not unchanged:
        blockers.append("production_service_changed_during_staging")
    if summary["production_runs_from_release_store"]:
        blockers.append("production_authority_switched_during_staging")

    store = (summary.get("store_status") or {}).get("store", {})
    if store.get("current_release_id") != release_a:
        blockers.append("store_current_is_not_release_a")
    if int(store.get("partial_release_count", 0) or 0):
        blockers.append("partial_release_present")
    if release_b not in (store.get("installed_releases") or []):
        blockers.append("candidate_b_not_installed")

    summary["blockers"] = sorted(set(blockers))
    summary["status"] = STATUS_STAGING_PASS if not summary["blockers"] else STATUS_BLOCKED
    (run_dir / "gate_b_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    print("")
    print("%s %s" % (PHASE, summary["status"]))
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % run_dir)
    print("release_a=%s release_b=%s" % (release_a, release_b))
    print("production_authority_switched=%s" % summary["production_authority_switched"])
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]))
    return 0 if not summary["blockers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
