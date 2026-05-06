# Double-Clap Wake Listener

This project now includes a lightweight background listener that wakes Jarvis
when it detects **two claps** close together.

## Files added

- `wake_listener.py`: Mic listener + clap detection + launcher
- `scripts/start_wake_listener.ps1`: Starts listener with `JARVIS_PYTHON`, local `venv`, local `.venv`, or PATH Python
- `scripts/register_wake_listener_task.ps1`: Registers Windows auto-start task

## Run manually

From project root:

```powershell
npm run wake-listener
```

Or for packaged Electron mode:

```powershell
npm run wake-listener:electron
```

## Auto-start on Windows logon

From project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_wake_listener_startup.ps1 -Mode dev
```

This is one-time setup. After that, it starts hidden on each logon.
When a double clap is detected, it opens a **visible cmd window**
(`Jarvis Console`) so you can inspect startup logs/errors.
The console closes automatically when Jarvis exits.

Remove auto-start if needed:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_wake_listener_startup.ps1 -Remove
```

If your machine policy blocks registry startup entries, fallback:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_wake_listener_task.ps1 -Mode dev
```

## Tuning sensitivity

If it does not trigger, lower threshold:

```powershell
.\venv\Scripts\python.exe .\wake_listener.py --mode dev --base-threshold-rms 3200
```

If it triggers too easily, raise threshold:

```powershell
.\venv\Scripts\python.exe .\wake_listener.py --mode dev --base-threshold-rms 5200
```

Useful debug mode:

```powershell
.\venv\Scripts\python.exe .\wake_listener.py --mode dev --verbose
```

## Troubleshooting (if claps do not trigger)

1. Check that listener is running:

```powershell
Get-CimInstance Win32_Process | ? { $_.Name -like 'python*' -and $_.CommandLine -like '*wake_listener.py*' } | select ProcessId,CommandLine
```

2. Check log output:

```powershell
Get-Content .\wake_listener.log -Tail 80
```

You should see startup lines and, on detection:
- `Double clap detected`
- `Launched Jarvis with command: ...`
- `Launch skipped: Startup lock active ...` (expected while it is booting)

3. Start manually with extra sensitivity:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_wake_listener.ps1 -Mode dev -ExtraArgs "--base-threshold-rms 1100 --verbose"
```
