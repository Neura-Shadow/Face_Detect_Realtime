# Phase 11E — CARLA Runtime Environment Unlock

## 結論

Phase 11C 狀態必須嚴格維持為：

```text
Phase 11C Blocked Locally — real CARLA runtime execution attempted with --require-server, but local environment lacks both carla Python package and reachable CARLA server.
```

Phase 11E 新增的是 unlock kit，不是 runtime pass：

```text
Phase 11E Unlock Kit Ready — CARLA environment unlock helper and runbook added; local runtime remains blocked until a real CARLA root, wheel, server process, and TCP endpoint are present.
```

Phase 11F 已嘗試外部 CARLA package provisioning，但本機沒有有效 CARLA root，因此仍停在：

```text
Phase 11F Blocked — no valid CARLA server package found locally.
```

詳細紀錄請見 `docs/phase11f_external_carla_provisioning.md`。

Phase 11G later downloaded and extracted CARLA 0.9.16 to `D:\CARLA`, but the package wheel targets CPython 3.12 while the active interpreter is Python 3.10.14. Therefore the real runtime remained blocked before server launch and 11C smoke.

Phase 11H then created a dedicated Python 3.12 environment and completed the unlock path:

```text
Phase 11H Pass — Python 3.12 CARLA runtime environment provisioned; Phase 11D ready gate passed; Phase 11C 5-step and 50-step real CARLA --require-server smoke tests passed.
```

## 新增腳本

```text
scripts/phase11e_unlock_carla_environment.ps1
```

此腳本預設只做 planning 與 Phase 11D gate，不做任何外部環境變更。只有明確提供 switch 時才會執行動作：

| Switch | 行為 |
|---|---|
| `-InstallWheel` | 安裝 `CARLA_ROOT\PythonAPI\carla\dist\carla-*.whl` 至指定 Python。 |
| `-ForceReinstallWheel` | 搭配 `-InstallWheel`，使用 pip force reinstall。 |
| `-StartServer` | 從 `CARLA_ROOT` 啟動 `CarlaUE4.exe` 或 `CarlaUnreal.exe`。 |
| `-VisibleServer` | 搭配 `-StartServer`，使用可見視窗啟動 server。預設背景啟動。 |
| `-RunRuntimeSmoke` | 11D ready 後，直接執行 11C real runtime smoke。 |
| `-RequireUnlock` | provisioning 未 ready 時 exit 1。 |

## 預設安全執行

```powershell
powershell -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1
```

Phase 11E 原始執行結果仍會停在 blocked，因為當時尚未提供有效 `CARLA_ROOT`，且 11D 仍偵測到：

```text
carla Python package missing
carla wheel candidate missing
CARLA server executable missing
CARLA server process missing
127.0.0.1:2000 TCP endpoint unreachable
```

目前驗證結果：

```text
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1
exit 0, prints unlock plan and current Phase 11D blocked report

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1 -RequireUnlock
exit 1, expected because CARLA_ROOT / wheel / server are not ready

PowerShell scriptblock parse check
passed
```

## 解鎖流程

### 1. 指定 CARLA_ROOT

```powershell
$env:CARLA_ROOT = "C:\CARLA\CARLA_0.9.x"
```

### 2. 先跑 plan-only

```powershell
powershell -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1 -CarlaRoot $env:CARLA_ROOT
```

### 3. 安裝 matching CARLA wheel

```powershell
powershell -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1 `
  -CarlaRoot $env:CARLA_ROOT `
  -InstallWheel `
  -RequireUnlock
```

### 4. 啟動 CARLA server

```powershell
powershell -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1 `
  -CarlaRoot $env:CARLA_ROOT `
  -StartServer `
  -VisibleServer
```

### 5. 確認 provisioning ready

```powershell
python scripts\run_phase11d_carla_provisioning_gate.py --require-ready
```

### 6. 執行 11C runtime smoke

```powershell
python scripts\run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 5 --require-server
```

## 一次式解鎖與 smoke

若 `CARLA_ROOT` 已正確設定，且你要讓腳本安裝 wheel、啟動 server、跑 11C：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1 `
  -CarlaRoot $env:CARLA_ROOT `
  -InstallWheel `
  -StartServer `
  -VisibleServer `
  -RunRuntimeSmoke `
  -RequireUnlock
```

## 狀態升級規則

只有以下兩個 gate 都通過，才可升級：

```powershell
python scripts\run_phase11d_carla_provisioning_gate.py --require-ready
python scripts\run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 5 --require-server
```

通過前不可宣告：

```text
Phase 11C Pass
CARLA Server Runtime Pass
Real CARLA closed-loop verified
```

通過前可宣告：

```text
Phase 11E Unlock Kit Ready — runtime remains blocked until external CARLA environment is provisioned.
```

Phase 11H 已用 dedicated Python 3.12 runtime 完成上述兩個 gate；最新 runtime pass 請以 `docs/phase11h_python312_carla_runtime_environment.md` 為準。
