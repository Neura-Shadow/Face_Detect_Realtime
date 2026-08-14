# Phase 11H — Python 3.12 CARLA Runtime Environment

## Purpose

Phase 11H resolves the Phase 11G wheel ABI blocker by creating a dedicated Python 3.12 runtime for CARLA 0.9.16.

This phase does not modify MA-VLNA core runtime code and does not add `carla` to baseline requirements. It provisions an external simulator runtime under `D:\CARLA`, installs the package-provided CARLA wheel into a dedicated interpreter, starts the real CARLA server, and runs the existing Phase 11D/11C gates.

## Initial Status Guard

At the start of this phase, the status remained:

```text
Phase 11C Blocked Locally — real CARLA runtime execution attempted with --require-server, but local environment lacks both carla Python package and reachable CARLA server.
```

That statement is preserved as the historical Phase 11C/11G blocker. Phase 11H supersedes it only for the dedicated Python 3.12 CARLA runtime documented below.

## Final Phase 11H Status

```text
Phase 11H Pass — Python 3.12 CARLA runtime environment provisioned; Phase 11D ready gate passed; Phase 11C 5-step and 50-step real CARLA --require-server smoke tests passed.
```

## Environment

| Item | Value |
|---|---|
| Executed at | `2026-06-12 23:28-23:29 +08:00` |
| Workspace | `D:\Face_Detect_Realtime` |
| Dedicated Python env | `D:\CARLA\envs\ma-vlna-carla312` |
| Python interpreter | `D:\CARLA\envs\ma-vlna-carla312\python.exe` |
| Python version | `3.12.13 | packaged by Anaconda, Inc.` |
| CARLA package root | `D:\CARLA\packages\CARLA_0.9.16` |
| CARLA executable | `D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe` |
| CARLA wheel | `D:\CARLA\packages\CARLA_0.9.16\PythonAPI\carla\dist\carla-0.9.16-cp312-cp312-win_amd64.whl` |
| CARLA endpoint | `127.0.0.1:2000` |

## Python 3.12 Environment

Created a dedicated conda environment on D drive:

```powershell
conda create -y -p D:\CARLA\envs\ma-vlna-carla312 python=3.12 pip
```

Installed MA-VLNA worker dependencies:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r workers\requirements.txt
```

Installed the CARLA package wheel:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install D:\CARLA\packages\CARLA_0.9.16\PythonAPI\carla\dist\carla-0.9.16-cp312-cp312-win_amd64.whl
```

Result:

```text
Successfully installed carla-0.9.16
```

## Import Verification

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -c "import sys, platform, carla; print(sys.executable); print(sys.version); print(platform.platform()); print('carla', getattr(carla, '__version__', 'unknown'), carla.__file__)"
```

Result:

```text
D:\CARLA\envs\ma-vlna-carla312\python.exe
3.12.13 | packaged by Anaconda, Inc. | (main, Mar 19 2026, 20:16:45) [MSC v.1942 64 bit (AMD64)]
Windows-11-10.0.22631-SP0
carla unknown D:\CARLA\envs\ma-vlna-carla312\Lib\site-packages\carla\__init__.py
```

Package metadata:

```text
Name: carla
Version: 0.9.16
Location: D:\CARLA\envs\ma-vlna-carla312\Lib\site-packages
```

## Server Launch

`CARLA_ROOT` was set to:

```text
D:\CARLA\packages\CARLA_0.9.16
```

Server launch command used by the provisioning step:

```powershell
Start-Process D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe `
  -ArgumentList "-carla-rpc-port=2000", "-quality-level=Low", "-RenderOffScreen", "-nosound", "-windowed", "-ResX=640", "-ResY=480"
```

Readiness loop result:

```text
STARTED_PID 220948
WAIT 22s process_alive=True tcp=True
CARLA_TCP_READY
```

Process evidence while running:

```text
CarlaUE4.exe, 220948
CarlaUE4-Win64-Shipping.exe, 238316
```

The server was stopped after verification so no CARLA background process remains from this phase.

## Phase 11D Ready Gate

Command:

```powershell
$env:CARLA_ROOT="D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11d_carla_provisioning_gate.py --carla-root $env:CARLA_ROOT --host 127.0.0.1 --port 2000 --steps 5 --require-ready
```

Result:

```text
status: ready

[PASS] python_interpreter: D:\CARLA\envs\ma-vlna-carla312\python.exe (3.12.13)
[PASS] carla_python_package: carla import ok
[PASS] pip_package_metadata: Name: carla | Version: 0.9.16 | Location: D:\CARLA\envs\ma-vlna-carla312\Lib\site-packages
[PASS] carla_server_package_root: D:\CARLA\packages\CARLA_0.9.16
[PASS] carla_server_executable: D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe
[PASS] carla_wheel_candidate: D:\CARLA\packages\CARLA_0.9.16\PythonAPI\carla\dist\carla-0.9.16-cp312-cp312-win_amd64.whl
[PASS] carla_server_process: CarlaUE4.exe, 220948; CarlaUE4-Win64-Shipping.exe, 238316
[PASS] carla_tcp_endpoint: 127.0.0.1:2000 is reachable.

phase11d carla provisioning gate ready
```

## Phase 11C 5-Step Runtime Smoke

Command:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 5 --require-server
```

Result:

```text
phase11b real carla smoke passed
ego vehicle spawned: blueprint=vehicle.tesla.model3, spawn_index=0
RGB camera attached: 320x180 fov=90.0
[CARLA] control #1..#5
達到指定 CARLA closed-loop 步數: 5
Phase 11 CARLA closed-loop runner stopped
```

## Phase 11C 50-Step Runtime Smoke

Command:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 50 --require-server
```

Result:

```text
phase11b real carla smoke passed
ego vehicle spawned: blueprint=vehicle.tesla.model3, spawn_index=0
RGB camera attached: 320x180 fov=90.0
[CARLA] control #1..#50
達到指定 CARLA closed-loop 步數: 50
flush: 已寫入 40 筆遙測資料
Phase 11 CARLA closed-loop runner stopped
```

Supabase was intentionally not required for this local runtime gate. Telemetry fell back to:

```text
runtime_logs\telemetry_fallback.jsonl
```

## Runtime Boundary

This pass applies to:

```text
Python: D:\CARLA\envs\ma-vlna-carla312\python.exe
CARLA_ROOT: D:\CARLA\packages\CARLA_0.9.16
CARLA server: 127.0.0.1:2000
CARLA wheel: carla 0.9.16 cp312
```

The default Anaconda base interpreter remains Python 3.10.14 and should continue to run no-server/fallback checks. Do not add `carla` to `workers/requirements.txt`; keep CARLA as an external simulator dependency pinned by the installed CARLA package.

## Regression Results

After documentation updates, the baseline no-server and mock/fallback checks still pass from the default Python 3.10 environment:

```text
python scripts\run_phase11_carla_checks.py
Phase 11 驗證總結: 6/6 passed

python scripts\run_demo_checks.py
驗證總結: 6/6 測試通過

python -m py_compile scripts\run_phase11b_real_carla_smoke.py scripts\run_phase11d_carla_provisioning_gate.py
passed
```

## Final Claim

The historical Phase 11C blocked-local status was valid for the Python 3.10 environment. Phase 11H provides the successful unlock path:

```text
Phase 11H Pass — dedicated Python 3.12 CARLA environment created; real CARLA server launched; 11D ready gate and 11C 5/50-step --require-server runtime smoke passed.
```

## Phase 11I Evidence Pack

Phase 11I converted this runtime pass into a structured evidence pack:

```text
runtime_logs\carla_runs\20260613T073948Z
```

Status:

```text
Phase 11I Evidence Pack Pass — structured evidence for real CARLA 5-step and 50-step smoke generated.
```

The evidence pack is smoke-only. It does not claim route completion, infraction metrics, CARLA Leaderboard pass, real YOLO/RT-DETR verification, or real OpenAI-compatible VLM verification.
