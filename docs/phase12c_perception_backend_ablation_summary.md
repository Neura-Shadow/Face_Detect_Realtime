# Phase 12C-SUM - Perception Backend Ablation Summary

## Status

```text
Phase 12C-SUM Completed - perception backend ablation summary and evidence handoff are prepared without claiming full Phase 12C runtime pass.
```

This phase summarizes and normalizes existing Phase 12C perception backend evidence only. It does not start CARLA, execute route runtime, run YOLOv9 route completion, run RT-DETR smoke, install dependencies, download weights, create fake weights, modify baseline requirements, or promote any blocked or partial status into a pass.

## Backend Results

| backend | status | runtime backend | controller | claim | key evidence |
| --- | --- | --- | --- | --- | --- |
| `dummy` | `runtime_confirmed` | `dummy` | `grp_follower` | 5/5 calibrated dummy backend smoke rows reached goal | `experiments\phase12\20260628T173019Z` |
| `yolov9` | `route_begin_and_latency_profiled_but_not_route_completion` | `yolov9` | `grp_follower` | No-fallback source adapter verified, selected route loop entered, latency bottleneck characterized | source `experiments\phase12\20260630T060621Z`; post-unlock `experiments\phase12\20260630T061015Z`; rows `experiments\phase12\20260630T060823Z`; setup `experiments\phase12\20260701T045047Z`; short route-begin `experiments\phase12\20260701T064944Z`; latency `experiments\phase12\20260701T103721Z`; latency opt `experiments\phase12\20260701T115744Z`; lightweight blocked `experiments\phase12\20260701T165325Z`; latest formal gate `experiments\phase12\20260702T182842Z` |
| `rtdetr` | `external_asset_blocked` | `rtdetr` | pending | Dependency installed, local weights missing, branch frozen | unlock `experiments\phase12\20260702T022636Z-1`; asset setup `experiments\phase12\20260702T040554Z`; asset exec `experiments\phase12\20260702T044516Z`; weights-local rerun `experiments\phase12\20260702T125105Z`; freeze doc `docs\phase12c_rtdetr_asset_blocker_freeze.md` |

## Evidence Lineage

```text
dummy_backend_runtime_confirmed=true
dummy_evidence_dir=experiments\phase12\20260628T173019Z
dummy_row_count=5
dummy_passed_count=5
dummy_collision_count_total=0
dummy_lane_invasion_count_total=83

yolov9_route_begin_and_latency_profiled=true
yolov9_route_completion_verified=false
yolov9_source_adapter_verified=true
yolov9_source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
yolov9_post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
yolov9_setup_evidence_dir=experiments\phase12\20260701T045047Z
yolov9_short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
yolov9_latency_evidence_dir=experiments\phase12\20260701T103721Z
yolov9_latency_opt_evidence_dir=experiments\phase12\20260701T115744Z
yolov9_lightweight_evidence_dir=experiments\phase12\20260701T165325Z
yolov9_latest_formal_gate_evidence_dir=experiments\phase12\20260702T182842Z
yolov9_latency_bottleneck_classification=yolov9_forward_dominant
yolov9_best_current_cadence_effective_fps=0.239313
yolov9_baseline_current_cadence_yolov9_avg_ms=2522.06
yolov9_latency_opt_useful_improvement_verified=false
yolov9_lightweight_weights_ready=false

rtdetr_external_asset_blocked=true
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
rtdetr_asset_setup_evidence_dir=experiments\phase12\20260702T040554Z
rtdetr_asset_exec_evidence_dir=experiments\phase12\20260702T044516Z
rtdetr_weights_local_rerun_evidence_dir=experiments\phase12\20260702T125105Z
rt_detr_branch_frozen_external_asset_blocker=true
rtdetr_dependency_ready=true
rtdetr_weights_ready=false
rtdetr_no_fallback_ready=false
phase12c_rtdetr_rows_available=false
```

## Claim Boundaries

| backend | allowed claims | forbidden claims |
| --- | --- | --- |
| `dummy` | Dummy backend runtime smoke confirmed on calibrated routes; collision and lane-invasion counts are sensor metrics | Infraction benchmark, CARLA Leaderboard, formal route benchmark |
| `yolov9` | Source adapter no-fallback verified; selected route-begin and latency were profiled | Selected route runtime pass, route completion, model accuracy, full Phase 12C ablation pass, Leaderboard, formal route benchmark, infraction benchmark |
| `rtdetr` | Dependency installed in CARLA Python 3.12 runtime; local weights missing; branch frozen | No-fallback readiness, runtime pass, route completion, model accuracy, full Phase 12C ablation pass |

Top-level boundary:

```text
full_phase12c_perception_ablation_runtime_pass=false
carla_route_runtime_executed=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

## Next-Step Decision Table

| condition | recommended next phase |
| --- | --- |
| No RT-DETR local weights and no lightweight YOLOv9 weights | `Phase 12D-VLM-TRIGGER-SCAFFOLD_OR_FINAL_REPORT_FREEZE` |
| RT-DETR local weights appear at `D:\AIModels\rtdetr\rtdetr-l.pt` | `R1-RT-DETR-WEIGHTS-LOCAL-RERUN` |
| YOLOv9 lightweight weights appear | `R1-YOLOv9-LIGHTWEIGHT-RERUN` |
| A route-completion attempt is requested before a faster backend is available | Scope it explicitly as slow diagnostic only |

Do not recommend route completion until either a lightweight/fast backend is available, or route runtime is explicitly scoped as slow diagnostic only.

## Boundary Statement

Phase 12C-SUM is not a full perception backend ablation runtime pass. It does not claim YOLOv9 selected route runtime pass, YOLOv9 route completion, YOLOv9 accuracy, RT-DETR no-fallback readiness, RT-DETR runtime pass, RT-DETR accuracy, CARLA Leaderboard, formal route benchmark, or infraction benchmark.
