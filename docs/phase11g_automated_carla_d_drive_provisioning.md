# Phase 11G — Fully Automated CARLA Provisioning to D Drive

## Purpose

Attempt to automatically provision a real CARLA runtime under `D:\CARLA`, install the matching carla Python wheel, start the CARLA server, verify TCP endpoint, run Phase 11D `--require-ready`, and then run Phase 11C real CARLA smoke.

This is an external simulator infrastructure provisioning phase, not an MA-VLNA implementation phase.

No MA-VLNA core runtime code was modified in this phase.

## Required Status Guard

Phase 11C status must remain strict:

```text
Phase 11C Blocked Locally — real CARLA runtime execution attempted with --require-server, but local environment lacks both carla Python package and reachable CARLA server.
```

## Final Phase 11G Status

```text
Phase 11G Blocked — CARLA package downloaded/extracted, but matching carla wheel installation is blocked by Python ABI mismatch.
```

More specific blocker:

```text
Phase 11G Wheel Install Blocked — carla-0.9.16-cp312-cp312-win_amd64.whl is not compatible with active Python 3.10.14.
```

## Environment

| Item | Value |
|---|---|
| Executed at | `2026-06-12 22:28:30 +08:00` |
| Python interpreter | `C:\Users\zongx\anaconda3\python.exe` |
| Python version | `3.10.14 | packaged by Anaconda, Inc. | (main, May 6 2024, 19:44:50) [MSC v.1916 64 bit (AMD64)]` |
| Platform | `Windows-10-10.0.22631-SP0` |
| Workspace | `D:\Face_Detect_Realtime` |
| Download root | `D:\CARLA\downloads` |
| Package root | `D:\CARLA\packages` |
| CARLA_ROOT | `D:\CARLA\packages\CARLA_0.9.16` |
| CARLA version | `0.9.16` |
| CARLA executable | `D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe` |
| CARLA wheel candidate | `D:\CARLA\packages\CARLA_0.9.16\PythonAPI\carla\dist\carla-0.9.16-cp312-cp312-win_amd64.whl` |
| TCP endpoint | `127.0.0.1:2000` not reachable |

Environment command:

```powershell
python -c "import sys, platform; print(sys.executable); print(sys.version); print(platform.platform())"
```

## D Drive Preparation

Created / confirmed:

```text
D:\CARLA
D:\CARLA\downloads
D:\CARLA\packages
```

D drive was available and had sufficient space for the CARLA package.

## Download

Official release metadata resolved the Windows package link:

```text
https://tiny.carla.org/carla-0-9-16-windows
-> https://carla-releases.b-cdn.net/Windows/CARLA_0.9.16.zip
```

HEAD metadata:

```text
Content-Length: 7812252810
Content-Type: application/x-zip-compressed
```

Downloaded file:

```text
D:\CARLA\downloads\CARLA_0.9.16.zip
size: 7812252810 bytes
```

This is larger than the 1GB suspect threshold.

## Extraction

Extracted to:

```text
D:\CARLA\packages\CARLA_0.9.16
```

Validation after extraction:

```text
D:\CARLA\packages\CARLA_0.9.16\CarlaUE4.exe: found
D:\CARLA\packages\CARLA_0.9.16\PythonAPI\carla\dist\carla-0.9.16-cp312-cp312-win_amd64.whl: found
```

`CARLA_ROOT` was set to:

```text
D:\CARLA\packages\CARLA_0.9.16
```

## Wheel Installation Attempt

Active interpreter:

```text
C:\Users\zongx\anaconda3\python.exe
Python 3.10.14
```

Wheel found:

```text
carla-0.9.16-cp312-cp312-win_amd64.whl
```

Command attempted:

```powershell
python -m pip uninstall -y carla
python -m pip install D:\CARLA\packages\CARLA_0.9.16\PythonAPI\carla\dist\carla-0.9.16-cp312-cp312-win_amd64.whl
```

Result:

```text
WARNING: Skipping carla as it is not installed.
ERROR: carla-0.9.16-cp312-cp312-win_amd64.whl is not a supported wheel on this platform.
```

Validation:

```text
import carla: failed
python -m pip show carla: package not found
```

## Stop Decision

Because the matching CARLA 0.9.16 Windows wheel is built for CPython 3.12 and the active MA-VLNA interpreter is Python 3.10, Phase 11G stopped before:

- CARLA server launch
- TCP readiness wait loop
- Phase 11D `--require-ready`
- Phase 11C 5-step real runtime smoke
- Phase 11C 50-step real runtime smoke

This preserves the rule: fake runtime must not be used as a real CARLA runtime substitute.

## Phase 11D Evidence

With `--carla-root D:\CARLA\packages\CARLA_0.9.16`, Phase 11D now sees the package and executable but remains blocked:

```text
status: blocked
carla_python_package: fail
carla_server_package_root: pass
carla_server_executable: pass
carla_wheel_candidate: fail, cp312 wheel does not match Python 3.10.14
carla_server_process: fail
carla_tcp_endpoint: fail
```

## Next Unlock Options

Choose one:

1. Run MA-VLNA Phase 11G from a Python 3.12 environment and reinstall project worker dependencies there.
2. Use a CARLA release that provides a Windows wheel compatible with Python 3.10.
3. Keep the downloaded package, create a dedicated Python 3.12 environment, install the CPython 3.12 CARLA wheel, then rerun 11D and 11C from that interpreter.

Do not add `carla` to baseline requirements.

## Regression Results

Required regressions were executed after stopping at the wheel-install blocker:

```text
python scripts\run_phase11_carla_checks.py
6/6 passed

python scripts\run_demo_checks.py
6/6 passed

python -m py_compile scripts\run_phase11b_real_carla_smoke.py scripts\run_phase11d_carla_provisioning_gate.py
passed
```

## Final Status

```text
Phase 11G Blocked — CARLA package downloaded/extracted to D:\CARLA, but carla wheel installation is blocked because the CARLA 0.9.16 Windows wheel targets CPython 3.12 while the active interpreter is Python 3.10.14.
```

## Superseded By Phase 11H

Phase 11H resolved this blocker by creating a dedicated Python 3.12 environment:

```text
D:\CARLA\envs\ma-vlna-carla312
```

It then installed the CARLA 0.9.16 `cp312` wheel, started the real CARLA server, passed Phase 11D `--require-ready`, and passed Phase 11C 5-step plus 50-step `--require-server` smoke tests.

Latest status:

```text
Phase 11H Pass — Python 3.12 CARLA runtime environment provisioned; Phase 11D ready gate passed; Phase 11C 5-step and 50-step real CARLA --require-server smoke tests passed.
```
