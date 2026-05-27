const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

// Use ANGLE D3D11 backend - more stable on Windows while keeping WebGL working
// This fixes "GPU state invalid after WaitForGetOffsetInRange" error
app.commandLine.appendSwitch('use-angle', 'd3d11');
app.commandLine.appendSwitch('enable-features', 'Vulkan');
app.commandLine.appendSwitch('ignore-gpu-blocklist');

let mainWindow;
let pythonProcess;
let openclawProcess;
let openclawStartedByJarvis = false;
let childCleanupStarted = false;

const OPENCLAW_GATEWAY_PORT = Number(process.env.JARVIS_OPENCLAW_GATEWAY_PORT || process.env.OPENCLAW_GATEWAY_PORT || 18789);

function envFlag(name, defaultValue) {
    const raw = process.env[name];
    if (raw === undefined || raw === null || raw === '') return defaultValue;
    return !['0', 'false', 'no', 'off'].includes(String(raw).trim().toLowerCase());
}

function resolvePythonExecutable() {
    if (process.env.JARVIS_PYTHON) {
        return process.env.JARVIS_PYTHON;
    }

    const projectRoot = path.join(__dirname, '..');
    const localVenvPython = process.platform === 'win32'
        ? path.join(projectRoot, 'venv', 'Scripts', 'python.exe')
        : path.join(projectRoot, 'venv', 'bin', 'python');

    if (fs.existsSync(localVenvPython)) {
        return localVenvPython;
    }

    return process.platform === 'win32' ? 'python' : 'python3';
}

function resolveOpenClawExecutable() {
    if (process.env.JARVIS_OPENCLAW_EXECUTABLE) {
        return process.env.JARVIS_OPENCLAW_EXECUTABLE;
    }
    return 'openclaw';
}

function killProcessTree(childProcess, label) {
    if (!childProcess || !childProcess.pid) return;

    if (process.platform === 'win32') {
        try {
            const { execSync } = require('child_process');
            execSync(`taskkill /pid ${childProcess.pid} /f /t`, { stdio: 'ignore' });
        } catch (e) {
            console.error(`Failed to kill ${label} process:`, e.message);
        }
    } else {
        try {
            childProcess.kill('SIGKILL');
        } catch (e) {
            console.error(`Failed to kill ${label} process:`, e.message);
        }
    }
}

function cleanupChildProcesses() {
    if (childCleanupStarted) return;
    childCleanupStarted = true;

    console.log('App closing... Killing Python backend and OpenClaw gateway.');
    if (pythonProcess) {
        killProcessTree(pythonProcess, 'python');
        pythonProcess = null;
    }
    if (openclawProcess) {
        openclawStartedByJarvis = false;
        killProcessTree(openclawProcess, 'OpenClaw');
        openclawProcess = null;
    }
}

function runOpenClawCli(args, timeoutMs = 15000) {
    return new Promise((resolve) => {
        const executable = resolveOpenClawExecutable();
        const child = spawn(executable, args, {
            shell: process.platform === 'win32',
            windowsHide: true,
            env: {
                ...process.env,
                OPENCLAW_GATEWAY_PORT: String(OPENCLAW_GATEWAY_PORT),
            },
        });

        let stdout = '';
        let stderr = '';
        const timeout = setTimeout(() => {
            killProcessTree(child, 'OpenClaw CLI');
            resolve({ code: -1, stdout, stderr: `${stderr}\nTimed out.`.trim() });
        }, timeoutMs);

        child.stdout.on('data', (data) => {
            stdout += data.toString();
        });
        child.stderr.on('data', (data) => {
            stderr += data.toString();
        });
        child.on('error', (err) => {
            clearTimeout(timeout);
            resolve({ code: -1, stdout, stderr: err.message });
        });
        child.on('close', (code) => {
            clearTimeout(timeout);
            resolve({ code, stdout, stderr });
        });
    });
}

function waitForPortState(port, shouldBeTaken, timeoutMs = 10000) {
    const startedAt = Date.now();
    return new Promise((resolve) => {
        const check = async () => {
            const isTaken = await checkPortTaken(port);
            if (isTaken === shouldBeTaken) {
                resolve(true);
                return;
            }
            if (Date.now() - startedAt >= timeoutMs) {
                resolve(false);
                return;
            }
            setTimeout(check, 500);
        };
        check();
    });
}

async function stopExistingOpenClawGateway() {
    console.log(`OpenClaw port ${OPENCLAW_GATEWAY_PORT} is already in use. Stopping existing gateway before starting Jarvis-managed OpenClaw...`);
    const result = await runOpenClawCli(['gateway', 'stop'], 15000);
    if (result.code !== 0) {
        console.warn(`OpenClaw gateway stop returned ${result.code}: ${(result.stderr || result.stdout || '').trim()}`);
    }
    return waitForPortState(OPENCLAW_GATEWAY_PORT, false, 10000);
}

async function startOpenClawGateway() {
    if (!envFlag('JARVIS_OPENCLAW_AUTO_START', true)) {
        console.log('OpenClaw auto-start disabled by JARVIS_OPENCLAW_AUTO_START.');
        return;
    }

    const portTaken = await checkPortTaken(OPENCLAW_GATEWAY_PORT);
    let forceGatewayStart = false;
    if (portTaken) {
        const stopped = await stopExistingOpenClawGateway();
        if (!stopped) {
            console.warn(`OpenClaw port ${OPENCLAW_GATEWAY_PORT} is still busy. Starting Jarvis-managed OpenClaw with --force.`);
            forceGatewayStart = true;
        }
    }

    const executable = resolveOpenClawExecutable();
    console.log(`Starting OpenClaw gateway on port ${OPENCLAW_GATEWAY_PORT} using: ${executable}`);

    const gatewayArgs = ['gateway'];
    if (forceGatewayStart) {
        gatewayArgs.push('--force');
    }
    gatewayArgs.push('run', '--port', String(OPENCLAW_GATEWAY_PORT));

    openclawProcess = spawn(executable, gatewayArgs, {
        shell: process.platform === 'win32',
        windowsHide: true,
        env: {
            ...process.env,
            OPENCLAW_GATEWAY_PORT: String(OPENCLAW_GATEWAY_PORT),
        },
    });
    openclawStartedByJarvis = true;

    openclawProcess.stdout.on('data', (data) => {
        console.log(`[OpenClaw]: ${data}`);
    });

    openclawProcess.stderr.on('data', (data) => {
        console.warn(`[OpenClaw]: ${data}`);
    });

    openclawProcess.on('error', (err) => {
        console.error('Failed to start OpenClaw gateway:', err.message);
        openclawProcess = null;
        openclawStartedByJarvis = false;
    });

    openclawProcess.on('exit', (code, signal) => {
        if (openclawStartedByJarvis) {
            console.log(`OpenClaw gateway exited (code=${code}, signal=${signal}).`);
        }
        openclawProcess = null;
        openclawStartedByJarvis = false;
    });

    const ready = await waitForPortState(OPENCLAW_GATEWAY_PORT, true, 20000);
    if (ready) {
        console.log('OpenClaw gateway is ready!');
    } else {
        console.warn(`OpenClaw gateway did not report port ${OPENCLAW_GATEWAY_PORT} as ready before timeout.`);
    }
}

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1920,
        height: 1080,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false, // For simple IPC/Socket.IO usage
        },
        backgroundColor: '#000000',
        frame: false, // Frameless for custom UI
        titleBarStyle: 'hidden',
        show: false, // Don't show until ready
    });

    // In dev, load Vite server. In prod, load index.html
    const isDev = process.env.NODE_ENV !== 'production';

    const loadFrontend = (retries = 3) => {
        const url = isDev ? 'http://localhost:5173' : null;
        const loadPromise = isDev
            ? mainWindow.loadURL(url)
            : mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));

        loadPromise
            .then(() => {
                console.log('Frontend loaded successfully!');
                windowWasShown = true;
                mainWindow.show();
                if (isDev) {
                    mainWindow.webContents.openDevTools();
                }
            })
            .catch((err) => {
                console.error(`Failed to load frontend: ${err.message}`);
                if (retries > 0) {
                    console.log(`Retrying in 1 second... (${retries} retries left)`);
                    setTimeout(() => loadFrontend(retries - 1), 1000);
                } else {
                    console.error('Failed to load frontend after all retries. Keeping window open.');
                    windowWasShown = true;
                    mainWindow.show(); // Show anyway so user sees something
                }
            });
    };

    loadFrontend();

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

function startPythonBackend() {
    const scriptPath = path.join(__dirname, '../backend/server.py');
    const pythonExecutable = resolvePythonExecutable();
    console.log(`Starting Python backend: ${scriptPath}`);
    console.log(`Using Python executable: ${pythonExecutable}`);

    pythonProcess = spawn(pythonExecutable, [scriptPath], {
        cwd: path.join(__dirname, '../backend'),
    });

    pythonProcess.stdout.on('data', (data) => {
        console.log(`[Python]: ${data}`);
    });

    pythonProcess.stderr.on('data', (data) => {
        console.error(`[Python Error]: ${data}`);
    });
}

app.whenReady().then(async () => {
    ipcMain.on('window-minimize', () => {
        if (mainWindow) mainWindow.minimize();
    });

    ipcMain.on('window-maximize', () => {
        if (mainWindow) {
            if (mainWindow.isMaximized()) {
                mainWindow.unmaximize();
            } else {
                mainWindow.maximize();
            }
        }
    });

    ipcMain.on('window-close', () => {
        if (mainWindow) mainWindow.close();
    });

    await startOpenClawGateway();

    checkBackendPort(8000).then((isTaken) => {
        if (isTaken) {
            console.log('Port 8000 is taken. Assuming backend is already running manually.');
            waitForBackend().then(createWindow);
        } else {
            startPythonBackend();
            // Give it a moment to start, then wait for health check
            setTimeout(() => {
                waitForBackend().then(createWindow);
            }, 1000);
        }
    });

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

function checkBackendPort(port) {
    return checkPortTaken(port);
}

function checkPortTaken(port) {
    return new Promise((resolve) => {
        const net = require('net');
        const server = net.createServer();
        server.once('error', (err) => {
            if (err.code === 'EADDRINUSE') {
                resolve(true);
            } else {
                resolve(false);
            }
        });
        server.once('listening', () => {
            server.close();
            resolve(false);
        });
        server.listen(port, '127.0.0.1');
    });
}

function waitForBackend() {
    return new Promise((resolve) => {
        const check = () => {
            const http = require('http');
            http.get('http://127.0.0.1:8000/status', (res) => {
                if (res.statusCode === 200) {
                    console.log('Backend is ready!');
                    resolve();
                } else {
                    console.log('Backend not ready, retrying...');
                    setTimeout(check, 1000);
                }
            }).on('error', (err) => {
                console.log('Waiting for backend...');
                setTimeout(check, 1000);
            });
        };
        check();
    });
}

let windowWasShown = false;

app.on('window-all-closed', () => {
    // Only quit if the window was actually shown at least once
    // This prevents quitting during startup if window creation fails
    if (process.platform !== 'darwin' && windowWasShown) {
        app.quit();
    } else if (!windowWasShown) {
        console.log('Window was never shown - keeping app alive to allow retries');
    }
});

app.on('will-quit', () => {
    cleanupChildProcesses();
});

process.on('SIGINT', () => {
    cleanupChildProcesses();
    app.quit();
});

process.on('SIGTERM', () => {
    cleanupChildProcesses();
    app.quit();
});
