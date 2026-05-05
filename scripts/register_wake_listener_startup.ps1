param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [ValidateSet("dev", "electron")]
    [string]$Mode = "dev",
    [switch]$Remove
)

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$entryName = "JarvisWakeListener"

if ($Remove) {
    if (Get-ItemProperty -Path $runKey -Name $entryName -ErrorAction SilentlyContinue) {
        Remove-ItemProperty -Path $runKey -Name $entryName -Force
        Write-Host "[WakeListener] Startup entry removed."
    } else {
        Write-Host "[WakeListener] Startup entry was not present."
    }
    exit 0
}

$startScript = Join-Path $ProjectRoot "scripts\start_wake_listener.ps1"
if (-not (Test-Path $startScript)) {
    Write-Error "Start script not found: $startScript"
    exit 1
}

$command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`" -Mode $Mode"

New-Item -Path $runKey -Force | Out-Null
New-ItemProperty -Path $runKey -Name $entryName -PropertyType ExpandString -Value $command -Force | Out-Null

Write-Host "[WakeListener] Startup entry created for current user."
Write-Host "[WakeListener] Name: $entryName"
Write-Host "[WakeListener] Command: $command"
