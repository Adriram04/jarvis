param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [ValidateSet("dev", "electron")]
    [string]$Mode = "dev",
    [string]$ExtraArgs = ""
)

$listenerPath = Join-Path $ProjectRoot "wake_listener.py"
$venvPythonCandidates = @(
    (Join-Path $ProjectRoot "venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe")
)

if (-not (Test-Path $listenerPath)) {
    Write-Error "wake_listener.py not found at $listenerPath"
    exit 1
}

if (-not [string]::IsNullOrWhiteSpace($env:JARVIS_PYTHON)) {
    $python = $env:JARVIS_PYTHON
} else {
    $python = $null
    foreach ($candidate in $venvPythonCandidates) {
        if (Test-Path $candidate) {
            $python = $candidate
            break
        }
    }

    if (-not $python) {
        $python = "python"
    }
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

$extraArgList = @()
if (-not [string]::IsNullOrWhiteSpace($ExtraArgs)) {
    $extraArgList = @($ExtraArgs -split '\s+' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

& $python $listenerPath @defaultArgs @extraArgList
