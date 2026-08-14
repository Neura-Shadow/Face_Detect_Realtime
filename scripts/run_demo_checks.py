import subprocess
import sys
import logging
import time
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("ReleaseVerifier")

def run_test(name: str, cmd: list[str], expected_strings: list[str]) -> bool:
    logger.info(f"========== 執行檢查: {name} ==========")
    logger.info(f"指令: {' '.join(cmd)}")
    
    start_time = time.time()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env
        )
    except Exception as e:
        logger.error(f"❌ 啟動失敗: {e}")
        return False
        
    elapsed = time.time() - start_time
    output = result.stdout + "\n" + result.stderr
    
    if result.returncode != 0:
        logger.error(f"❌ '{name}' 異常退出 (Exit code: {result.returncode})")
        logger.error(f"最後 20 行輸出:\n{chr(10).join(output.splitlines()[-20:])}")
        return False
        
    missing_strings = []
    for expected in expected_strings:
        if expected not in output:
            missing_strings.append(expected)
            
    if missing_strings:
        logger.error(f"❌ '{name}' 失敗！找不到預期字串:")
        for ms in missing_strings:
            logger.error(f"   - {ms}")
        logger.error(f"最後 20 行輸出:\n{chr(10).join(output.splitlines()[-20:])}")
        return False
        
    logger.info(f"✅ '{name}' 通過！ (耗時: {elapsed:.2f}s)")
    return True

def main() -> int:
    logger.info("開始執行 MA-VLNA v0.5 Release Verification...")
    
    tests = [
        {
            "name": "1. 核心模組語法檢查 (py_compile)",
            "cmd": [
                sys.executable, "-m", "py_compile",
                "workers/Autonomous_Driving_Agent.py",
                "workers/core/vlm_reasoner.py",
                "workers/core/safety_gate.py",
                "workers/core/trigger_policy.py",
                "workers/core/config.py",
                "workers/core/telemetry_publisher.py",
                "workers/core/carla_adapter.py",
                "workers/CARLA_Closed_Loop_Agent.py"
            ],
            "expected": []
        },
        {
            "name": "2. VLM Reasoner 單元測試 (local_stub)",
            "cmd": [sys.executable, "-m", "workers.core.vlm_reasoner", "--test", "local_stub"],
            "expected": []
        },
        {
            "name": "3. VLM Reasoner 單元測試 (openai_compatible)",
            "cmd": [sys.executable, "-m", "workers.core.vlm_reasoner", "--test", "openai_compatible"],
            "expected": []
        },
        {
            "name": "4. Edge Perception 單元測試 (dummy)",
            "cmd": [sys.executable, "-m", "workers.core.edge_perception", "--test", "dummy"],
            "expected": []
        },
        {
            "name": "5. Agent 10 步 Mock Mode (預設 LocalStub)",
            "cmd": [
                sys.executable, "-m", "workers.Autonomous_Driving_Agent",
                "--mode", "mock",
                "--steps", "10"
            ],
            "expected": ["10"]
        },
        {
            "name": "6. Agent 30 步 Mock Mode + 強制 VLM 觸發",
            "cmd": [
                sys.executable, "-m", "workers.Autonomous_Driving_Agent",
                "--mode", "mock",
                "--steps", "30",
                "--force-vlm-every", "10"
            ],
            "expected": [
                "LocalStub VLM",
                "reason=force_interval",
                "30"
            ]
        }
    ]
    
    passed_count = 0
    for test in tests:
        success = run_test(test["name"], test["cmd"], test["expected"])
        if success:
            passed_count += 1
        else:
            # If a critical check fails, we might want to continue to see all failures,
            # but usually we just collect the counts.
            pass
            
    logger.info("========================================")
    logger.info(f"驗證總結: {passed_count}/{len(tests)} 測試通過")
    
    if passed_count == len(tests):
        logger.info("🎉 所有 Release Checks 測試成功！v0.5 版本準備就緒！")
        return 0
    else:
        logger.error("💥 部分測試失敗，請檢查日誌。")
        return 1

if __name__ == "__main__":
    sys.exit(main())
