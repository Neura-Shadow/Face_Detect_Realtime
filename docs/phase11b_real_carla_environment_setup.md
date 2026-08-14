# Phase 11B — Real CARLA Environment Setup Guide

## 目前狀態

```text
Phase 11B Skipped — real CARLA server smoke gate is ready; local CARLA wheel/server unavailable.
```

這份指南的目標，是把 Phase 11B 從「工程 gate 已建立」推進到可在真實 CARLA 環境重跑的驗收流程。Phase 11B 不使用 fake CARLA adapter；它驗證的是：

```text
CARLA server
-> CARLA Python client
-> ego vehicle spawn
-> RGB camera sensor
-> CarlaClosedLoopAgent
-> EdgePerception
-> SafetyGate / PlannerAction
-> CARLA VehicleControl
-> world.tick()
-> telemetry fallback 或 Supabase
```

> 官方 quickstart 說明 packaged CARLA 版本包含 server 與 Python client library，並以 2000 / 2001 作為預設 TCP ports。請以官方文件與實際下載版本為準：  
> https://carla.readthedocs.io/en/latest/start_quickstart/

## 驗收狀態語意

| 狀態 | 含義 |
|---|---|
| `Phase 11B Skipped` | `run_phase11b_real_carla_smoke.py` 已存在，但目前機器缺少 `carla` wheel、CARLA server 未啟動，或 TCP endpoint 不可達。 |
| `Phase 11B Preflight Pass` | Python 可 import `carla`，且 `CARLA_HOST:CARLA_PORT` 可連線；尚未執行 closed-loop tick。 |
| `Phase 11B Real CARLA Server Runtime Smoke Pass` | 已使用真實 CARLA server 跑過 `setup -> tick -> control -> cleanup`。 |
| `Phase 11B Failed` | 前提成立後執行失敗，例如 spawn 失敗、camera frame timeout、VehicleControl 套用失敗或 cleanup 例外。 |

## 版本原則

1. CARLA server package 與 Python client wheel 必須同版。
2. Phase 11B 需在能 `import carla` 的 Python interpreter 中執行。
3. 若 CARLA release 只提供特定 Python ABI 的 wheel，請建立一個 CARLA 專用 venv，並在該 venv 安裝 MA-VLNA worker 依賴。
4. 不要把 `carla` 加入必要依賴；它仍是 optional runtime dependency。

官方 quickstart 提供兩條 client library 路徑：

- 官方 release 可嘗試 `python -m pip install carla`。
- package 內通常提供 `PythonAPI/carla/dist/*.whl`，自訂 package 或 `CARLA-latest` 應使用 package 內附 wheel。

## Windows 建置流程

以下以 PowerShell 與 Windows package 為主。請將 `C:\CARLA\CARLA_0.9.x` 替換成實際解壓路徑。

### 1. 建立或啟用 Python 環境

```powershell
cd D:\Face_Detect_Realtime
python -m venv .venv-carla
.\.venv-carla\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r workers\requirements.txt
```

若你的 CARLA wheel 不支援目前 Python 版本，請建立與 wheel ABI 相容的 Python 環境，再安裝同一組 worker requirements。

### 2. 安裝 CARLA Python client

優先使用與 server package 同版的 wheel：

```powershell
python -m pip uninstall -y carla
python -m pip install "C:\CARLA\CARLA_0.9.x\PythonAPI\carla\dist\<carla-wheel-file>.whl"
```

若使用官方 PyPI release：

```powershell
python -m pip uninstall -y carla
python -m pip install carla
```

驗證目前 interpreter 可 import：

```powershell
python -c "import sys, carla; print(sys.executable); print(carla.__file__)"
```

### 3. 啟動 CARLA server

開另一個 PowerShell 視窗：

```powershell
cd C:\CARLA\CARLA_0.9.x
.\CarlaUE4.exe -quality-level=Low
```

若你使用自訂 RPC port，請在 Phase 11B 指令同步使用相同 `--port`。

### 4. 檢查 TCP port

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 2000
```

期望 `TcpTestSucceeded: True`。若失敗，先檢查 CARLA 視窗是否仍在、Windows Firewall、port 是否被占用，以及 server 是否使用不同 RPC port。

### 5. 跑 Phase 11B preflight

```powershell
python scripts\run_phase11b_real_carla_smoke.py --preflight-only --require-server
```

期望輸出：

```text
phase11b real carla preflight passed
```

### 6. 跑 Phase 11B 真實 closed-loop smoke

先使用最低風險設定：dummy perception、低解析度 camera、不啟用 VLM、不寫 Supabase。

```powershell
python scripts\run_phase11b_real_carla_smoke.py `
  --host 127.0.0.1 `
  --port 2000 `
  --steps 5 `
  --camera-width 320 `
  --camera-height 180 `
  --perception-backend dummy `
  --require-server
```

期望輸出：

```text
phase11b real carla smoke passed
```

通過後，才逐步增加步數：

```powershell
python scripts\run_phase11b_real_carla_smoke.py --steps 50 --require-server
```

## Linux / WSL 注意事項

CARLA server 通常需要 GPU 與圖形環境。若 server 跑在 Windows，client 跑在 WSL 或另一台機器，請確認：

- `--host` 指向 CARLA server 所在 IP，不一定是 `127.0.0.1`。
- Windows Firewall 允許 CARLA RPC port。
- CARLA server 與 Python client wheel 版本一致。
- 若使用 Docker CARLA，container 的 RPC ports 已正確 publish。

Linux package 啟動通常使用：

```bash
./CarlaUE4.sh -quality-level=Low
```

client 端驗收：

```bash
python scripts/run_phase11b_real_carla_smoke.py --host <server-ip> --port 2000 --steps 5 --require-server
```

## MA-VLNA 設定欄位

Phase 11B 可透過 CLI 覆寫 `config/agent_config.yaml` 的 `carla:` 設定：

| 欄位 / 參數 | 用途 |
|---|---|
| `CARLA_HOST` / `--host` | CARLA server host，預設 `127.0.0.1`。 |
| `CARLA_PORT` / `--port` | CARLA RPC port，預設 `2000`。 |
| `CARLA_TOWN` / `--town` | 指定載入 town；留空代表使用目前 server world。 |
| `CARLA_SPAWN_POINT_INDEX` / `--spawn-point-index` | ego vehicle spawn point。spawn 失敗時先換 index。 |
| `CARLA_SYNC_MODE` / `--async-world` | 預設同步 tick；`--async-world` 可停用同步模式。 |
| `CARLA_CAMERA_WIDTH` / `--camera-width` | Phase 11B 建議先用 `320` 降低 smoke test 負載。 |
| `CARLA_CAMERA_HEIGHT` / `--camera-height` | Phase 11B 建議先用 `180` 降低 smoke test 負載。 |

預設不寫 Supabase，避免真實 CARLA smoke 被雲端狀態阻塞。若要把 telemetry 寫回 Supabase：

```powershell
python scripts\run_phase11b_real_carla_smoke.py --steps 5 --publish-telemetry --require-server
```

## Optional VLM Path

Phase 11B 首次驗收不建議啟用 VLM。確認真實 server loop 穩定後，再使用 LocalStub 驗證語義路徑：

```powershell
python scripts\run_phase11b_real_carla_smoke.py `
  --steps 10 `
  --enable-vlm `
  --vlm-provider local_stub `
  --force-vlm-every 2 `
  --require-server
```

不要在 Phase 11B 首次驗收中直接使用遠端 VLM provider。真實 CARLA server smoke 的核心目標是 simulation bridge，而不是測 API latency。

## 常見失敗與處理

| 現象 | 可能原因 | 處理方式 |
|---|---|---|
| `carla Python package not installed` | 目前 Python 環境沒有 client wheel。 | 使用同一個 interpreter 安裝與 server package 同版的 `carla` wheel。 |
| `TCP endpoint unreachable` | CARLA server 未啟動、port 不同、Firewall 阻擋。 | 啟動 `CarlaUE4.exe`，確認 `Test-NetConnection` 成功，或改用正確 `--host/--port`。 |
| `ModuleNotFoundError: carla` 但已安裝 | 裝在另一個 Python / conda / venv。 | `python -c "import sys; print(sys.executable)"` 確認 interpreter，重新安裝 wheel。 |
| import crash 或 RPC protocol error | server 與 wheel 版本不一致。 | 移除 `carla`，改裝 package 內 `PythonAPI/carla/dist` 的同版 wheel。 |
| `ego vehicle spawn 失敗` | spawn point 被占用或 map 不含該點。 | 重啟 server，或改 `--spawn-point-index 1`、`2`、`3`。 |
| `camera frame timeout` | server 卡頓、解析度太高、同步 tick 未正常推進。 | 降低 `--camera-width/--camera-height`，使用 `--steps 1` 重新測，必要時重啟 CARLA。 |
| `Supabase 無法初始化` | smoke test 預設關閉雲端寫入。 | 這是預期行為；需要雲端 telemetry 時才加 `--publish-telemetry`。 |

## 通過後的紀錄格式

Phase 11B 真實通過後，請在報告中記錄：

```text
Phase 11B Real CARLA Server Runtime Smoke Pass
- CARLA server: <version / package path>
- Python: <python --version>
- carla module: <carla.__file__>
- command: python scripts\run_phase11b_real_carla_smoke.py --steps 5 --require-server
- result: phase11b real carla smoke passed
```

如果仍缺環境，保留目前狀態：

```text
Phase 11B Skipped — real CARLA server smoke gate is ready; local CARLA wheel/server unavailable.
```

## 官方參考

- CARLA quickstart package installation: https://carla.readthedocs.io/en/latest/start_quickstart/
- CARLA downloads and versioned docs: https://carla.readthedocs.io/en/latest/download/
- CARLA Python API reference: https://carla.readthedocs.io/en/latest/python_api/
