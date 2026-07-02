# Phase 12C-R1-RT-DETR-ASSET-BLOCKER-FREEZE

## Status

```text
Phase 12C-R1-RT-DETR-ASSET-BLOCKER-FREEZE Completed - RT-DETR branch is formally frozen as external local-weight blocked and Phase 12C summary handoff is prepared.
```

This phase freezes the RT-DETR branch as an external local-weight blocker. It is docs and summary only: it does not install dependencies, download weights, create fake weights, run post-setup smoke, refresh RT-DETR rows, start CARLA, or execute CARLA route runtime.

## Evidence Lineage

```text
rtdetr_weights_local_rerun_evidence_dir=experiments\phase12\20260702T125105Z
previous_weights_local_evidence_dir=experiments\phase12\20260702T071641Z
rtdetr_asset_exec_evidence_dir=experiments\phase12\20260702T044516Z
rtdetr_asset_setup_evidence_dir=experiments\phase12\20260702T040554Z
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
target_perception_backend=rtdetr
```

## Frozen Blocker

```text
rt_detr_branch_frozen_external_asset_blocker=true
rtdetr_dependency_ready=true
ultralytics_import_ready_after=true
ultralytics_version_after=8.4.84
rtdetr_weights_configured=true
rtdetr_weights_ready=false
rtdetr_weights_path=D:\AIModels\rtdetr\rtdetr-l.pt
missing_weight_path=D:\AIModels\rtdetr\rtdetr-l.pt
rtdetr_no_fallback_ready=false
post_setup_smoke_executed=false
edge_rtdetr_command_passed=null
edge_rtdetr_fallback_used=null
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
phase12c_rtdetr_backend_unavailable_count=5
recommended_next_phase_without_weights=Phase 12C-SUM
recommended_next_phase_if_weights_available=R1-RT-DETR-WEIGHTS-LOCAL-RERUN
```

ASSET-EXEC installed the RT-DETR dependency side successfully in the CARLA Python 3.12 runtime. WEIGHTS-LOCAL and WEIGHTS-LOCAL-RERUN both correctly stopped before post-setup smoke because the operator-provided local weight file is missing at `D:\AIModels\rtdetr\rtdetr-l.pt`.

The branch remains frozen until the operator provides local weights. When the weight file exists, the next technical branch is `R1-RT-DETR-WEIGHTS-LOCAL-RERUN`. Without weights, the project should move to `Phase 12C-SUM`.

Phase 12C-SUM has now been prepared:

```text
Phase 12C-SUM Completed
rtdetr_external_asset_blocked=true
rtdetr_no_fallback_ready=false
recommended_next_phase=Phase 12D-VLM-TRIGGER-SCAFFOLD_OR_FINAL_REPORT_FREEZE
```

Summary artifacts: `docs\phase12c_perception_backend_ablation_summary.md` and `docs\phase12c_perception_backend_ablation_summary.json`.

## Phase 12C-SUM Handoff

| backend | status | key evidence | claim | boundary |
| --- | --- | --- | --- | --- |
| `dummy` | `runtime_confirmed` | `experiments\phase12\20260628T173019Z` | 5/5 calibrated dummy backend smoke rows reached goal | Not infraction benchmark, not Leaderboard |
| `yolov9` | `route_begin_and_latency_profiled_but_not_route_completion` | source adapter `experiments\phase12\20260630T060621Z`; setup `experiments\phase12\20260701T045047Z`; short route-begin `experiments\phase12\20260701T064944Z`; latency `experiments\phase12\20260701T103721Z`; latency opt `experiments\phase12\20260701T115744Z`; lightweight blocked `experiments\phase12\20260701T165325Z` | No-fallback source adapter verified, selected route loop entered, latency bottleneck characterized | No route completion, no model accuracy, no full ablation pass |
| `rtdetr` | `external_asset_blocked` | unlock `experiments\phase12\20260702T022636Z-1`; asset setup `experiments\phase12\20260702T040554Z`; asset exec `experiments\phase12\20260702T044516Z`; weights-local rerun `experiments\phase12\20260702T125105Z` | Dependency installed, local weights missing | No no-fallback readiness, no runtime, no accuracy |

## Boundary

```text
runtime_scope=docs_summary_external_asset_blocker_freeze_only
weights_downloaded=false
weights_committed=false
post_setup_smoke_executed=false
runtime_confirmation_executed=false
carla_route_runtime_executed=false
rtdetr_runtime_verified=false
rtdetr_accuracy_verified=false
full_phase12c_perception_ablation_runtime_pass=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

This freeze does not claim RT-DETR no-fallback readiness, RT-DETR route runtime pass, RT-DETR route completion, RT-DETR accuracy, YOLOv9 selected route runtime pass, full Phase 12C perception ablation runtime pass, CARLA Leaderboard, formal route benchmark, or infraction benchmark.
