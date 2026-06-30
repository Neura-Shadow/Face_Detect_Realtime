# Walkthrough - Phase 12C-YOLOv9-SRC-V Source Adapter No-Fallback Verification

1. Preserve Phase 12C-DUMMY as the only runtime-confirmed perception backend slice.
2. Preserve Phase 12C-YOLOv9-U and Phase 12C-YOLOv9-B as historical dependency/adapter preparation.
3. Add an official YOLOv9 external source adapter for `perception_backend=yolov9`.
4. Require operator-provided `YOLOV9_ROOT` and `YOLOV9_WEIGHTS`.
5. Do not commit YOLOv9 source.
6. Do not commit YOLOv9 weights.
7. Do not vendor YOLOv9 into this repository.
8. Verify source entries: `detect.py`, `detect_dual.py`, `models/`, `utils/`.
9. Verify `workers.core.edge_perception --test yolov9` in the target CARLA Python runtime.
10. Require no fallback for strict source-adapter pass.
11. Refresh Phase 12C YOLOv9 rows using source-adapter readiness.
12. Do not auto-install packages.
13. Do not modify baseline requirements.
14. Do not start CARLA.
15. Do not execute YOLOv9 route runtime confirmation.

Generated evidence:

```text
yolov9_source_adapter_verification=experiments\phase12\20260629T134856Z
yolov9_post_unlock_external_source=experiments\phase12\20260629T134856Z-1
yolov9_rows_refresh=experiments\phase12\20260629T134856Z-1-2
yolov9_source_adapter_strict_no_fallback=experiments\phase12\20260630T040313Z
yolov9_strict_rows_refresh=experiments\phase12\20260630T040317Z
```

YOLOv9-SRC result:

```text
source_adapter_verified=false
require_verified_requested=true
strict_gate_exit_code=1
yolov9_source_root_configured=false
yolov9_weights_configured=false
yolov9_source_root_ready=false
yolov9_weights_ready=false
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=true
edge_yolov9_no_fallback_verified=false
runtime_confirmation_executed=false
```

Manual operator setup:

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r "$env:YOLOV9_ROOT\requirements.txt"
```

Strict source-adapter command:

```powershell
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified
```

Refresh Phase 12C YOLOv9 rows:

```powershell
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --output-dir experiments\phase12
```

Pass condition:

```text
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
source_adapter_verified=true
```

Boundary fields:

```text
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
runtime_confirmation_executed=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Validation checklist:

```text
python -m py_compile workers\core\edge_perception.py scripts\run_phase12c_yolov9_source_adapter_verification.py scripts\run_phase12c_yolov9_post_unlock_verification.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase11_carla_checks.py
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12C-YOLOv9-SRC prepared evidence is not a YOLOv9 route runtime pass. It means the official source adapter contract and no-fallback gate now exist; local no-fallback verification remains blocked until the operator provides source and weights.
