<#
.SYNOPSIS
Phase 11E - CARLA Runtime Environment Unlock helper.

.DESCRIPTION
Read-first helper for unlocking the real CARLA runtime environment.
By default this script does not install packages, does not launch CARLA,
and does not run the real runtime smoke test. It prints the concrete next
commands and runs the Phase 11D provisioning gate.

The Phase 11C status must remain strict until the real runtime smoke passes:

Phase 11C Blocked Locally - real CARLA runtime execution attempted with
--require-server, but local environment lacks both carla Python package and
reachable CARLA server.
#>

[CmdletBinding()]
param(
    [string]$CarlaRoot = $env:CARLA_ROOT,
    [string]$PythonExe = "python",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 2000,
    [int]$Steps = 5,
    [switch]$InstallWheel,
    [switch]$ForceReinstallWheel,
    [switch]$StartServer,
    [switch]$VisibleServer,
    [switch]$RunRuntimeSmoke,
    [switch]$RequireUnlock
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$Phase11D = Join-Path $RepoRoot "scripts\run_phase11d_carla_provisioning_gate.py"
$Phase11B = Join-Path $RepoRoot "scripts\run_phase11b_real_carla_smoke.py"

function Write-Phase {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message =="
}

function Resolve-OptionalPath {
    param([string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $null
    }
    $resolved = Resolve-Path -LiteralPath $PathValue -ErrorAction SilentlyContinue
    if ($null -eq $resolved) {
        return $null
    }
    return $resolved.Path
}

function Find-FirstFile {
    param(
        [string]$Root,
        [string[]]$Names
    )
    if ([string]::IsNullOrWhiteSpace($Root) -or -not (Test-Path -LiteralPath $Root)) {
        return $null
    }
    foreach ($name in $Names) {
        $direct = Join-Path $Root $name
        if (Test-Path -LiteralPath $direct) {
            return (Resolve-Path -LiteralPath $direct).Path
        }
    }
    $found = Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $Names -contains $_.Name } |
        Select-Object -First 1
    if ($null -eq $found) {
        return $null
    }
    return $found.FullName
}

function Find-CARLAWheel {
    param([string]$Root)
    if ([string]::IsNullOrWhiteSpace($Root) -or -not (Test-Path -LiteralPath $Root)) {
        return $null
    }
    $dist = Join-Path $Root "PythonAPI\carla\dist"
    if (Test-Path -LiteralPath $dist) {
        $wheel = Get-ChildItem -LiteralPath $dist -Filter "carla-*.whl" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($null -ne $wheel) {
            return $wheel.FullName
        }
    }
    $fallback = Get-ChildItem -LiteralPath $Root -Recurse -Filter "carla-*.whl" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $fallback) {
        return $null
    }
    return $fallback.FullName
}

Write-Phase "Phase 11E - CARLA Runtime Environment Unlock"
Write-Host "11C status preserved:"
Write-Host "Phase 11C Blocked Locally - real CARLA runtime execution attempted with --require-server, but local environment lacks both carla Python package and reachable CARLA server."

$ResolvedCarlaRoot = Resolve-OptionalPath $CarlaRoot
if ($null -eq $ResolvedCarlaRoot) {
    Write-Phase "CARLA_ROOT not ready"
    Write-Host "No valid CARLA root was supplied."
    Write-Host "Set CARLA_ROOT or pass -CarlaRoot, for example:"
    Write-Host '  $env:CARLA_ROOT = "C:\CARLA\CARLA_0.9.x"'
    Write-Host '  powershell -ExecutionPolicy Bypass -File scripts\phase11e_unlock_carla_environment.ps1 -CarlaRoot $env:CARLA_ROOT'
    Write-Phase "Current Phase 11D gate"
    & $PythonExe $Phase11D --host $HostName --port $Port
    if ($RequireUnlock) {
        exit 1
    }
    exit 0
}

Write-Phase "Resolved CARLA root"
Write-Host $ResolvedCarlaRoot

$ServerExe = Find-FirstFile -Root $ResolvedCarlaRoot -Names @("CarlaUE4.exe", "CarlaUnreal.exe")
$Wheel = Find-CARLAWheel -Root $ResolvedCarlaRoot

$ServerExeDisplay = if ($null -ne $ServerExe) { $ServerExe } else { "<missing>" }
$WheelDisplay = if ($null -ne $Wheel) { $Wheel } else { "<missing>" }
Write-Host "Server executable: $ServerExeDisplay"
Write-Host "CARLA wheel: $WheelDisplay"

if ($InstallWheel) {
    if ($null -eq $Wheel) {
        Write-Error "Cannot install CARLA wheel because no carla-*.whl was found under $ResolvedCarlaRoot"
    }
    Write-Phase "Installing CARLA Python wheel"
    $pipArgs = @("-m", "pip", "install")
    if ($ForceReinstallWheel) {
        $pipArgs += "--force-reinstall"
    }
    $pipArgs += $Wheel
    & $PythonExe @pipArgs
} else {
    Write-Phase "Wheel install command"
    if ($null -ne $Wheel) {
        Write-Host "$PythonExe -m pip install `"$Wheel`""
    } else {
        Write-Host "No wheel found yet. Install/extract a CARLA package that contains PythonAPI\carla\dist\carla-*.whl."
    }
}

if ($StartServer) {
    if ($null -eq $ServerExe) {
        Write-Error "Cannot start CARLA server because no CarlaUE4.exe or CarlaUnreal.exe was found under $ResolvedCarlaRoot"
    }
    Write-Phase "Starting CARLA server"
    $serverArgs = @("-quality-level=Low")
    if ($Port -ne 2000) {
        $serverArgs += "-carla-rpc-port=$Port"
    }
    $workingDir = Split-Path -Parent $ServerExe
    if ($VisibleServer) {
        Start-Process -FilePath $ServerExe -ArgumentList $serverArgs -WorkingDirectory $workingDir
    } else {
        Start-Process -FilePath $ServerExe -ArgumentList $serverArgs -WorkingDirectory $workingDir -WindowStyle Hidden
    }
    Start-Sleep -Seconds 8
} else {
    Write-Phase "Server start command"
    if ($null -ne $ServerExe) {
        Write-Host "`"$ServerExe`" -quality-level=Low"
    } else {
        Write-Host "No CARLA server executable found yet."
    }
}

Write-Phase "Phase 11D provisioning gate"
$gateArgs = @($Phase11D, "--host", $HostName, "--port", "$Port")
if ($RequireUnlock -or $RunRuntimeSmoke) {
    $gateArgs += "--require-ready"
}
& $PythonExe @gateArgs
$gateExit = $LASTEXITCODE
if ($gateExit -ne 0) {
    if ($RequireUnlock -or $RunRuntimeSmoke) {
        exit $gateExit
    }
    exit 0
}

if ($RunRuntimeSmoke) {
    Write-Phase "Phase 11C real runtime smoke"
    & $PythonExe $Phase11B --host $HostName --port $Port --steps $Steps --require-server
    exit $LASTEXITCODE
}

Write-Phase "Ready for Phase 11C command"
Write-Host "$PythonExe `"$Phase11B`" --host $HostName --port $Port --steps $Steps --require-server"
exit 0
