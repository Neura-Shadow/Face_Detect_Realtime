# Phase 11F — External CARLA Package Provisioning & 11C Unlock Attempt

## Current Status

Phase 11C 狀態必須嚴格維持：

```text
Phase 11C Blocked Locally — real CARLA runtime execution attempted with --require-server, but local environment lacks both carla Python package and reachable CARLA server.
```

Phase 11F 結論：

```text
Phase 11F Blocked — no valid CARLA server package found locally.
```

## Purpose

This phase attempts to unlock the real CARLA runtime by provisioning a real CARLA package, matching carla Python wheel, running CARLA server, and reachable TCP endpoint.

This is an infrastructure provisioning phase, not an MA-VLNA implementation phase.

No MA-VLNA core runtime code was modified in this phase.

## Execution Environment

| Item | Value |
|---|---|
| Executed at | `2026-06-12 21:35:51 +08:00` |
| Workspace | `D:\Face_Detect_Realtime` |
| Python interpreter | `C:\Users\zongx\anaconda3\python.exe` |
| Python version | `3.10.14 | packaged by Anaconda, Inc. | (main, May 6 2024, 19:44:50) [MSC v.1916 64 bit (AMD64)]` |
| Platform | `Windows-10-10.0.22631-SP0` |
| CARLA_ROOT | empty / not set |
| CARLA executable | not found |
| CARLA wheel candidate | not found |
| TCP endpoint | `127.0.0.1:2000` not reachable |

Environment command:

```powershell
python -c "import sys, platform; print(sys.executable); print(sys.version); print(platform.platform())"
```

## CARLA_ROOT Probe

Commands executed:

```powershell
echo $env:CARLA_ROOT
Get-ChildItem C:\ -Directory -ErrorAction SilentlyContinue | Where-Object {$_.Name -like "*CARLA*"}
Get-ChildItem D:\ -Directory -ErrorAction SilentlyContinue | Where-Object {$_.Name -like "*CARLA*"}
Get-ChildItem "$env:USERPROFILE\Downloads" -Directory -ErrorAction SilentlyContinue | Where-Object {$_.Name -like "*CARLA*"}
```

Result:

```text
CARLA_ROOT=
C:\ search: no *CARLA* directory found
D:\ search: no *CARLA* directory found
Downloads search: no *CARLA* directory found
```

Phase 11D JSON preflight still detects only a cache-like candidate:

```text
C:\Users\zongx\carlaCache
```

That path is not a valid CARLA server package root because it does not contain:

```text
CarlaUE4.exe or CarlaUnreal.exe
PythonAPI\carla\dist\carla-*.whl
```

## Phase 11D Evidence

```text
status: blocked
carla_python_package: fail
pip_package_metadata: warn, package not found
carla_server_package_root: warn, only C:\Users\zongx\carlaCache found
carla_server_executable: fail
carla_wheel_candidate: fail
carla_server_process: fail
carla_tcp_endpoint: fail
```

## Unlock Attempt Decision

Because no valid CARLA root exists locally, Phase 11F stopped before:

- plan-only unlock with a real `CARLA_ROOT`
- wheel installation
- `import carla` validation
- CARLA server launch
- Phase 11D `--require-ready`
- Phase 11C 5-step runtime smoke
- Phase 11C 50-step runtime smoke

This is the intended safe stop. Fake runtime is not used as a substitute for real runtime.

## Regression Results

Required regressions were executed after stopping at the CARLA package blocker:

```text
python scripts\run_phase11_carla_checks.py
Phase 11 驗證總結: 6/6 passed

python scripts\run_demo_checks.py
驗證總結: 6/6 測試通過

python -m py_compile scripts\run_phase11b_real_carla_smoke.py scripts\run_phase11d_carla_provisioning_gate.py
passed
```

Note: `run_demo_checks.py` completed successfully, but the 30-step mock check took about 140 seconds in this run.

## Required Manual Action

1. Download and extract a CARLA release package.
2. Set `CARLA_ROOT` to the extracted package root.
3. Confirm the root contains `CarlaUE4.exe` or `CarlaUnreal.exe`.
4. Confirm `PythonAPI\carla\dist\carla-*.whl` exists.
5. Re-run Phase 11F.

## Next Commands

After CARLA is extracted:

```powershell
$env:CARLA_ROOT = "C:\CARLA\CARLA_0.9.x"

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1 `
  -CarlaRoot $env:CARLA_ROOT
```

Only after plan-only output is correct:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1 `
  -CarlaRoot $env:CARLA_ROOT `
  -InstallWheel `
  -StartServer `
  -VisibleServer `
  -RunRuntimeSmoke `
  -RequireUnlock
```

## Final Phase 11F Status

```text
Phase 11F Blocked — no valid CARLA server package found locally.
```

## Superseded By Phase 11G

Phase 11G later downloaded and extracted CARLA 0.9.16 to `D:\CARLA`, so the Phase 11F package-root blocker is no longer the latest external provisioning state.

The current blocker moved to wheel compatibility:

```text
Phase 11G Wheel Install Blocked — carla-0.9.16-cp312-cp312-win_amd64.whl is not compatible with active Python 3.10.14.
```

## Superseded By Phase 11H

Phase 11H later created `D:\CARLA\envs\ma-vlna-carla312`, installed the same CARLA 0.9.16 `cp312` wheel, started the real CARLA server, and passed both 11D ready and 11C real runtime smoke gates.

Latest runtime status:

```text
Phase 11H Pass — Python 3.12 CARLA runtime environment provisioned; Phase 11D ready gate passed; Phase 11C 5-step and 50-step real CARLA --require-server smoke tests passed.
```
