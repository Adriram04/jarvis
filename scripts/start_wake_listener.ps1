param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [ValidateSet("dev", "electron")]
    [string]$Mode = "dev",
    [string]$ExtraArgs = ""
)

$listenerPath = Join-Path $ProjectRoot "wake_listener.py"
$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $listenerPath)) {
    Write-Error "wake_listener.py not found at $listenerPath"
    exit 1
}

if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    $python = "python"
}

Write-Host "[WakeListener] Starting with: $python $listenerPath --mode $Mode"

$existing = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -like 'python*' -and
        $_.CommandLine -like '*wake_listener.py*'
    }

if ($existing) {
    Write-Host "[WakeListener] Existing listener detected. Skipping duplicate start."
    exit 0
}

$defaultArgs = @(
    "--mode", $Mode,
    "--base-threshold-rms", "1500",
    "--clap-min-gap", "0.08",
    "--clap-max-gap", "1.20",
    "--launch-cooldown", "20",
    "--startup-grace", "45",
    "--startup-min-hold", "8",
    "--launch-visible"
)

if ([string]::IsNullOrWhiteSpace($ExtraArgs)) {
    & $python $listenerPath @defaultArgs
} else {
    & $python $listenerPath @defaultArgs $ExtraArgs
}
