# Walkthrough - Phase 12C-YOLOv9-SRC-V Source Adapter No-Fallback Verification

1. Preserve Phase 12C-DUMMY as the only runtime-confirmed perception backend slice.
2. Preserve Phase 12C-YOLOv9-U and Phase 12C-YOLOv9-B as historical dependency/adapter preparation.
3. Preserve Phase 12C-YOLOv9-SRC as the official external source adapter and no-fallback gate preparation.
4. Record Phase 12C-YOLOv9-SRC-V as the verified no-fallback source adapter gate in CARLA Python 3.12.
5. Keep Phase 12C-YOLOv9-RUNTIME as a future phase only.
6. Do not commit YOLOv9 source.
7. Do not commit YOLOv9 weights.
8. Do not vendor YOLOv9 into this repository.
9. Verify source entries: `detect.py`, `detect_dual.py`, `models/`, `utils/`.
10. Verify `workers.core.edge_perception --test yolov9` in the target CARLA Python runtime.
11. Require no fallback for strict source-adapter pass.
12. Refresh Phase 12C YOLOv9 rows using source-adapter readiness.
13. Do not auto-install packages from MA-VLNA scripts.
14. Do not modify baseline requirements.
15. Do not start CARLA.
16. Do not execute YOLOv9 route runtime confirmation.

Generated evidence:

```text
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
```

YOLOv9-SRC-V result:

```text
source_adapter_verified=true
require_verified_requested=true
strict_gate_exit_code=0
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
post_unlock_verified=true
unlock_mode=external_source
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
runtime_confirmation_executed=false
carla_route_runtime_executed=false
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
```

Manual operator setup, not committed:

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r "$env:YOLOV9_ROOT\requirements.txt"
```

Strict source-adapter command:

```powershell
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified
```

Post-unlock strict command:

```powershell
python scripts\run_phase12c_yolov9_post_unlock_verification.py --unlock-mode external_source --output-dir experiments\phase12 --require-verified
```

Refresh Phase 12C YOLOv9 rows:

```powershell
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --output-dir experiments\phase12
```

Boundary fields:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Validation checklist:

```text
python -m py_compile workers\core\edge_perception.py scripts\run_phase12c_yolov9_source_adapter_verification.py scripts\run_phase12c_yolov9_post_unlock_verification.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py
D:\CARLA\envs\ma-vlna-carla312\python.exe -m py_compile workers\core\edge_perception.py scripts\run_phase12c_yolov9_source_adapter_verification.py scripts\run_phase12c_yolov9_post_unlock_verification.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11_carla_checks.py
git diff --check
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12C-YOLOv9-SRC-V is not a YOLOv9 CARLA route runtime pass. It means the official external source adapter verifies no-fallback readiness in the dedicated CARLA Python 3.12 runtime, and Phase 12C YOLOv9 rows are scaffold command-ready. It makes no YOLOv9 accuracy, RT-DETR runtime, CARLA Leaderboard, formal route benchmark, or infraction benchmark claim.
