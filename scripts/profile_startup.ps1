<#
.SYNOPSIS
    Muestrea el consumo de RAM/CPU del stack de Jarvis durante el arranque.

.DESCRIPTION
    Corre este script en una terminal y, en otra, lanza `npm run dev`.
    Cada 2s toma una foto de los procesos relevantes y guarda el PICO de
    RAM (WorkingSet) por nombre de proceso. Pulsa Ctrl+C para terminar y
    ver el informe ordenado.

.PARAMETER Seconds
    Duracion maxima del muestreo (por defecto 120s). Ctrl+C lo corta antes.

.PARAMETER IntervalMs
    Intervalo entre muestras en milisegundos (por defecto 2000).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\profile_startup.ps1
#>
param(
    [int]$Seconds = 120,
    [int]$IntervalMs = 2000
)

$pattern = 'electron|node|python|chrome|chromium|openclaw|esbuild|vite|conhost'

# peak[clave] = @{ Name; PeakRamMB; PeakCount; LastCpu }
$peak = @{}

$deadline = (Get-Date).AddSeconds($Seconds)
Write-Host "[profile] Muestreando hasta $Seconds s (Ctrl+C para parar). Lanza 'npm run dev' en otra terminal..." -ForegroundColor Cyan

try {
    while ((Get-Date) -lt $deadline) {
        $procs = Get-Process | Where-Object { $_.Name -match $pattern }

        # Agrupa por nombre de proceso (electron suele tener varios .exe)
        $groups = $procs | Group-Object Name
        foreach ($g in $groups) {
            $ramMB = [math]::Round((($g.Group | Measure-Object WorkingSet64 -Sum).Sum) / 1MB, 1)
            $cpu   = [math]::Round((($g.Group | Measure-Object CPU -Sum).Sum), 1)
            $count = $g.Count
            $name  = $g.Name

            if (-not $peak.ContainsKey($name)) {
                $peak[$name] = @{ Name = $name; PeakRamMB = $ramMB; PeakCount = $count; LastCpu = $cpu }
            } else {
                if ($ramMB -gt $peak[$name].PeakRamMB) { $peak[$name].PeakRamMB = $ramMB }
                if ($count -gt $peak[$name].PeakCount) { $peak[$name].PeakCount = $count }
                $peak[$name].LastCpu = $cpu
            }
        }

        $totalNow = [math]::Round((($procs | Measure-Object WorkingSet64 -Sum).Sum) / 1MB, 1)
        Write-Host ("[profile] {0}  RAM stack actual: {1} MB  ({2} procesos)" -f (Get-Date -Format HH:mm:ss), $totalNow, $procs.Count)

        Start-Sleep -Milliseconds $IntervalMs
    }
} finally {
    Write-Host ""
    Write-Host "==== PICO DE RAM POR COMPONENTE (durante el muestreo) ====" -ForegroundColor Green
    $rows = $peak.Values | Sort-Object PeakRamMB -Descending
    $rows | Format-Table @{N='Proceso';E={$_.Name}},
                         @{N='Pico RAM (MB)';E={$_.PeakRamMB}},
                         @{N='# procesos';E={$_.PeakCount}},
                         @{N='CPU acum (s)';E={$_.LastCpu}} -AutoSize

    $grandTotal = [math]::Round((($rows | Measure-Object PeakRamMB -Sum).Sum), 1)
    Write-Host ("TOTAL (suma de picos, aprox.): {0} MB" -f $grandTotal) -ForegroundColor Yellow
    Write-Host "Nota: la suma de picos sobreestima un poco (no todos pican a la vez)." -ForegroundColor DarkGray
}
