# MA-VLNA Release Checklist

> 版本發佈前驗證清單 — 記錄所有驗證結果與待辦事項 (v0.3.1 Release)

---

## ✅ Completed & Verified（已完成且驗證之主要工程閉環）

### Core Integration
- [x] **Supabase Real Integration**: 真實資料庫連線、pgvector HNSW 索引、RPC 檢索與前端即時讀取功能皆已完成驗證。
- [x] **Camera / Mock Mode Runtime**: 攝影機介面與模擬迴圈（12 步自動駕駛主迴圈）執行穩定無崩潰。
- [x] **SafetyGate Final Regression**: 仲裁機制全面覆蓋（信心不足、超速、禁止動作、嚴重危害與 Fallback 攔截）。
- [x] **VLM Reasoning Trace Pipeline**: 感知 -> 觸發 -> 推理 -> 安全仲裁 -> 規劃 -> 遙測，完整決策鏈寫入。
- [x] **.env / API Key Safety Audit**: 專案已完全排除 hardcoded keys，`.env.example` 僅存放 placeholder。

### Edge AI Perception
- [x] **Edge AI Perception Abstraction**: 支援標準化的物件偵測介面與統一的 `PerceptionResult` Schema。
- [x] **YOLO / RT-DETR Optional Backend**: 支援外掛式載入。
- [x] **Graceful Fallback**: 若環境缺乏模型、權重或 `ultralytics`，完美降級至 `DummyPerceptionBackend`，不引發 Crash。

### CARLA / Phase 11
- [x] **Phase 11 No-Server Smoke Checks**: `scripts/run_phase11_carla_checks.py` 可在沒有 CARLA server 與 `carla` wheel 的環境下驗證 import、設定載入與 control mapping。
- [x] **Phase 11 Core Runtime Verification**: `scripts/run_phase11_core_runtime_checks.py` 使用 fake CARLA runtime 跑通 local planner 與 LocalStub VLM 兩條 closed-loop orchestration。
- [x] **Phase 11B Real CARLA Smoke Gate**: `scripts/run_phase11b_real_carla_smoke.py` 已建立真實 server preflight / skipped / required-fail 語意。
- [x] **Phase 11B Environment Setup Guide**: `docs/phase11b_real_carla_environment_setup.md` 已補齊 CARLA package、Python wheel、server 啟動、preflight、smoke test 與 troubleshooting 流程。
- [x] **Phase 11C Runtime Execution Attempt**: 已使用 `--require-server` 嘗試真實 CARLA runtime；本機缺少 `carla` wheel 且 `127.0.0.1:2000` 不可達，因此紀錄為 blocked locally。
- [x] **Phase 11D Provisioning Gate**: `scripts/run_phase11d_carla_provisioning_gate.py` 已建立 read-only provisioning gate；目前結果為 blocked，會以 `--require-ready` exit 1 擋下未 provisioned 的 runtime。
- [x] **Phase 11E Unlock Kit**: `scripts/phase11e_unlock_carla_environment.ps1` 已建立 Windows unlock helper，可在指定 `CARLA_ROOT` 後安裝 wheel、啟動 server、重跑 11D 與 11C gate。
- [x] **Phase 11F External CARLA Provisioning Attempt**: 已檢查 `CARLA_ROOT`、`C:\`、`D:\` 與 Downloads；未找到有效 CARLA server package root，因此停止於 blocker，未安裝 wheel、未啟 server、未跑 real runtime smoke。
- [x] **Phase 11G Automated D Drive Provisioning Attempt**: 已下載並解壓 CARLA 0.9.16 Windows package 到 `D:\CARLA`，但 package wheel 為 CPython 3.12，與目前 Python 3.10.14 不相容，因此停止於 wheel install blocker。
- [x] **Phase 11H Python 3.12 CARLA Runtime Environment**: 已建立 `D:\CARLA\envs\ma-vlna-carla312`，安裝 CARLA 0.9.16 `cp312` wheel，啟動真實 CARLA server，並通過 11D `--require-ready`、11C 5-step 與 50-step `--require-server` smoke。
- [x] **Phase 11I CARLA Runtime Evidence Pack**: 已產生 `runtime_logs\carla_runs\20260613T073948Z`，包含 manifest、metrics、events、commands、environment、regression 與 raw stdout/stderr，支援 5/50-step real smoke 審核。
- [x] **Phase 11J CARLA Sensor Metrics Instrumentation**: 已產生 `runtime_logs\carla_runs\20260613T082452Z`，在真實 CARLA smoke 中掛載 collision/lane invasion sensors，並量測 speed 與 distance。
- [x] **Phase 11K Fixed Route Scenario Smoke**: 已產生 `runtime_logs\carla_runs\20260613T092548Z`，在真實 CARLA smoke 中建立 `Town03` spawn-pair route，並量測 route progress。
- [x] **Phase 11L Fixed Route Completion Attempt**: 已產生 `runtime_logs\carla_runs\20260613T130532Z`，在真實 CARLA smoke 中通過 strict fixed spawn-pair goal-reach gate。
- [x] **Phase 11M GRP-backed Route Following**: 已產生 `runtime_logs\carla_runs\20260614T173740Z`，在真實 CARLA smoke 中使用 CARLA `GlobalRoutePlanner` route-following 通過 strict goal-reach gate，並保留 benchmark boundary。
- [x] **Phase 11N Git Snapshot & Release Packaging**: 已產生 timestamped `release_artifacts` package，包含 git snapshot、artifact boundary、checksums 與 release zip；精確路徑與 SHA-256 以 generated `manifest.json` / `package.sha256` 為準。
- [x] **Phase 11O Source Commit Boundary & Draft PR Preparation**: 已新增 staged-file boundary gate 與 Draft PR handoff 文件，將 source commit 與 runtime/release artifacts 明確分離。
- [x] **Phase 12 Experiment Kickoff Preparation**: 已新增 experiment kickoff plan 與 scaffold script；此階段只建立計畫與輸出格式，不啟動 CARLA 或大型實驗。
- [x] **Phase 12A CARLA Route Scaling Evidence Produced**: 已在真實 CARLA runtime 執行 5-route `Town03` GRP smoke batch，產生 aggregate evidence；4/5 routes passed，`route_05` 因 strict goal-reach failure 使 all-route gate 保持 blocked。
- [x] **Phase 12A-R05 Failure Diagnosis & Recovery Evidence**: 已執行 Route 05 專用 recovery-variant runner；4 個 conservative variants 均未達 strict goal tolerance。`r05_slow_short_lookahead` 無碰撞且進度提升至 71.07%，但 Phase 12A-R05 仍保持 blocked。

### VLM Reasoner
- [x] **VLMReasoner Provider Abstraction**: 定義清楚的 VLM 介面，統一回傳 `VLMOutput`。
- [x] **OpenAI-Compatible VLM Provider**: 支援通用 OpenAI 格式的模型（如 GPT-4V, Gemma 4）。
- [x] **Graceful Fallback**: 若 VLM 未配置 API 金鑰、網路逾時或解析失敗，完美降級至 `LocalStubReasoner` 產出安全預設值。
- [x] **Demo Trigger (`--force-vlm-every`)**: 支援強制週期觸發機制，且不受 Cooldown 阻擋，方便展示。

---

## 🔶 Graceful Fallback Confirmed (尚未經過 Real Backend 全面測試)

雖然框架已具備對接真實後端的能力並能安全降級，但考量到開發者機器環境，以下「真實模型」的效能與準確率**尚未進行大規模硬體驗證**。請勿聲稱其具有真實世界的泛化能力。

- **Real YOLO / RT-DETR Inference**: 目前皆是在缺少依賴的情況下測試其 Fallback 能力，並未以 GPU 實際負載真實路況。
- **Real VLM Endpoint Connection**: 驗證了 API 金鑰缺乏與逾時的 Fallback 防護，端對端的真實 GPT-4V 推論需由終端使用者提供金鑰。
- **Real CLIP / SigLIP Embeddings**: 框架具備調用 `open-clip-torch` 的能力，目前依賴 `DummyEmbeddingBackend` 以保證 Mock 模式無痛執行。
- **Real CARLA Server Runtime**: Phase 11H 已在 dedicated Python 3.12 environment 中完成 CARLA 0.9.16 真實 server runtime smoke。Base Python 3.10 仍保留 no-server/fallback 驗證路徑，不把 `carla` 加入 baseline requirements。
- **CARLA Smoke Evidence Pack**: Phase 11I 已提供 structured metrics 與 event logs。這不是 route benchmark，也不包含 collision/lane invasion sensor 指標。
- **CARLA Sensor Metrics Smoke**: Phase 11J 已驗證 collision/lane sensors 可掛載並寫入 metrics；`collision_count=0` 與 `lane_invasion_count=0` 是 sensor-attached 後的實測 smoke 結果，不是 infraction benchmark。
- **CARLA Fixed Route Progress Smoke**: Phase 11K 已驗證固定 spawn-pair route progress 可寫入 metrics；`route_progress_verified=true` 只代表 smoke 門檻通過，不是 route completion benchmark。
- **CARLA Fixed Route Goal-Reach Smoke**: Phase 11L 已驗證 `distance_to_goal_m <= 3.0` 的 strict fixed spawn-pair gate；`fixed_route_completion_verified=true` 不等同 CARLA Leaderboard 或正式 route benchmark。
- **CARLA GRP Route-Following Smoke**: Phase 11M 已驗證 `GlobalRoutePlanner` route generation 與 runner-only GRP waypoint following；`grp_route_following_verified=true` 與 `fixed_route_completion_verified=true` 仍只代表 fixed spawn-pair smoke gate，不等同 CARLA Leaderboard、正式 route benchmark 或 infraction benchmark。
- **Release Artifact Boundary**: Phase 11N 已產生 release zip 與 checksum；`status_clean=false` 被記錄於 git snapshot，代表這是 workspace artifact snapshot，不是 clean git commit/tag release。
- **Source Commit Boundary**: Phase 11O 已準備 source-only commit boundary 與 Draft PR body；runtime logs、release artifacts、local envs 與 `.env` 仍不得進入 git。遠端 Draft PR、git tag 與 push 需另行執行。
- **Experiment Kickoff Scaffold**: Phase 12 已建立 controlled experiment planning scaffold；`experiments/phase12/*/runs/` 與 `experiments/phase12/*/raw_outputs/` 不得提交，kickoff 不等於正式實驗結果。
- **Route Scaling Experiment**: Phase 12A 已產生 real CARLA 5-route aggregate evidence；`passed_count=4` 與 `route_05 goal_reach_blocked` 只代表 controlled fixed spawn-pair smoke 結果，不等同 CARLA Leaderboard、正式 route benchmark 或 infraction benchmark。

---

## ❌ Not Yet Verified / Future Work（尚未驗證/未來規劃）

### ROS2 / Isaac Sim Integration
- `ROS2SimulatorAdapter` 與 `IsaacSimAdapter` 目前為 stub（`NotImplementedError`）。需要真實的 ROS2 Humble 環境與 Isaac Sim 實體連線測試。

### Production Deployment
- Docker / Docker Compose 容器化部署環境設定。
- Frontend (Next.js) 的生產環境部署 (如 Vercel 或 Cloudflare Pages)。
- Supabase 的 Realtime WebSocket 深度訂閱優化。

---

## 📊 驗證覆蓋率摘要

| 類別 | 完成 | 部分 | 未驗證 | 狀態 |
|------|------|------|--------|--------|
| **Python Workers Core** | 100% | — | — | 🟢 Pass |
| **FastAPI Backend** | 100% | — | — | 🟢 Pass |
| **Frontend Build** | 100% | — | — | 🟢 Pass |
| **VLM Fallback / Stub** | 100% | — | — | 🟢 Pass |
| **Real VLM API** | — | 100% | — | 🟡 Fallback Confirmed |
| **Real YOLO / CV** | — | 100% | — | 🟡 Fallback Confirmed |
| **Database Integration**| 100% | — | — | 🟢 Pass |
| **CARLA Fake Runtime** | 100% | — | — | 🟢 Pass |
| **CARLA Real Server** | 100% | — | — | 🟢 Phase 11H Pass |
| **CARLA Runtime Evidence Pack** | 100% | — | — | 🟢 Phase 11I Pass |
| **CARLA Sensor Metrics Smoke** | 100% | — | — | 🟢 Phase 11J Pass |
| **CARLA Fixed Route Progress Smoke** | 100% | — | — | 🟢 Phase 11K Pass |
| **CARLA Fixed Route Goal-Reach Smoke** | 100% | — | — | 🟢 Phase 11L Pass |
| **CARLA GRP Route-Following Smoke** | 100% | — | — | 🟢 Phase 11M Pass |
| **Release Artifact Packaging** | 100% | — | — | 🟢 Phase 11N Pass |
| **Source Commit Boundary** | 100% | — | — | 🟢 Phase 11O Pass |
| **Experiment Kickoff Scaffold** | 100% | — | — | 🟢 Phase 12 Kickoff Pass |
| **CARLA Route Scaling Experiment** | — | 100% | — | 🟡 Phase 12A Evidence Produced |
| **Route 05 Recovery Smoke** | — | 100% | — | 🟡 Phase 12A-R05 Blocked |
| **生產容器化部署** | 0% | — | 100% | 🔴 TODO |

## 🚧 Explicitly Not Verified

- [ ] CARLA formal route benchmark verified
- [ ] CARLA infraction benchmark verified
- [ ] CARLA Leaderboard passed
- [x] Source-only local commit boundary prepared
- [ ] Remote Draft PR opened
- [ ] Clean git tag release created
- [ ] Real YOLO / RT-DETR verified
- [ ] Real OpenAI-compatible VLM verified

> **總結**：目前專案處於 **v0.3.1 (Release Candidate)**，非常適合用於作品集展示與架構概念性驗證 (PoC)。核心的決策管線 (Pipeline)、防呆降級 (Graceful Fallback) 與資料流串接已全數打通。
