# Phase 11C — Real CARLA Runtime Execution Report

## 原始 11C 結論

```text
Phase 11C Blocked Locally — real CARLA runtime execution attempted with --require-server, but local environment lacks both carla Python package and reachable CARLA server.
```

本階段目標是把 Phase 11B 的 real CARLA smoke gate 往前推進到實際執行。此次已使用正式驗收模式 `--require-server` 執行，但本機環境尚未具備真實 CARLA runtime 前提，因此不可宣稱 `CARLA Server Runtime Pass`。

Phase 11F 已進一步嘗試 external CARLA package provisioning，但本機仍沒有有效 `CARLA_ROOT`，也未找到包含 server executable 與 matching wheel 的 CARLA package root。因此 Phase 11C 狀態不變。

Phase 11G 後續已取得 CARLA 0.9.16 package 與 server executable，但 wheel install blocked，因為 `carla-0.9.16-cp312-cp312-win_amd64.whl` 不支援目前 Python 3.10.14。Phase 11C 仍未進入 real runtime smoke。

## Phase 11H 後續解鎖

Phase 11H 建立 dedicated Python 3.12 environment，安裝同一個 CARLA 0.9.16 package 內的 `cp312` wheel，啟動本機 `CarlaUE4.exe`，並從同一個 interpreter 通過 11D ready gate 與 11C real smoke：

```text
Phase 11H Pass — Python 3.12 CARLA runtime environment provisioned; Phase 11D ready gate passed; Phase 11C 5-step and 50-step real CARLA --require-server smoke tests passed.
```

因此，本文件中的 blocked 結論應視為 base Python 3.10 / Phase 11C 原始嘗試的歷史紀錄；目前的 real runtime unlock 證據以 [`docs/phase11h_python312_carla_runtime_environment.md`](phase11h_python312_carla_runtime_environment.md) 為準。

## 執行時間與環境

| 項目 | 值 |
|---|---|
| 執行時間 | 2026-06-11 19:20:08 +08:00 |
| Workspace | `D:\Face_Detect_Realtime` |
| Python | `C:\Users\zongx\anaconda3\python.exe` |
| Target CARLA endpoint | `127.0.0.1:2000` |
| Runtime mode | Real CARLA required gate |

## 11C 前置探測

### Python CARLA package

```powershell
python -c "import importlib.util, sys; spec=importlib.util.find_spec('carla'); print('python=' + sys.executable); print('carla_available=' + str(spec is not None)); print('carla_origin=' + str(spec.origin if spec else ''))"
```

結果：

```text
python=C:\Users\zongx\anaconda3\python.exe
carla_available=False
carla_origin=
```

### pip package

```powershell
python -m pip show carla
```

結果：

```text
WARNING: Package(s) not found: carla
```

### CARLA server TCP endpoint

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 2000
```

結果：

```text
TcpTestSucceeded: False
```

### CARLA process / common install path

已檢查執行中 process 與常見安裝路徑，未找到可直接啟動的 CARLA server package。

## 11C 正式 runtime gate

正式驗收指令：

```powershell
python scripts\run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 5 --require-server
```

結果：

```text
phase11b real carla smoke skipped: carla Python package not installed; CARLA server TCP endpoint unreachable at 127.0.0.1:2000
exit code: 1
```

`--require-server` 模式下 exit code 1 是正確行為，代表 11C 的真實 CARLA runtime 前提未成立，不能降級成 fake runtime，也不能改用 no-server gate 充當通過。

## 可宣告狀態

原始 Phase 11C 嘗試可宣告：

```text
Phase 11C Real CARLA Runtime Execution Attempted — blocked by missing local CARLA wheel/server.
```

Phase 11H 之後，在 `D:\CARLA\envs\ma-vlna-carla312\python.exe`、`CARLA_ROOT=D:\CARLA\packages\CARLA_0.9.16` 且 CARLA server running 的條件下，可以宣告：

```text
Phase 11C Pass — Real CARLA runtime executed through setup/tick/control/cleanup.
CARLA Server Runtime Pass — verified by 5-step and 50-step --require-server smoke.
```

## 歷史解鎖條件

1. 安裝與 CARLA server package 同版的 `carla` Python wheel。
2. 啟動 CARLA server，例如 Windows package 的 `CarlaUE4.exe -quality-level=Low`。
3. 確認 `Test-NetConnection -ComputerName 127.0.0.1 -Port 2000` 回傳 `TcpTestSucceeded: True`。
4. 在同一個 Python interpreter 重跑：

```powershell
python scripts\run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 5 --require-server
```

Phase 11H 已完成上述條件，狀態可升級為：

```text
Phase 11C Pass — Real CARLA runtime executed through setup/tick/control/cleanup.
```

## 關聯文件

- `docs/phase11b_real_carla_environment_setup.md`
- `docs/phase11_carla_closed_loop.md`
- `scripts/run_phase11b_real_carla_smoke.py`
