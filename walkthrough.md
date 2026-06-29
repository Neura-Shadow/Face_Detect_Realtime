# Walkthrough - Phase 12C-YOLOv9-V YOLOv9 Post-Unlock Verification

1. Preserve Phase 12C-DUMMY as the only runtime-confirmed perception backend slice.
2. Preserve Phase 12C-YOLOv9-U as manual dependency unlock preparation.
3. Preserve Phase 12C-YOLOv9-B as adapter-path preparation.
4. Add a strict post-unlock verifier for `perception_backend=yolov9`.
5. Verify `yolov9` import inside `D:\CARLA\envs\ma-vlna-carla312`.
6. Verify `pip show yolov9` inside the same target runtime.
7. Verify `workers.core.edge_perception --test yolov9` exits successfully without fallback.
8. Verify Phase 12B / Phase 11M / Phase 11K / baseline mapper CLIs accept `--perception-backend yolov9`.
9. Refresh Phase 12C YOLOv9 rows using the target Python dependency probe.
10. Do not auto-install packages.
11. Do not modify baseline requirements.
12. Do not start CARLA.
13. Do not execute YOLOv9 route runtime confirmation.

Generated evidence:

```text
yolov9_post_unlock_verification=experiments\phase12\20260629T124925Z
yolov9_rows_refresh=experiments\phase12\20260629T124940Z
phase12c_matrix=experiments\phase12\20260629T070603Z
```

YOLOv9-V result:

```text
post_unlock_verified=false
require_verified_requested=true
strict_gate_exit_code=1
yolov9_import_ready=false
yolov9_pip_metadata_ready=false
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=true
edge_yolov9_no_fallback_verified=false
phase12b_yolov9_dry_run_command_ready=true
phase11m_yolov9_cli_ready=true
phase11k_yolov9_cli_ready=true
phase12b_baseline_yolov9_cli_ready=true
phase12c_yolov9_rows_available=false
phase12c_yolov9_backend_unavailable_count=5
```

Strict post-unlock command:

```powershell
python scripts\run_phase12c_yolov9_post_unlock_verification.py --output-dir experiments\phase12 --require-verified
```

Current local result with `--require-verified` should remain nonzero until the selected YOLOv9 dependency is installed in the CARLA Python 3.12 runtime.

Pass condition:

```text
yolov9_import_ready=true
yolov9_pip_metadata_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
phase12c_yolov9_rows_available=true
post_unlock_verified=true
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
python -m py_compile scripts\run_phase12c_yolov9_post_unlock_verification.py scripts\run_phase12c_perception_backend_ablation.py scripts\run_phase12b_controller_ablation_experiment.py scripts\run_phase11m_grp_route_following.py scripts\run_phase11k_fixed_route_smoke.py scripts\run_phase12b_baseline_mapper_route_metrics.py scripts\run_phase11_carla_checks.py
python scripts\run_phase12c_yolov9_post_unlock_verification.py --output-dir experiments\phase12 --require-verified
python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12C-YOLOv9-V blocked evidence is not a failure of the adapter path. It means the environment has not actually been unlocked with a YOLOv9 dependency yet.
