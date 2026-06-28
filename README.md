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

Phase 12 scaffold（不啟動 CARLA、不跑大型實驗）：

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

Phase 12B-BASE-M baseline-only controller ablation runtime（需外部 CARLA server 與 Python 3.12 CARLA env）：

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode baseline_planner_action_mapper --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --output-dir experiments\phase12
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
