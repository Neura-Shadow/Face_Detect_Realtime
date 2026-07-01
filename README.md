# MA-VLNA — Memory-Augmented Vision-Language Navigation Agent

> 記憶增強型視覺語言導航代理 | A 2026 Research Engineering System | **v0.5.0 (Release Candidate)**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org)
[![Supabase](https://img.shields.io/badge/Supabase-pgvector-3ECF8E.svg)](https://supabase.com)
[![Fail-Safe Architecture](https://img.shields.io/badge/Architecture-Fail--Safe-red.svg)](#3-三層安全機制)

一個符合 2026 年工程研究趨勢的「**CV + Event-Triggered VLM Reasoner + Scene Memory + Planner Arbitration + Research Dashboard**」視覺導航代理系統。

---

## 🎯 專案定位

MA-VLNA 是一個**可運行、可擴充、可回放、可驗證、可展示**的視覺導航代理研究系統，從一個基於 OpenCV 的即時監控專案重構而來。

### 研究核心問題

> **如何讓 VLM (視覺語言模型) 在具身智能系統中擔任「認知顧問」而非「直接控制器」，同時保證安全性、可審計性與資源效率？**

### 設計回答 (v0.5 核心特色)

- **雙軌感知 (Dual-track Perception)**：高頻 Edge CV（YOLO / RT-DETR）處理常規幀，VLM 僅在異常事件觸發時介入。
- **優雅降級 (Graceful Fallback)**：即便網路斷線、API 失效或缺少深度學習模型，系統仍能自動退回 LocalStub 與 Dummy 節點，保證決策鏈不斷鏈。
- **記憶增強 (Memory-Augmented)**：pgvector 場景記憶取代逐幀 VLM 推理，節省 95%+ 推理資源。
- **三層安全 (Tri-layer SafetyGate)**：SafetyGate → SemanticPlanner → SimulatorAdapter，任一層拒絕即退回保守策略。
- **全程可審計 (Fully Auditable)**：所有決策、拒絕、失敗案例寫入 Supabase，支援 Dashboard Replay 回放與人工覆核。

### 系統整合狀態 (Integration Status)

- **Phase 1-4**: Architecture refactoring, workers, mock mode, APIs, frontend — **Passed**
- **Phase 5**: Real Supabase verification, Real WebCam integration — **Passed**
- **Phase 6-9 (v0.5)**: 
  - Edge Perception Optional Backend (YOLO/RT-DETR) Fallback: **Passed**
  - SafetyGate Final Regression: **Passed**
  - VLM Reasoner API Fallback (OpenAI-compatible): **Passed**
  - Automated Release Demo Verification (6/6 Tests): **Passed**
- **Phase 10**:
  - Supervision optional analytics layer: **Passed**
- **Phase 11**:
  - CARLA closed-loop adapter / runner smoke checks: **Passed locally without CARLA server**
  - CARLA core runtime verification with fake closed-loop: **Passed**
  - Phase 11B real CARLA server smoke gate: **Available**
  - Phase 11C real CARLA runtime execution: **Passed via Phase 11H dedicated Python 3.12 runtime**
  - Phase 11D CARLA runtime provisioning gate: **Ready under Python 3.12 + CARLA 0.9.16**
  - Phase 11E CARLA runtime environment unlock kit: **Ready**
  - Phase 11F external CARLA package provisioning: **Blocked — no valid local CARLA package root**
  - Phase 11G automated D drive CARLA provisioning: **Blocked in base Python 3.10 — CARLA 0.9.16 wheel targets CPython 3.12**
  - Phase 11H Python 3.12 CARLA runtime environment: **Passed — 11D ready, 11C 5/50-step real smoke passed**
  - Phase 11I CARLA runtime evidence pack: **Passed — structured evidence for 5/50-step real smoke generated**
  - Phase 11J CARLA sensor metrics instrumentation: **Passed — collision/lane sensors, speed, and distance measured during real smoke**
  - Phase 11K fixed route scenario smoke: **Passed — spawn-pair route progress metrics generated during real CARLA smoke**
  - Phase 11L fixed route completion attempt: **Passed — strict fixed spawn-pair goal-reach gate passed**
  - Phase 11M GRP-backed route following: **Passed — strict GlobalRoutePlanner route-following goal-reach gate passed**
  - Phase 11N release packaging: **Passed — git snapshot, artifact boundary, and release zip generated**
  - Phase 11O source commit boundary: **Passed — source-only commit boundary and Draft PR body prepared**
- **Phase 12**:
  - Experiment kickoff preparation: **Passed — controlled experiment plan and scaffold created without running large experiments**
  - Phase 12A CARLA route scaling: **Evidence produced — real 5-route CARLA batch generated aggregate evidence; strict all-route gate blocked by route_05**
  - Phase 12A-R05 route recovery: **Blocked — 4 conservative recovery variants executed; best variant improved progress but did not reach goal**
  - Phase 12A-R05B waypoint progression diagnosis: **Passed — extended 5200-step diagnostic reached Route 05 goal and confirmed 2500-step horizon limitation**
  - Phase 12A-H horizon calibration: **Passed — generated calibrated per-route step horizons from existing real CARLA evidence**
  - Phase 12A-C calibrated route confirmation: **Passed — real 5-route CARLA runtime confirmed all calibrated horizons**
  - Phase 12B controller ablation scaffold: **Prepared — 15-row dry-run matrix for 5 routes x 3 controller modes; no CARLA runtime executed**
  - Phase 12B-R controller ablation runtime wiring: **Prepared — execute-runtime child process wiring, blocked evidence handling, and aggregation implemented**
  - Phase 12B-GRP GRP controller ablation runtime: **Passed — 5/5 calibrated `grp_follower` rows reached goal in real CARLA**
  - Phase 12B-LIN linear spawn-pair controller runtime: **Passed for route-progress smoke — 5/5 calibrated `linear_spawn_pair_follower` rows passed after CARLA warm-up; high collision counts preserved**
  - Phase 12B-BASE-M baseline PlannerAction mapper route metrics: **Prepared — baseline mapper now emits structured route metrics; no-server blocked wiring smoke verified**
  - Phase 12B-BASE baseline PlannerAction mapper runtime: **Blocked — 5/5 real CARLA baseline rows executed but failed route-progress gate**
  - Phase 12B-SUM controller ablation comparative summary: **Prepared — GRP, linear, and baseline evidence normalized into comparative tables**
  - Phase 12C perception backend ablation: **Prepared — 5 routes x 3 backend modes scaffolded; YOLOv9 optional rows are now available / command-ready after no-fallback source adapter verification; RT-DETR remains optional**
  - Phase 12C-DUMMY dummy backend runtime confirmation: **Passed — 5/5 calibrated `grp_follower + dummy` rows reached goal in real CARLA; collision_count_total=0, lane_invasion_count_total=83**
  - Phase 12C-YOLOv9-U YOLOv9 optional dependency unlock: **Prepared — CARLA Python 3.12 preflight confirms YOLOv9 dependency missing; manual unlock and post-unlock verification commands generated**
  - Phase 12C-YOLOv9-B EdgePerception YOLOv9 backend adapter: **Prepared — `EdgePerception --test yolov9` is registered in base and CARLA Python; missing dependency still falls back safely**
  - Phase 12C-YOLOv9-V YOLOv9 post-unlock verification: **Passed — external_source strict verifier passed at `experiments\phase12\20260630T061015Z`; no-fallback backend readiness is verified in CARLA Python 3.12**
  - Phase 12C-YOLOv9-SRC official YOLOv9 source adapter: **Prepared — external `YOLOV9_ROOT` / `YOLOV9_WEIGHTS` contract, source adapter, and no-fallback verification gate are implemented**
  - Phase 12C-YOLOv9-SRC-V source adapter no-fallback verification: **Passed — official YOLOv9 source adapter verified with no fallback in the CARLA Python 3.12 runtime at `experiments\phase12\20260630T060621Z`**
  - Phase 12C-YOLOv9-R1 selected YOLOv9 runtime row: **Blocked — RERUN reached CARLA and launched `grp_follower + yolov9`, but the selected row timed out before route metrics were produced at `experiments\phase12\20260630T134322Z`**

  - Phase 12C-YOLOv9-R1-DIAG timeout diagnosis: **Diagnostic Completed - bounded 300-step diagnostic classified the selected-row blocker as `map_load_or_spawn_stall` at `experiments\phase12\20260630T150500Z`; no runtime pass claimed**
  - Phase 12C-YOLOv9-R1-SETUP setup recovery probe: **Probe Pass - selected setup reached Town03, ego spawn, RGB first frame, GRP route generation, 20 warm-up ticks, and cleanup at `experiments\phase12\20260701T045047Z`; no YOLOv9 runtime pass claimed**
  - Phase 12C-YOLOv9-R1-SHORT route-begin probe: **Probe Pass - selected YOLOv9 row entered the closed-loop route loop with 50 world ticks, 50 RGB frames, 50 EdgePerception calls, 11 YOLOv9 no-fallback inference samples, and partial route metrics at `experiments\phase12\20260701T064944Z`; no route completion or YOLOv9 runtime pass claimed**
  - Phase 12C-YOLOv9-R1-LATENCY route-loop latency probe: **Completed - current-cadence YOLOv9 route loop profiled at `experiments\phase12\20260701T103721Z`; effective FPS `0.239313`, YOLOv9 avg `2522.06ms`, bottleneck `yolov9_forward_dominant`, recommended next phase `R1-LATENCY-OPT`; no route completion claimed**
  - Phase 12C-YOLOv9-R1-LATENCY-OPT forward-latency optimization probe: **No-Improvement - bounded optimization variants completed at `experiments\phase12\20260701T115744Z`; best variant `variant_01_baseline_recheck`, effective FPS `0.168392`, YOLOv9 avg `2194.8ms`, avg improvement `12.976%`, FPS improvement `-29.635%`, useful improvement `false`, recommended next phase `R1-YOLOv9-LIGHTWEIGHT`; no route completion claimed**

Phase 12 begins experiment planning and controlled experiment scaffolding. Phase 11 remains the CARLA runtime verification and evidence-pack foundation.

---

## 🏗️ 系統架構圖 (Architecture Overview)

```
┌─────────────────────────────────────────────────────────────┐
│           Frontend Dashboard (Next.js 16 + Tailwind CSS)    │
│  StatusPanel │ VisualPanel │ VLMPanel │ MemoryPanel │ Replay│
└──────────────────────────┬──────────────────────────────────┘
                           │  REST API + Supabase Realtime
┌──────────────────────────▼──────────────────────────────────┐
│             FastAPI Backend (10 endpoints, query-only)       │
└──────────────────────────┬──────────────────────────────────┘
                           │  Supabase Python Client
┌──────────────────────────▼──────────────────────────────────┐
│          Supabase (PostgreSQL + pgvector + Storage)          │
└──────────────────────────┬──────────────────────────────────┘
                           │  Read / Write
┌──────────────────────────▼──────────────────────────────────┐
│                    Python Workers                            │
│                                                              │
│  Camera ──► EdgePerception ──► EmbeddingBackend              │
│                │                      │                      │
│                ▼                      ▼                      │
│         TriggerPolicy ◄── SceneMemoryRetriever               │
│              │                                               │
│     ┌────────┴────────┐                                      │
│     ▼                 ▼                                      │
│  LocalPlanner    VLMReasoner ──► SafetyGate                  │
│     │                                │                       │
│     └──────────► SemanticPlanner ◄───┘                       │
│                       │                                      │
│                SimulatorAdapter ──► TelemetryPublisher        │
└──────────────────────────────────────────────────────────────┘
```

> 📐 詳細 Mermaid 互動式架構圖請見 [docs/system_architecture.md](docs/system_architecture.md)

---

## 🚀 快速開始 (Quickstart)

### Mock Demo 模式（推薦，無需任何金鑰）

MA-VLNA 支援完整的離線 Mock 模式，不需要 Supabase、VLM API 或相機硬體。

#### 1. Python Agent — 30 步自動駕駛與強制 VLM 觸發測試

```bash
cd workers
pip install -r requirements.txt

# 執行 30 幀完整循環，並設定每 10 幀強制觸發 VLM 仲裁
python -m workers.Autonomous_Driving_Agent --mode mock --steps 30 --force-vlm-every 10
```

#### 2. FastAPI Backend — API 端點驗證

```bash
cd backend
pip install -r requirements.txt

# 自動偵測缺少 Supabase 金鑰，降級到 MockSupabaseClient
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload
```

#### 3. Next.js Dashboard — 研究展示界面

```bash
cd frontend
npm install
npm run dev
# 瀏覽器開啟 http://localhost:3000
```

> 📖 完整 Demo 腳本與解說請見 [docs/demo_script.md](docs/demo_script.md)

#### 4. Phase 11 CARLA Closed-Loop Smoke Checks

不需要 CARLA server，也不要求安裝 `carla` wheel：

```bash
python scripts/run_phase11_carla_checks.py
```

只跑 core runtime verification：

```bash
python scripts/run_phase11_core_runtime_checks.py
```

若已啟動 CARLA server 並安裝相容 Python wheel：

```bash
python scripts/run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 5 --require-server

python -m workers.CARLA_Closed_Loop_Agent --host 127.0.0.1 --port 2000 --steps 100 --perception-backend dummy
```

Phase 11H 驗證過的 Python 3.12 CARLA runtime：

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 50 --require-server
```

啟用 optional VLM path：

```bash
python -m workers.CARLA_Closed_Loop_Agent --enable-vlm --vlm-provider local_stub --force-vlm-every 20 --steps 100
```

> 📖 Phase 11 詳細流程請見 [docs/phase11_carla_closed_loop.md](docs/phase11_carla_closed_loop.md)
> 
> 🧭 Phase 11B 真實 CARLA 環境建置請見 [docs/phase11b_real_carla_environment_setup.md](docs/phase11b_real_carla_environment_setup.md)
>
> Phase 11C 本機執行紀錄請見 [docs/phase11c_real_carla_runtime_execution.md](docs/phase11c_real_carla_runtime_execution.md)
>
> Phase 11D provisioning gate 請見 [docs/phase11d_carla_runtime_provisioning_gate.md](docs/phase11d_carla_runtime_provisioning_gate.md)
>
> Phase 11E unlock kit 請見 [docs/phase11e_carla_runtime_environment_unlock.md](docs/phase11e_carla_runtime_environment_unlock.md)
>
> Phase 11F provisioning attempt 請見 [docs/phase11f_external_carla_provisioning.md](docs/phase11f_external_carla_provisioning.md)
>
> Phase 11G D drive provisioning attempt 請見 [docs/phase11g_automated_carla_d_drive_provisioning.md](docs/phase11g_automated_carla_d_drive_provisioning.md)
>
> Phase 11H Python 3.12 CARLA runtime pass 請見 [docs/phase11h_python312_carla_runtime_environment.md](docs/phase11h_python312_carla_runtime_environment.md)
>
> Phase 11I structured evidence pack 請見 [docs/phase11i_carla_runtime_evidence_pack.md](docs/phase11i_carla_runtime_evidence_pack.md)
>
> Phase 11J sensor metrics instrumentation 請見 [docs/phase11j_carla_sensor_metrics_instrumentation.md](docs/phase11j_carla_sensor_metrics_instrumentation.md)
>
> Phase 11K fixed route scenario smoke 請見 [docs/phase11k_fixed_route_scenario_smoke.md](docs/phase11k_fixed_route_scenario_smoke.md)
>
> Phase 11L fixed route completion attempt 請見 [docs/phase11l_fixed_route_completion_attempt.md](docs/phase11l_fixed_route_completion_attempt.md)
>
> Phase 11M GRP-backed route following 請見 [docs/phase11m_grp_route_following_boundary_prep.md](docs/phase11m_grp_route_following_boundary_prep.md)
>
> Phase 11N release packaging 請見 [docs/phase11n_git_snapshot_artifact_release_packaging.md](docs/phase11n_git_snapshot_artifact_release_packaging.md)
>
> Phase 11O source commit boundary / Draft PR preparation 請見 [docs/phase11o_source_commit_boundary_draft_pr.md](docs/phase11o_source_commit_boundary_draft_pr.md)
>
> Phase 12 experiment kickoff plan 請見 [docs/phase12_experiment_kickoff_plan.md](docs/phase12_experiment_kickoff_plan.md)
>
> Phase 12A CARLA route scaling experiment 請見 [docs/phase12a_carla_route_scaling_experiment.md](docs/phase12a_carla_route_scaling_experiment.md)
>
> Phase 12A real runtime evidence 請見 [docs/phase12a_real_route_scaling_evidence.md](docs/phase12a_real_route_scaling_evidence.md)
>
> Phase 12A-R05 failure diagnosis / recovery experiment 請見 [docs/phase12a_r05_failure_diagnosis_recovery.md](docs/phase12a_r05_failure_diagnosis_recovery.md)
>
> Phase 12A-R05B late-route waypoint progression diagnosis 請見 [docs/phase12a_r05b_late_route_waypoint_progression_diagnosis.md](docs/phase12a_r05b_late_route_waypoint_progression_diagnosis.md)
>
> Phase 12A-H horizon calibration experiment 請見 [docs/phase12a_h_horizon_calibration_experiment.md](docs/phase12a_h_horizon_calibration_experiment.md)
>
> Phase 12A-C calibrated 5-route runtime confirmation 請見 [docs/phase12a_c_calibrated_route_confirmation.md](docs/phase12a_c_calibrated_route_confirmation.md)
>
> Phase 12B controller ablation scaffold 請見 [docs/phase12b_controller_ablation_experiment.md](docs/phase12b_controller_ablation_experiment.md)
>
> Phase 12B-R controller ablation runtime wiring 請見 [docs/phase12b_r_controller_ablation_runtime_wiring.md](docs/phase12b_r_controller_ablation_runtime_wiring.md)
>
> Phase 12B-GRP GRP controller ablation runtime pass 請見 [docs/phase12b_grp_controller_ablation_runtime_pass.md](docs/phase12b_grp_controller_ablation_runtime_pass.md)
>
> Phase 12B-LIN linear spawn-pair controller runtime pass / blocked evidence 請見 [docs/phase12b_lin_controller_ablation_runtime_pass.md](docs/phase12b_lin_controller_ablation_runtime_pass.md)
>
> Phase 12B-BASE-M baseline PlannerAction mapper route-metric wiring 請見 [docs/phase12b_base_m_planner_action_mapper_route_metrics.md](docs/phase12b_base_m_planner_action_mapper_route_metrics.md)
>
> Phase 12B-BASE baseline PlannerAction mapper runtime evidence 請見 [docs/phase12b_base_planner_action_mapper_runtime_evidence.md](docs/phase12b_base_planner_action_mapper_runtime_evidence.md)
>
> Phase 12B-SUM controller ablation comparative summary 請見 [docs/phase12b_sum_controller_ablation_comparative_summary.md](docs/phase12b_sum_controller_ablation_comparative_summary.md)
>
> Phase 12C perception backend ablation scaffold 請見 [docs/phase12c_perception_backend_ablation_prepared.md](docs/phase12c_perception_backend_ablation_prepared.md)
>
> Phase 12C-DUMMY dummy perception backend runtime confirmation 請見 [docs/phase12c_dummy_backend_runtime_confirmation.md](docs/phase12c_dummy_backend_runtime_confirmation.md)
>
> Phase 12C-YOLOv9-U YOLOv9 optional dependency unlock preparation 請見 [docs/phase12c_yolov9_optional_dependency_unlock_prepared.md](docs/phase12c_yolov9_optional_dependency_unlock_prepared.md)
>
> Phase 12C-YOLOv9-B EdgePerception YOLOv9 backend adapter preparation 請見 [docs/phase12c_yolov9_backend_adapter_prepared.md](docs/phase12c_yolov9_backend_adapter_prepared.md)
>
> Phase 12C-YOLOv9-V YOLOv9 post-unlock verification 請見 [docs/phase12c_yolov9_post_unlock_verification.md](docs/phase12c_yolov9_post_unlock_verification.md)
>
> Phase 12C-YOLOv9-SRC official YOLOv9 source adapter verification 請見 [docs/phase12c_yolov9_source_adapter_verification.md](docs/phase12c_yolov9_source_adapter_verification.md)
>
> Phase 12C-YOLOv9-SRC-V no-fallback verification 請見 [docs/phase12c_yolov9_source_adapter_no_fallback_verification.md](docs/phase12c_yolov9_source_adapter_no_fallback_verification.md)
>
> Phase 12C-YOLOv9-R1 selected runtime confirmation 請見 [docs/phase12c_yolov9_runtime_confirmation.md](docs/phase12c_yolov9_runtime_confirmation.md)
>
> Phase 12C-YOLO-U generic YOLO unlock preparation 是早期歷史紀錄，請見 [docs/phase12c_yolo_optional_dependency_unlock_prepared.md](docs/phase12c_yolo_optional_dependency_unlock_prepared.md)

Phase 12 scaffold（不啟動 CARLA、不跑大型實驗）：

> Phase 12C-YOLOv9-R1-DIAG runtime timeout diagnosis 請見 [docs/phase12c_yolov9_runtime_timeout_diagnosis.md](docs/phase12c_yolov9_runtime_timeout_diagnosis.md)
>
> Phase 12C-YOLOv9-R1-SETUP setup recovery probe 請見 [docs/phase12c_yolov9_r1_setup_recovery.md](docs/phase12c_yolov9_r1_setup_recovery.md)
>
> Phase 12C-YOLOv9-R1-SHORT route-begin probe 請見 [docs/phase12c_yolov9_r1_short_route_begin.md](docs/phase12c_yolov9_r1_short_route_begin.md)
>
> Phase 12C-YOLOv9-R1-LATENCY route-loop latency probe 請見 [docs/phase12c_yolov9_r1_latency_probe.md](docs/phase12c_yolov9_r1_latency_probe.md)
> Phase 12C-YOLOv9-R1-LATENCY-OPT forward-latency optimization probe 請見 [docs/phase12c_yolov9_r1_latency_opt_probe.md](docs/phase12c_yolov9_r1_latency_opt_probe.md)

```powershell
python scripts\run_phase12_experiment_plan.py --output-dir experiments\phase12
```

Phase 12A route-scaling dry run（只寫 summary，不啟動 CARLA）：

```powershell
python scripts\run_phase12a_route_scaling_experiment.py --dry-run --output-dir experiments\phase12
```

Phase 12A-R05 recovery dry run（只寫 recovery variant commands，不啟動 CARLA）：

```powershell
python scripts\run_phase12a_r05_recovery_experiment.py --dry-run --output-dir experiments\phase12
```

Phase 12A-R05B waypoint progression dry run（解析既有 R05 evidence 並寫 extended command，不啟動 CARLA）：

```powershell
python scripts\run_phase12a_r05b_waypoint_progression_diagnosis.py --dry-run --run-extended --output-dir experiments\phase12
```

Phase 12A-H horizon calibration（只讀既有 real CARLA evidence，不啟動 CARLA）：

```powershell
python scripts\run_phase12a_h_horizon_calibration_experiment.py --output-dir experiments\phase12 --require-complete-calibration
```

Phase 12A-C calibrated route confirmation dry run（只寫 calibrated child commands，不啟動 CARLA）：

```powershell
python scripts\run_phase12a_c_calibrated_route_confirmation.py --dry-run --output-dir experiments\phase12
```

Phase 12B controller ablation dry run（只寫 5 routes x 3 controller commands，不啟動 CARLA）：

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py --dry-run --output-dir experiments\phase12
```

Phase 12B-R controller ablation runtime wiring smoke（顯式執行 1 row，無 CARLA server 時應產生 blocked evidence，不可宣稱 Runtime Pass）：

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --route-id route_01 --controller-mode linear_spawn_pair_follower --runtime-row-limit 1 --child-timeout-sec 120 --python-executable python --output-dir experiments\phase12
```

Phase 12B-GRP GRP-only controller ablation runtime（需外部 CARLA server 與 Python 3.12 CARLA env）：

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode grp_follower --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --output-dir experiments\phase12
```

Phase 12B-LIN linear-only controller ablation runtime（route-progress smoke，不是 goal-reach / infraction benchmark）：

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode linear_spawn_pair_follower --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --output-dir experiments\phase12
```

Phase 12B-BASE-M baseline PlannerAction mapper route-metric wiring smoke（無 CARLA server 時應產生 structured blocked evidence，不可宣稱 Runtime Pass）：

```powershell
python scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --route-id route_01 --controller-mode baseline_planner_action_mapper --runtime-row-limit 1 --child-timeout-sec 120 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --output-dir experiments\phase12
```

Phase 12B-BASE baseline-only controller ablation runtime（需外部 CARLA server 與 Python 3.12 CARLA env；可能產生 route-progress blocked evidence）：

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode baseline_planner_action_mapper --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --output-dir experiments\phase12
```

Phase 12B-SUM controller ablation comparative summary（讀取既有 evidence，不啟動 CARLA）：

```powershell
python scripts\run_phase12b_controller_ablation_summary.py --require-complete --output-dir experiments\phase12
```

Phase 12C perception backend ablation scaffold（固定 `grp_follower`，只做 backend preflight / command scaffold，不啟動 CARLA）：

```powershell
python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12
```

Phase 12C-DUMMY dummy backend runtime confirmation（需外部 CARLA server 與 Python 3.12 CARLA env）：

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_dummy_runtime_confirmation.py --host 127.0.0.1 --port 2000 --output-dir experiments\phase12 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --parent-timeout-sec 14400
```

Phase 12C-YOLOv9-U YOLOv9 optional dependency unlock preparation（不自動安裝、不改 baseline requirements、不啟動 CARLA）：

```powershell
python scripts\run_phase12c_yolov9_optional_dependency_unlock.py --output-dir experiments\phase12
```

Phase 12C-YOLOv9-B EdgePerception YOLOv9 backend adapter checks（只驗證 adapter path 與 fallback，不啟動 CARLA）：

```powershell
python scripts\run_phase12c_yolov9_backend_adapter_checks.py --output-dir experiments\phase12
```

Phase 12C-YOLOv9-V post-unlock verification（external_source strict gate 已通過；不代表 CARLA route runtime pass）：

```powershell
python scripts\run_phase12c_yolov9_post_unlock_verification.py --unlock-mode external_source --output-dir experiments\phase12 --require-verified
```

Phase 12C-YOLOv9-SRC official source adapter verification（不提交 source/weights，不啟動 CARLA）：

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r "$env:YOLOV9_ROOT\requirements.txt"
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --output-dir experiments\phase12
```

Phase 12C-YOLOv9-SRC-V strict no-fallback verification（已驗證 source adapter no-fallback；不可宣稱 YOLOv9 CARLA route runtime pass）：

```powershell
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified
```

Verified Phase 12C-YOLOv9-SRC-V evidence:

```text
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
post_unlock_verified=true
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
runtime_confirmation_executed=false
carla_route_runtime_executed=false
```

Phase 12C-YOLOv9-R1 selected runtime confirmation（單一路線 formal gate；本次因 CARLA server 不可達而產生 blocked evidence）：

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_runtime_confirmation.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --child-timeout-sec 2400 --parent-timeout-sec 7200 --require-yolov9-ready
```

Latest Phase 12C-YOLOv9-R1 evidence:

```text
runtime_evidence_dir=experiments\phase12\20260630T134322Z
previous_blocked_evidence_dir=experiments\phase12\20260630T094645Z
carla_server_reachable=true
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
child_row_result=timeout
metrics_read_status=loaded
```

Phase 12C-YOLOv9-R1-DIAG timeout diagnosis（bounded instrumentation only；不宣稱 YOLOv9 runtime pass）：

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --diagnostic-steps 300 --diagnostic-timeout-sec 900 --child-timeout-sec 900 --parent-timeout-sec 1800 --require-yolov9-ready --emit-heartbeat-every 10 --emit-partial-metrics-every 25
```

Latest Phase 12C-YOLOv9-R1-DIAG evidence:

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
dry_run_evidence_dir=experiments\phase12\20260630T150101Z
timeout_classification=map_load_or_spawn_stall
diagnosis_confidence=high
diagnostic_steps_completed=0
heartbeat_count=0
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
yolo_runtime_row_verified=false
```

Phase 12C-YOLOv9-R1-SETUP setup/spawn-stage recovery probe（不宣稱 YOLOv9 runtime pass）：

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_setup_recovery.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --map-load-mode reuse_or_load --setup-timeout-sec 300 --map-load-timeout-sec 180 --spawn-timeout-sec 120 --sensor-timeout-sec 120 --warmup-ticks 20 --warmup-timeout-sec 120 --require-yolov9-ready
```

Latest Phase 12C-YOLOv9-R1-SETUP evidence:

```text
setup_evidence_dir=experiments\phase12\20260701T045047Z
dry_run_evidence_dir=experiments\phase12\20260701T045259Z
map_load_mode=reuse_or_load
carla_server_reachable=true
town_ready=true
ego_spawned=true
rgb_sensor_attached=true
first_rgb_frame_received=true
grp_route_generated=true
warmup_ticks_completed=20
setup_probe_passed=true
setup_blocker_classification=setup_probe_passed
yolo_runtime_row_verified=false
```

Phase 12C-YOLOv9-R1-SHORT selected route-begin probe（只驗證早期 route-loop breadcrumbs；不宣稱 route completion / YOLOv9 runtime pass）：

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_short_route_begin.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --setup-evidence-dir experiments\phase12\20260701T045047Z --diagnostic-steps 50 --diagnostic-timeout-sec 300 --child-timeout-sec 300 --parent-timeout-sec 900 --require-yolov9-ready --require-setup-passed --emit-heartbeat-every 5 --emit-partial-metrics-every 10
```

Latest Phase 12C-YOLOv9-R1-SHORT evidence:

```text
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
diagnostic_steps_completed=50
heartbeat_count=11
world_tick_count=50
rgb_frame_received_count=50
edge_perception_call_count=50
yolov9_inference_call_count=11
edge_yolov9_fallback_used_during_route=false
partial_route_progress_seen=true
short_route_begin_verified=true
short_route_begin_blocker_classification=short_route_begin_verified
yolo_runtime_row_verified=false
selected_route_completion_verified=false
```

Phase 12C-YOLOv9-R1-LATENCY route-loop latency and cadence probe（只量測 latency/cadence；不宣稱 route completion / YOLOv9 runtime pass）：

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_latency_probe.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --short-route-begin-evidence-dir experiments\phase12\20260701T064944Z --setup-evidence-dir experiments\phase12\20260701T045047Z --require-yolov9-ready --require-setup-passed --require-short-route-begin-passed --child-timeout-sec 600 --parent-timeout-sec 2400
```

Latest Phase 12C-YOLOv9-R1-LATENCY evidence:

```text
latency_evidence_dir=experiments\phase12\20260701T103721Z
executed_variant_count=2
completed_variant_count=1
blocked_variant_count=1
best_variant_id=variant_01_current_cadence
best_variant_effective_fps=0.239313
best_variant_yolov9_avg_ms=2522.06
baseline_current_cadence_yolov9_avg_ms=2522.06
latency_bottleneck_classification=yolov9_forward_dominant
recommended_next_phase=R1-LATENCY-OPT
latency_probe_completed=true
yolo_runtime_row_verified=false
selected_route_completion_verified=false
```

---

### 真實環境執行（需配置金鑰）

如果您想串接真實的 OpenAI API 或 Supabase：

```bash
cp config/.env.example config/.env
# 編輯 .env，填入 VLM_API_KEY, SUPABASE_URL 與 SUPABASE_SERVICE_ROLE_KEY
```

若您遇到網路中斷或 VLM 金鑰無效，本專案的 **Graceful Fallback 防呆機制** 將保證：
系統**不會崩潰**，並會自動印出 `VLM API 未配置，直接使用 LocalStubReasoner`，退回安全的預設本地決策！

---

## 📁 目錄結構 (Directory Layout)

```
MA-VLNA/
├── workers/                          # 🤖 Python 研究工程層 (3.10+)
├── backend/                          # ⚡ FastAPI 後端 API 層
├── frontend/                         # 🖥️ Next.js 研究 Dashboard
├── scripts/                          # 🛠️ 自動化驗證腳本
├── shared/schemas/                   # 📋 共享 JSON Schema
├── config/                           # ⚙️ 配置 (.env.example, YAML)
├── migrations/                       # 🗄️ SQL 初始化 (pgvector)
└── docs/                             # 📚 文件
```

---

## 🔬 2026 Research Engineering Highlights

### 1. VLM 作為事件觸發式語義 Reasoner
VLM 不再是控制器，而是認知顧問。平均每分鐘 0-3 次推理，比逐幀呼叫節省 95%+ 資源。

### 2. 優雅的防呆架構 (Fail-safe Architecture)
系統在 Perception 與 Reasoner 兩端實作了完美的外掛式設計，當缺少 `ultralytics` YOLO 權重或 `OpenAI API Key` 逾期時，系統能夠瞬間且無縫地退回 `DummyPerception` 與 `LocalStubReasoner`。

### 3. 三層安全機制
1. **SafetyGate**：信心分數、速度限制、禁止動作。拒絕即記錄 telemetry。
2. **SemanticPlanner**：Waypoints 可行性、碰撞檢測。拒絕即退回 LocalPlanner。
3. **SimulatorAdapter**：最終執行確認。失敗即觸發緊急停止 (`emergency_stop`)。

### 4. 全程可回放與可審計
所有 VLM 輸出、規劃決策、拒絕事件皆寫入資料庫，Dashboard 支援歷史場景 Replay 與 A/B 比較，大幅提升可解釋性。

---

## ⚠️ Safety Disclaimer (安全提示)

> **本系統為研究原型 (Research Prototype)，並非實際量產的安全關鍵系統 (Non-safety-critical)。不可直接用於真實車輛控制。**

### 🔐 憑證安全
1. **絕對不要**把 `SUPABASE_SERVICE_ROLE_KEY` 或是 `VLM_API_KEY` commit 到 GitHub。
2. `.env`、`config/.env` 檔案已加入 `.gitignore`。

---

## 📄 License
MIT License — 研究與教育用途。

---

<sub>Built with ❤️ for the Embodied AI research community — 2026</sub>
