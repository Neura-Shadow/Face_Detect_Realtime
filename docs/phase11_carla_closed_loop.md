# Phase 11 — CARLA Closed-Loop Integration

## 目標

Phase 11 將 MA-VLNA 從 mock / camera demo 推進到 CARLA closed-loop simulation prototype。

本階段不追求 CARLA Leaderboard，也不引入完整自駕 stack；重點是完成第一條可觀測、可回放、可安全退場的閉環：

```text
CARLA server
-> CARLA client adapter
-> ego vehicle spawn
-> RGB camera sensor
-> MA-VLNA EdgePerception
-> TriggerPolicy / VLMReasoner optional
-> SafetyGate
-> PlannerAction
-> CARLA VehicleControl
-> world.tick()
-> telemetry / replay logs
```

## 新增元件

| 元件 | 角色 |
|---|---|
| `workers/core/carla_adapter.py` | Optional CARLA client adapter、ego vehicle / RGB camera setup、PlannerAction 到 VehicleControl 的映射 |
| `workers/CARLA_Closed_Loop_Agent.py` | Phase 11 closed-loop runner，沿用 EdgePerception、TriggerPolicy、VLMReasoner、SafetyGate、SemanticPlanner、TelemetryPublisher |
| `scripts/run_phase11_carla_checks.py` | 無 CARLA server 也可跑的 Phase 11 smoke checks |
| `scripts/run_phase11_core_runtime_checks.py` | 使用 fake CARLA runtime 驗證 closed-loop orchestration |
| `scripts/run_phase11b_real_carla_smoke.py` | Phase 11B 真實 CARLA server runtime smoke test；支援 preflight / skipped / required-fail 語意 |
| `scripts/run_phase11d_carla_provisioning_gate.py` | Phase 11D read-only provisioning gate，檢查 CARLA package、wheel、server process 與 TCP endpoint |
| `scripts/phase11e_unlock_carla_environment.ps1` | Phase 11E Windows unlock helper，串接 CARLA_ROOT、wheel 安裝、server 啟動、11D 與 11C gate |
| `docs/phase11b_real_carla_environment_setup.md` | Phase 11B 真實 CARLA 環境建置、wheel 對版、server 啟動與驗收指南 |
| `docs/phase11c_real_carla_runtime_execution.md` | Phase 11C 真實 runtime execution attempt 與本機 blocker 證據 |
| `docs/phase11d_carla_runtime_provisioning_gate.md` | Phase 11D provisioning gate 執行結果與解鎖順序 |
| `docs/phase11e_carla_runtime_environment_unlock.md` | Phase 11E unlock kit 使用方式與狀態升級規則 |
| `docs/phase11f_external_carla_provisioning.md` | Phase 11F 外部 CARLA package provisioning 探測與 11C unlock attempt 紀錄 |
| `docs/phase11g_automated_carla_d_drive_provisioning.md` | Phase 11G 自動下載 / 解壓 CARLA 到 D 槽與 wheel install blocker 紀錄 |
| `docs/phase11h_python312_carla_runtime_environment.md` | Phase 11H Python 3.12 CARLA runtime environment 與真實 11C smoke pass 紀錄 |
| `docs/phase11i_carla_runtime_evidence_pack.md` | Phase 11I runtime evidence pack、structured metrics、events 與 regression proof |
| `docs/phase11j_carla_sensor_metrics_instrumentation.md` | Phase 11J CARLA-native collision/lane sensors、speed/distance instrumentation |
| `config/agent_config.yaml` 的 `carla:` 區塊 | CARLA host、port、sync mode、camera、spawn point、control gain 設定 |

## 執行前提

1. CARLA server 已啟動，例如：

```powershell
CarlaUE4.exe -quality-level=Low
```

2. Python 環境安裝與 CARLA server 版本相容的 `carla` wheel。

如果 PyPI 沒有對應版本，請使用 CARLA release 內附的 `PythonAPI/carla/dist/*.whl`。

3. MA-VLNA 核心依賴已安裝：

```powershell
pip install -r workers/requirements.txt
```

## 無 CARLA Server 的本機檢查

Phase 11 提供不依賴 CARLA server 的 smoke checks：

```powershell
python scripts/run_phase11_carla_checks.py
```

驗證範圍：

- `config.py`、`carla_adapter.py`、`CARLA_Closed_Loop_Agent.py` 語法檢查
- PlannerAction -> CARLA control mapping self-test
- `AgentConfig.carla` 設定載入
- CARLA runner import smoke
- Fake CARLA closed-loop core runtime verification
- Phase 11D read-only CARLA runtime provisioning gate

只跑 core runtime gate：

```powershell
python scripts/run_phase11_core_runtime_checks.py
```

Core runtime gate 會在沒有 CARLA server 的情況下跑兩條閉環：

- `EdgePerception -> TriggerPolicy -> local planner -> SafetyGate -> fake control -> telemetry fallback`
- `EdgePerception -> TriggerPolicy(force) -> LocalStub VLM -> SafetyGate -> semantic planner -> fake control -> telemetry fallback`

## Phase 11B — Real CARLA Server Runtime Smoke Test

完整環境建置流程請見 [`docs/phase11b_real_carla_environment_setup.md`](phase11b_real_carla_environment_setup.md)。
本機 Phase 11C 執行紀錄請見 [`docs/phase11c_real_carla_runtime_execution.md`](phase11c_real_carla_runtime_execution.md)。
Phase 11D provisioning gate 請見 [`docs/phase11d_carla_runtime_provisioning_gate.md`](phase11d_carla_runtime_provisioning_gate.md)。
Phase 11E unlock kit 請見 [`docs/phase11e_carla_runtime_environment_unlock.md`](phase11e_carla_runtime_environment_unlock.md)。
Phase 11F external provisioning 紀錄請見 [`docs/phase11f_external_carla_provisioning.md`](phase11f_external_carla_provisioning.md)。
Phase 11G D drive provisioning 紀錄請見 [`docs/phase11g_automated_carla_d_drive_provisioning.md`](phase11g_automated_carla_d_drive_provisioning.md)。
Phase 11H Python 3.12 runtime 紀錄請見 [`docs/phase11h_python312_carla_runtime_environment.md`](phase11h_python312_carla_runtime_environment.md)。
Phase 11I evidence pack 紀錄請見 [`docs/phase11i_carla_runtime_evidence_pack.md`](phase11i_carla_runtime_evidence_pack.md)。
Phase 11J sensor metrics 紀錄請見 [`docs/phase11j_carla_sensor_metrics_instrumentation.md`](phase11j_carla_sensor_metrics_instrumentation.md)。

Phase 11B 是真實 CARLA server gate，不使用 fake adapter。它會先檢查：

- 目前 Python 環境是否安裝 `carla` package。
- `CARLA_HOST:CARLA_PORT` 是否可 TCP 連線。
- 前提成立後，才執行 `CarlaClosedLoopAgent` 的真實 `setup -> tick -> control -> cleanup` 閉環。

預設缺少 CARLA 依賴或 server 時輸出 `skipped`，方便在一般開發機保留驗證紀錄：

```powershell
python scripts/run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 5
```

正式驗收時應使用 `--require-server`，若缺少 `carla` wheel 或 server 未啟動，會以 exit 1 回報：

```powershell
python scripts/run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 5 --require-server
```

只跑 preflight：

```powershell
python scripts/run_phase11b_real_carla_smoke.py --preflight-only
```

## Phase 11D — CARLA Runtime Provisioning Gate

Phase 11D 是 11C 前的 read-only provisioning gate，不執行 CARLA closed-loop，也不自動安裝任何外部套件：

```powershell
python scripts/run_phase11d_carla_provisioning_gate.py
```

正式驗收時可要求 provisioning ready，未 ready 時 exit 1：

```powershell
python scripts/run_phase11d_carla_provisioning_gate.py --require-ready
```

## Phase 11E — CARLA Runtime Environment Unlock

Phase 11E 提供 Windows unlock helper。預設不修改環境，只印出計畫並跑 11D gate：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1
```

指定 CARLA package root 後，可逐步安裝 wheel、啟動 server、重跑 11D 與 11C：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1 `
  -CarlaRoot $env:CARLA_ROOT `
  -InstallWheel `
  -StartServer `
  -VisibleServer `
  -RunRuntimeSmoke `
  -RequireUnlock
```

## Phase 11F — External CARLA Package Provisioning

Phase 11F 只做外部 CARLA runtime provisioning 與 11C 解鎖嘗試，不修改 MA-VLNA 核心程式。目前本機沒有有效 `CARLA_ROOT`，因此停止於 blocker：

```text
Phase 11F Blocked — no valid CARLA server package found locally.
```

## Phase 11G — Fully Automated CARLA Provisioning to D Drive

Phase 11G downloaded and extracted CARLA 0.9.16 Windows package to `D:\CARLA`. The package is valid enough to provide `CarlaUE4.exe` and a Python wheel candidate, but the wheel targets CPython 3.12 while this workspace currently runs Python 3.10.14:

```text
Phase 11G Wheel Install Blocked — carla-0.9.16-cp312-cp312-win_amd64.whl is not compatible with active Python 3.10.14.
```

No CARLA server was launched, and Phase 11C smoke was not executed.

## Phase 11H — Python 3.12 CARLA Runtime Environment

Phase 11H creates a dedicated Python 3.12 environment at `D:\CARLA\envs\ma-vlna-carla312`, installs the CARLA 0.9.16 `cp312` wheel from the extracted package, starts `D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe`, and reruns the real runtime gates:

```text
Phase 11H Pass — Python 3.12 CARLA runtime environment provisioned; Phase 11D ready gate passed; Phase 11C 5-step and 50-step real CARLA --require-server smoke tests passed.
```

Verified command shape:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11d_carla_provisioning_gate.py --carla-root $env:CARLA_ROOT --host 127.0.0.1 --port 2000 --steps 5 --require-ready
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 50 --require-server
```

This pass is bound to the dedicated Python 3.12 environment and a running CARLA 0.9.16 server. The base Python 3.10 environment remains the default for no-server/fallback checks.

## Phase 11I — CARLA Runtime Evidence Pack & Structured Metrics

Phase 11I converts the Phase 11H real runtime pass into a timestamped evidence pack:

```text
runtime_logs\carla_runs\20260613T073948Z
```

The pack contains:

```text
manifest.json
metrics.json
events.jsonl
commands.txt
environment.txt
regression.txt
raw_outputs\
```

Final status:

```text
Phase 11I Evidence Pack Pass — structured evidence for real CARLA 5-step and 50-step smoke generated.
```

Scope boundary:

- Phase 11I is smoke evidence, not route-completion verification.
- Collision, lane invasion, speed, distance, and route progress are verified only in later dedicated instrumentation gates.
- CARLA Leaderboard, real YOLO/RT-DETR, and real OpenAI-compatible VLM remain unverified.

## Phase 11J — CARLA Sensor Metrics & Infraction Instrumentation

Phase 11J adds CARLA-native smoke instrumentation:

- `sensor.other.collision`
- `sensor.other.lane_invasion`
- speed from CARLA vehicle velocity
- distance from ego vehicle transform deltas
- step-level `vehicle_state` events

Evidence directory:

```text
runtime_logs\carla_runs\20260613T082452Z
```

Final status:

```text
Phase 11J Sensor Metrics Pass — real CARLA smoke generated collision, lane invasion, speed, and distance instrumentation.
```

Measured smoke metrics:

```text
collision_sensor_attached=true
lane_invasion_sensor_attached=true
collision_count=0
lane_invasion_count=0
avg_speed_kmh=1.051892
max_speed_kmh=10.583999
distance_traveled_m=0.722641
```

This is still not a route benchmark, infraction benchmark, or CARLA Leaderboard result.

## Phase 11K — Fixed Route Scenario Smoke & Route Progress Metrics

Phase 11K adds a fixed spawn-pair route scenario on top of Phase 11J sensor metrics:

- requested route town: `Town03`
- CARLA runtime map: `Town03_Opt`
- start spawn index: `3`
- end spawn index: `30`
- route progress from ego transform projection against the fixed spawn-pair segment

Evidence directory:

```text
runtime_logs\carla_runs\20260613T092548Z
```

Final status:

```text
Phase 11K Fixed Route Scenario Smoke Pass — route progress metrics generated for real CARLA spawn-pair smoke.
```

Measured route smoke metrics:

```text
steps_completed=100
route_distance_m=307.662099
route_progress_m=8.574274
route_progress_pct=2.786913
route_remaining_m=299.087825
distance_to_goal_m=299.087857
route_progress_verified=true
route_goal_reached=false
route_completion_verified=false
```

The Phase 11K runner uses a route-smoke-only control adapter to generate measurable movement along the fixed spawn-pair route. This adapter does not modify VLM, SafetyGate, SemanticPlanner, or the baseline CARLA control mapper.

This is still not route completion verification, an infraction benchmark, or a CARLA Leaderboard result.

## Phase 11L — Fixed Route Completion Attempt & Goal-Reach Gate

Phase 11L upgrades Phase 11K from progress smoke to a strict fixed spawn-pair goal-reach gate:

- requested route town: `Town03`
- CARLA runtime map: `Town03_Opt`
- start spawn index: `3`
- end spawn index: `30`
- goal tolerance: `3.0m`
- target speed: `18 km/h`

Evidence directory:

```text
runtime_logs\carla_runs\20260613T130532Z
```

Final status:

```text
Phase 11L Fixed Route Completion Pass — strict goal-reach gate passed for real CARLA spawn-pair smoke.
```

Measured goal-reach metrics:

```text
steps_completed=2500
goal_reach_step=1731
route_distance_m=307.662099
route_progress_m=304.756089
route_progress_pct=99.055454
distance_to_goal_m=2.906011
best_distance_to_goal_m=2.906011
fixed_route_goal_reached=true
fixed_route_completion_verified=true
route_completion_verified=false
route_benchmark_verified=false
leaderboard_evaluated=false
```

The runner attempted CARLA `GlobalRoutePlanner`, but the local CARLA Python 3.12 environment lacked `networkx`; this was recorded as `goal_reach_controller_fallback`, and the runner used its scoped spawn-pair linear follower. This does not modify VLM, SafetyGate, SemanticPlanner, or the baseline CARLA control mapper.

This is still not a formal route benchmark, infraction benchmark, or CARLA Leaderboard result.

## Phase 11M — GRP-backed Route Following & Benchmark Boundary Preparation

Phase 11M upgrades Phase 11L by requiring CARLA `GlobalRoutePlanner` route generation and GRP-backed route following:

- requested route town: `Town03`
- CARLA runtime map: `Town03_Opt`
- start spawn index: `3`
- end spawn index: `30`
- goal tolerance: `3.0m`
- target speed: `18 km/h`
- GRP dependency: `networkx>=3,<4` installed in `D:\CARLA\envs\ma-vlna-carla312`

Evidence directory:

```text
runtime_logs\carla_runs\20260614T173740Z
```

Final status:

```text
Phase 11M GRP Route Following Pass — strict GRP-backed fixed-route goal-reach gate passed.
```

Measured GRP route metrics:

```text
steps_completed=2500
grp_route_required=true
grp_route_available=true
grp_route_source=carla_global_route_planner
grp_route_waypoint_count=267
grp_route_distance_m=525.559609
grp_route_following_verified=true
grp_fallback_used=false
goal_reach_step=2073
distance_to_goal_m=2.283447
fixed_route_goal_reached=true
fixed_route_completion_verified=true
```

Benchmark boundary evidence remains explicit:

```text
benchmark_boundary_prepared=true
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

The Phase 11M runner uses a scoped GRP route-following control adapter and does not modify VLM, SafetyGate, SemanticPlanner, the baseline CARLA control mapper, or baseline requirements.

This is still fixed spawn-pair smoke validation only, not a formal route benchmark, infraction benchmark, or CARLA Leaderboard result.

## Phase 11N — Git Snapshot, Artifact Boundary & Release Packaging

Phase 11N packages the Phase 11M result into a reviewable release artifact:

- git snapshot recorded without staging, committing, tagging, or pushing
- artifact boundary written to `artifact_boundary.json`
- Phase 11M evidence copied from `runtime_logs\carla_runs\20260614T173740Z`
- secret-like `.env*` files, local environments, transient logs, and legacy face assets excluded
- release zip and SHA-256 checksum generated

Release directory:

```text
release_artifacts\<timestamp>
```

Final status:

```text
Phase 11N Release Packaging Pass — git snapshot, artifact boundary, and release package generated.
```

Release package:

```text
ma-vlna_phase11n_release_<timestamp>.zip
sha256=<recorded in package.sha256>
```

Git snapshot:

```text
branch=master
head_short=d2a6d20
status_clean=false
status_entry_count=<recorded in git_snapshot.txt>
tracked_file_count=11
```

Artifact boundary:

```text
source_file_count=<recorded in manifest.json>
evidence_file_count=6
secret_file_boundary_verified=true
benchmark_boundary_prepared=true
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

This is a release artifact boundary only. It does not claim a clean git release commit, formal route benchmark, infraction benchmark, or CARLA Leaderboard result.

## Phase 11O — Source Commit Boundary & Draft PR Preparation

Phase 11O converts the Phase 11N workspace artifact snapshot into a reviewable source boundary:

- source/docs/config/frontend/backend/shared/workers/scripts/migrations are eligible for commit
- `runtime_logs/`, `release_artifacts/`, local envs, caches, transient logs, and `.env` files stay out of git
- `scripts\run_phase11o_source_commit_checks.py` validates the staged-file boundary before commit
- `docs\phase11o_source_commit_boundary_draft_pr.md` contains a copy-paste Draft PR body

Final status:

```text
Phase 11O Source Commit Boundary Pass — source-only commit boundary prepared, staged boundary gate added, and Draft PR body prepared locally.
```

Boundary evidence:

```text
source_commit_boundary_verified=true
draft_pr_prepared=true
remote_pr_created=false
tag_created=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

This phase prepares a local branch/commit and Draft PR handoff. It does not push to origin, open a remote pull request, create a git tag, or upgrade the CARLA smoke evidence into a formal benchmark claim.

## Phase 12 Handoff — Experiment Kickoff

Phase 12 begins experiment planning and controlled experiment scaffolding. Phase 11 remains the CARLA runtime verification and evidence-pack foundation.

Phase 12 starts from the Phase 11M/11N/11O boundaries and prepares:

- multi-route CARLA route smoke scaling
- controller ablation
- perception backend ablation
- VLM trigger / no-VLM comparison
- evidence aggregation under `experiments/phase12/<timestamp>/`

Scaffold command:

```powershell
python scripts\run_phase12_experiment_plan.py --output-dir experiments\phase12
```

Phase 12 kickoff does not run CARLA, does not import `carla`, does not require Python 3.12, and does not claim CARLA Leaderboard, formal route benchmark, infraction benchmark, or driving policy quality.

## Closed-Loop Runner

最小 CARLA closed-loop：

```powershell
python -m workers.CARLA_Closed_Loop_Agent --steps 100 --perception-backend dummy
```

指定 CARLA server：

```powershell
python -m workers.CARLA_Closed_Loop_Agent --host 127.0.0.1 --port 2000 --steps 200
```

指定 town 與 spawn point：

```powershell
python -m workers.CARLA_Closed_Loop_Agent --town Town03 --spawn-point-index 3 --steps 200
```

啟用 VLM optional path：

```powershell
python -m workers.CARLA_Closed_Loop_Agent --enable-vlm --vlm-provider local_stub --force-vlm-every 20 --steps 100
```

> 預設不啟用 VLM。Phase 11 的首要成功條件是 CARLA closed-loop 能跑通，而不是每幀或每個事件都呼叫 Gemma/OpenAI-compatible VLM。

## 控制映射

`PlannerActionToCarlaControl` 只使用 `PlannerAction.action_sequence[0]`。

原因：closed-loop prototype 應在每個 `world.tick()` 重新感知、重新規劃，而不是把長序列直接 replay 到車輛。

| Planner action | CARLA control |
|---|---|
| `forward` / `slow_forward` | throttle > 0, steer 由 `steering_deg` 或方向推導 |
| `turn_left` | throttle > 0, steer < 0 |
| `turn_right` | throttle > 0, steer > 0 |
| `reverse` | throttle > 0, reverse = true |
| `stop` / `wait` | throttle = 0, brake > 0 |

所有 VLM 輸出仍必須經過 `SafetyGate` 與 `SemanticPlanner`，VLM 不會直接產生 CARLA `VehicleControl`。

## Telemetry / Replay

Phase 11 runner 會發佈：

- `vehicle_status`
- `scene_logs`
- `trigger_events`
- `telemetry_entries`

當 Supabase 不可用時，既有 `TelemetryPublisher` 會退回本地：

```text
runtime_logs/telemetry_fallback.jsonl
```

這讓 CARLA closed-loop 原型可以在純本機環境中先驗證，再接 Dashboard Replay。

## 本階段成功標準

- CARLA client 可連線 server。
- Ego vehicle 能 spawn。
- RGB camera sensor 能提供 OpenCV BGR frame。
- EdgePerception 能處理 CARLA frame。
- PlannerAction 能映射成 CARLA VehicleControl。
- world tick 與 control loop 可持續執行指定步數。
- Telemetry / scene logs 可寫入 Supabase 或 fallback JSONL。
- 未安裝 CARLA 時，Phase 11 smoke checks 仍可通過。

## 驗證狀態語意

| 狀態 | 含義 |
|---|---|
| Partial Pass | CARLA integration path prepared；import / mapping / fallback verified |
| Core Runtime Pass | 使用 fake CARLA runtime 跑過 closed-loop orchestration；不需要 CARLA server |
| Phase 11B Skipped | Real CARLA smoke gate 已建立，但目前環境缺少 `carla` wheel 或 CARLA server |
| Phase 11C Blocked Locally | 已用 `--require-server` 嘗試真實 runtime execution，但本機缺少 `carla` wheel 或 reachable server |
| Phase 11D Provisioning Blocked | 已用 read-only provisioning gate 拆解缺失；本機 CARLA package、wheel、process 或 TCP endpoint 尚未 ready |
| Phase 11E Unlock Kit Ready | 已提供可重跑的環境解鎖腳本與 runbook；外部 CARLA runtime 尚未 provisioned 前不得升級 11C |
| Phase 11F Blocked | 已檢查 `CARLA_ROOT` 與常見位置，但沒有有效 CARLA server package root |
| Phase 11G Blocked | CARLA package 已下載/解壓至 D 槽，但 active Python 與 package wheel ABI 不相容 |
| Phase 11H Pass | 使用 dedicated Python 3.12 env 安裝 CARLA 0.9.16 cp312 wheel，啟動真實 server，通過 11D ready 與 11C 5/50-step smoke |
| Phase 11I Evidence Pack Pass | 已產生 manifest、metrics、events、commands、environment、regression，支援 5/50-step real smoke 審核 |
| Phase 11J Sensor Metrics Pass | 已在真實 CARLA smoke 中掛載 collision/lane sensors，並量測 speed/distance |
| Phase 11K Fixed Route Smoke Pass | 已在真實 CARLA smoke 中建立固定 spawn-pair route，並量測 route progress |
| Phase 11L Fixed Route Completion Pass | 已在真實 CARLA smoke 中通過 strict fixed spawn-pair goal-reach gate |
| Phase 11M GRP Route Following Pass | 已在真實 CARLA smoke 中使用 GlobalRoutePlanner route-following 通過 strict goal-reach gate，並保留 benchmark boundary |
| Phase 11N Release Packaging Pass | 已產生 git snapshot、artifact boundary、checksums 與 release zip；未建立 git commit/tag |
| Phase 11O Source Commit Boundary Pass | 已建立 source-only commit boundary、staged-file gate 與 Draft PR body；未 push、未建立遠端 PR 或 git tag |
| CARLA Server Runtime Pass | 已連線真實 CARLA server，完成 ego spawn、RGB camera、world.tick 與 VehicleControl |

## 非目標

- 不做 CARLA Leaderboard。
- 不做完整 HD map / rule-based driving stack。
- 不把 VLM 直接接到 `VehicleControl`。
- 不要求 ROS2。
- 不要求真實 GPU / YOLO / Gemma 才能啟動閉環。
