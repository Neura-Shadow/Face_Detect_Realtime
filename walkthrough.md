# Walkthrough - Phase 12C Perception Backend Ablation Prepared

1. Use Phase 12B-SUM as the controller selection boundary.
2. Fix `controller_mode=grp_follower`.
3. Preserve the calibrated 5-route `Town03` matrix from Phase 12A-C / Phase 12B.
4. Build a 5 routes x 3 perception backend scaffold.
5. Preflight optional backend dependencies without importing CARLA.
6. Mark missing YOLO / RT-DETR dependencies as `backend_unavailable`.
7. Write `manifest.json`, `summary.csv`, `summary.json`, `commands.txt`, and `README.md`.
8. Keep generated scaffold output local and out of git.
9. Preserve all benchmark boundary fields as false.

Matrix:

```text
routes=route_01,route_02,route_03,route_04,route_05
controller_mode=grp_follower
perception_backend_modes=dummy,yolo_optional,rt_detr_optional
```

Generated summary:

```text
experiments\phase12\20260628T170342Z
row_count=15
available_row_count=5
backend_unavailable_count=10
```

Command:

```powershell
python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12
```

Optional backend behavior:

```text
dummy=available
yolo_optional=backend_unavailable when ultralytics is missing
rt_detr_optional=backend_unavailable when ultralytics is missing
```

Boundary fields:

```text
carla_import_required=false
carla_server_required=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Validation checklist:

```text
python -m py_compile scripts\run_phase12c_perception_backend_ablation.py
python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Phase 12C prepares perception backend ablation commands. It does not execute YOLO / RT-DETR runtime validation and does not upgrade MA-VLNA to a CARLA benchmark result.
