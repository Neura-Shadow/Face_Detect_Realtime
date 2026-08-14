# Phase 11D — CARLA Runtime Provisioning Gate

## 結論

Phase 11C 狀態必須嚴格維持為：

```text
Phase 11C Blocked Locally — real CARLA runtime execution attempted with --require-server, but local environment lacks both carla Python package and reachable CARLA server.
```

Phase 11D 新增的是 provisioning gate，不是 runtime pass：

```text
Phase 11D Provisioning Gate Blocked — read-only preflight confirms CARLA runtime prerequisites are still missing locally.
```

Phase 11F 已確認 `CARLA_ROOT` 未設定，且 `C:\`、`D:\`、`Downloads` 常見位置沒有有效 CARLA package root。11D 仍為 blocked；這不是 MA-VLNA 核心程式問題。

Phase 11G 已下載並解壓 CARLA 0.9.16 到 `D:\CARLA\packages\CARLA_0.9.16`。11D 現在可看到 package root 與 `CarlaUE4.exe`，但仍 blocked，原因是 package 內 wheel 為 `cp312`，不支援目前 Python 3.10.14 interpreter。

Phase 11H 使用 dedicated Python 3.12 environment 重新執行 11D。此時 `carla` wheel、server process 與 TCP endpoint 皆通過：

```text
Phase 11D Provisioning Gate Ready — Python 3.12 CARLA runtime prerequisites are provisioned locally.
```

## 新增 Gate

```text
scripts/run_phase11d_carla_provisioning_gate.py
```

此腳本只做 read-only preflight，不會下載、不會安裝、不會啟動 CARLA。它檢查：

- Python interpreter 與版本。
- 目前 interpreter 是否可 import `carla`。
- `pip show carla` metadata。
- `CARLA_ROOT` / `CARLA_HOME` / 常見路徑中的 CARLA package root。
- `CarlaUE4` / `CarlaUnreal` server executable。
- package 內 `carla-*.whl` candidate。
- 本機 CARLA / UE4 / Unreal process。
- `CARLA_HOST:CARLA_PORT` TCP endpoint。

## 執行時間與環境

| 項目 | 值 |
|---|---|
| 執行時間 | 2026-06-12 16:17:54 +08:00 |
| Workspace | `D:\Face_Detect_Realtime` |
| Python | `C:\Users\zongx\anaconda3\python.exe` |
| Python version | `3.10.14` |
| Target endpoint | `127.0.0.1:2000` |

## 執行指令

一般紀錄模式，blocked 時 exit 0：

```powershell
python scripts\run_phase11d_carla_provisioning_gate.py
```

正式 provisioning gate，blocked 時 exit 1：

```powershell
python scripts\run_phase11d_carla_provisioning_gate.py --require-ready
```

JSON 模式：

```powershell
python scripts\run_phase11d_carla_provisioning_gate.py --json
```

## 本機結果

```text
Phase 11D — CARLA Runtime Provisioning Gate
status: blocked
target: 127.0.0.1:2000

[PASS] python_interpreter: C:\Users\zongx\anaconda3\python.exe (3.10.14)
[FAIL] carla_python_package: carla Python package is not importable in the active interpreter.
[WARN] pip_package_metadata: WARNING: Package(s) not found: carla
[WARN] carla_server_package_root: candidate roots: C:\Users\zongx\carlaCache (no CARLA server executable or carla wheel found under these roots)
[FAIL] carla_server_executable: No CarlaUE4/CarlaUnreal server executable found locally.
[FAIL] carla_wheel_candidate: No local carla-*.whl candidates found under CARLA package roots.
[FAIL] carla_server_process: No local CARLA/UE4/Unreal process found.
[FAIL] carla_tcp_endpoint: 127.0.0.1:2000 is not reachable.

phase11d carla provisioning gate blocked
```

`--require-ready` 已確認會以 exit code 1 擋下後續 11C runtime execution。

Phase 11 no-server umbrella gate 已納入 11D provisioning gate；它只驗證 gate 可穩定產出狀態，不要求本機 CARLA runtime 已 ready：

```powershell
python scripts\run_phase11_carla_checks.py
```

目前驗證結果：

```text
python scripts\run_phase11_carla_checks.py
Phase 11 驗證總結: 6/6 passed

python scripts\run_demo_checks.py
驗證總結: 6/6 測試通過
```

## 解鎖順序

1. 下載並解壓 CARLA server package。
2. 設定 `CARLA_ROOT` 指向 package root。
3. 使用同一個 Python interpreter 安裝 package 內的 `PythonAPI/carla/dist/carla-*.whl`。
4. 啟動 CARLA server。
5. 確認 `127.0.0.1:2000` TCP 可達。
6. 重跑：

```powershell
python scripts\run_phase11d_carla_provisioning_gate.py --require-ready
```

7. 只有 11D ready 後，才重跑 11C：

```powershell
python scripts\run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 5 --require-server
```

## Phase 11H 後續 ready 結果

Phase 11H 指令：

```powershell
$env:CARLA_ROOT="D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11d_carla_provisioning_gate.py --carla-root $env:CARLA_ROOT --host 127.0.0.1 --port 2000 --steps 5 --require-ready
```

結果：

```text
status: ready
[PASS] python_interpreter: D:\CARLA\envs\ma-vlna-carla312\python.exe (3.12.13)
[PASS] carla_python_package
[PASS] pip_package_metadata: carla 0.9.16
[PASS] carla_server_package_root
[PASS] carla_server_executable
[PASS] carla_wheel_candidate
[PASS] carla_server_process
[PASS] carla_tcp_endpoint
phase11d carla provisioning gate ready
```

## 宣告事項

Phase 11G 以前不可宣告：

```text
Phase 11C Pass
CARLA Server Runtime Pass
Real CARLA closed-loop verified
```

Phase 11H 之後，在 dedicated Python 3.12 runtime 與 running CARLA server 條件下，可以宣告：

```text
Phase 11D Provisioning Gate Ready — required CARLA runtime prerequisites are provisioned locally.
```
