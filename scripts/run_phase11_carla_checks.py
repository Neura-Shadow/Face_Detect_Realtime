"""
Phase 11 CARLA closed-loop smoke checks.

這些檢查不需要 CARLA server，也不要求安裝 carla Python wheel。
目的在於驗證 optional CARLA 整合不會破壞 v0.5 mock/demo 路徑，
且 PlannerAction -> CARLA VehicleControl mapping 可在 CI/本機離線驗證。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("Phase11Verifier")


def run_check(name: str, cmd: list[str], expected: list[str] | None = None) -> bool:
    logger.info("========== Phase 11 檢查: %s ==========", name)
    logger.info("指令: %s", " ".join(cmd))
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    start = time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    output = result.stdout + "\n" + result.stderr
    if result.returncode != 0:
        logger.error("FAILED: %s (exit=%d)", name, result.returncode)
        logger.error("最後 30 行輸出:\n%s", "\n".join(output.splitlines()[-30:]))
        return False
    for text in expected or []:
        if text not in output:
            logger.error("FAILED: %s missing expected text: %s", name, text)
            logger.error("最後 30 行輸出:\n%s", "\n".join(output.splitlines()[-30:]))
            return False
    logger.info("PASSED: %s (%.2fs)", name, time.time() - start)
    return True


def main() -> int:
    checks = [
        {
            "name": "CARLA 模組語法檢查",
            "cmd": [
                sys.executable,
                "-m",
                "py_compile",
                "workers/core/config.py",
                "workers/core/carla_metrics.py",
                "workers/core/carla_route_metrics.py",
                "workers/core/carla_adapter.py",
                "workers/CARLA_Closed_Loop_Agent.py",
                "scripts/run_phase11d_carla_provisioning_gate.py",
                "scripts/run_phase11j_carla_sensor_metrics.py",
                "scripts/run_phase11k_fixed_route_smoke.py",
                "scripts/run_phase11l_fixed_route_completion.py",
                "scripts/run_phase11m_grp_route_following.py",
                "scripts/run_phase11n_release_packaging.py",
                "scripts/run_phase11o_source_commit_checks.py",
                "scripts/run_phase12b_baseline_mapper_route_metrics.py",
                "scripts/run_phase12b_controller_ablation_experiment.py",
                "scripts/run_phase12b_controller_ablation_summary.py",
                "scripts/run_phase12c_perception_backend_ablation.py",
                "scripts/run_phase12c_dummy_runtime_confirmation.py",
                "scripts/run_phase12c_yolo_optional_dependency_unlock.py",
                "scripts/run_phase12c_yolov9_optional_dependency_unlock.py",
                "scripts/run_phase12c_yolov9_backend_adapter_checks.py",
                "scripts/run_phase12c_yolov9_source_adapter_verification.py",
                "scripts/run_phase12c_yolov9_post_unlock_verification.py",
                "scripts/run_phase12c_yolov9_runtime_confirmation.py",
                "scripts/run_phase12c_yolov9_runtime_timeout_diagnosis.py",
            ],
            "expected": [],
        },
        {
            "name": "CARLA control mapping self-test",
            "cmd": [
                sys.executable,
                "-m",
                "workers.core.carla_adapter",
                "--self-test-control",
            ],
            "expected": ["CARLA control mapping self-test passed"],
        },
        {
            "name": "AgentConfig CARLA 設定載入",
            "cmd": [
                sys.executable,
                "-c",
                (
                    "from workers.core.config import AgentConfig; "
                    "cfg=AgentConfig.load(); "
                    "assert cfg.carla.host; "
                    "assert cfg.carla.camera_width > 0; "
                    "print('carla config load passed')"
                ),
            ],
            "expected": ["carla config load passed"],
        },
        {
            "name": "CARLA runner import smoke",
            "cmd": [
                sys.executable,
                "-c",
                (
                    "from workers.CARLA_Closed_Loop_Agent import CarlaClosedLoopAgent; "
                    "from workers.core.carla_adapter import CarlaClientAdapter; "
                    "print('carla runner import passed')"
                ),
            ],
            "expected": ["carla runner import passed"],
        },
        {
            "name": "CARLA core runtime verification (fake CARLA closed-loop)",
            "cmd": [
                sys.executable,
                "scripts/run_phase11_core_runtime_checks.py",
            ],
            "expected": ["phase11 core runtime verification passed"],
        },
        {
            "name": "CARLA runtime provisioning gate (read-only)",
            "cmd": [
                sys.executable,
                "scripts/run_phase11d_carla_provisioning_gate.py",
            ],
            "expected": ["phase11d carla provisioning gate"],
        },
    ]

    passed = 0
    for check in checks:
        if run_check(check["name"], check["cmd"], check["expected"]):
            passed += 1

    logger.info("Phase 11 驗證總結: %d/%d passed", passed, len(checks))
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
