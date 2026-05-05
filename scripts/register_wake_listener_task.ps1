param(
    [string]$TaskName = "Jarvis Wake Listener",
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [ValidateSet("dev", "electron")]
    [string]$Mode = "dev"
)

$startScript = Join-Path $ProjectRoot "scripts\start_wake_listener.ps1"
if (-not (Test-Path $startScript)) {
    Write-Error "Start script not found: $startScript"
    exit 1
}

$escapedStartScript = $startScript.Replace('"', '\"')
$taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$escapedStartScript`" -Mode $Mode"

Write-Host "[WakeListener] Registering Windows task: $TaskName"
Write-Host "[WakeListener] Command: $taskCommand"

schtasks /Create /TN $TaskName /TR $taskCommand /SC ONLOGON /RL LIMITED /F | Out-Host

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to register task. Exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "[WakeListener] Task registered successfully."
Write-Host "[WakeListener] It will start automatically on logon."
