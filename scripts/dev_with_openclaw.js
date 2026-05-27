const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');
const { execFileSync, execSync, spawn } = require('child_process');

const projectRoot = path.resolve(__dirname, '..');
const gatewayPort = Number(process.env.JARVIS_OPENCLAW_GATEWAY_PORT || process.env.OPENCLAW_GATEWAY_PORT || 18789);
const vitePort = Number(process.env.JARVIS_VITE_PORT || 5173);
const children = new Set();
let shuttingDown = false;

function envFlag(name, defaultValue) {
    const raw = process.env[name];
    if (raw === undefined || raw === null || raw === '') return defaultValue;
    return !['0', 'false', 'no', 'off'].includes(String(raw).trim().toLowerCase());
}

function localPath(...parts) {
    return path.join(projectRoot, ...parts);
}

function resolveNodeExecutable() {
    return process.env.JARVIS_NODE || process.execPath || 'node';
}

function resolveOpenClawCommand() {
    if (process.env.JARVIS_OPENCLAW_NODE_ENTRY) {
        return {
            command: resolveNodeExecutable(),
            baseArgs: [process.env.JARVIS_OPENCLAW_NODE_ENTRY],
            shell: false,
        };
    }

    const appData = process.env.APPDATA || '';
    const globalEntry = appData
        ? path.join(appData, 'npm', 'node_modules', 'openclaw', 'dist', 'index.js')
        : '';
    if (globalEntry && fs.existsSync(globalEntry)) {
        return {
            command: resolveNodeExecutable(),
            baseArgs: [globalEntry],
            shell: false,
        };
    }

    const configured = process.env.JARVIS_OPENCLAW_EXECUTABLE;
    if (configured) {
        return {
            command: configured,
            baseArgs: [],
            shell: process.platform === 'win32' && /\.(cmd|bat)$/i.test(configured),
        };
    }

    return {
        command: 'openclaw',
        baseArgs: [],
        shell: process.platform === 'win32',
    };
}

function openclawArgs(args) {
    const resolved = resolveOpenClawCommand();
    return {
        ...resolved,
        args: [...resolved.baseArgs, ...args],
    };
}

function spawnManaged(label, command, args, options = {}) {
    console.log(`[dev] Starting ${label}: ${command} ${args.join(' ')}`);
    const child = spawn(command, args, {
        cwd: projectRoot,
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: false,
        ...options,
    });

    children.add(child);

    child.stdout.on('data', (data) => {
        process.stdout.write(`[${label}] ${data}`);
    });
    child.stderr.on('data', (data) => {
        process.stderr.write(`[${label}] ${data}`);
    });
    child.on('error', (err) => {
        console.error(`[dev] ${label} failed: ${err.message}`);
        shutdown(1);
    });
    child.on('exit', (code, signal) => {
        children.delete(child);
        if (!shuttingDown) {
            console.log(`[dev] ${label} exited (code=${code}, signal=${signal}).`);
            shutdown(code || (signal ? 1 : 0));
        }
    });

    return child;
}

function killProcessTree(child) {
    if (!child || !child.pid) return;
    try {
        if (process.platform === 'win32') {
            execSync(`taskkill /pid ${child.pid} /f /t`, { stdio: 'ignore' });
        } else {
            child.kill('SIGTERM');
            setTimeout(() => {
                try {
                    child.kill('SIGKILL');
                } catch (_err) {
                    // Already gone.
                }
            }, 1500).unref?.();
        }
    } catch (_err) {
        // Already gone.
    }
}

function canConnect(port) {
    return new Promise((resolve) => {
        const socket = net.createConnection({ host: '127.0.0.1', port });
        socket.setTimeout(1000);
        socket.once('connect', () => {
            socket.destroy();
            resolve(true);
        });
        socket.once('timeout', () => {
            socket.destroy();
            resolve(false);
        });
        socket.once('error', () => {
            resolve(false);
        });
    });
}

async function waitForPort(port, expected, timeoutMs) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
        if ((await canConnect(port)) === expected) {
            return true;
        }
        await new Promise((resolve) => setTimeout(resolve, 500));
    }
    return false;
}

function canFetch(url) {
    return new Promise((resolve) => {
        const request = http.get(url, (response) => {
            response.resume();
            resolve(response.statusCode >= 200 && response.statusCode < 500);
        });
        request.setTimeout(1000, () => {
            request.destroy();
            resolve(false);
        });
        request.on('error', () => {
            resolve(false);
        });
    });
}

async function waitForHttp(url, timeoutMs) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
        if (await canFetch(url)) {
            return true;
        }
        await new Promise((resolve) => setTimeout(resolve, 500));
    }
    return false;
}

function runOpenClawSync(args, timeoutMs = 15000) {
    const resolved = openclawArgs(args);
    try {
        execFileSync(resolved.command, resolved.args, {
            cwd: projectRoot,
            env: {
                ...process.env,
                OPENCLAW_GATEWAY_PORT: String(gatewayPort),
            },
            shell: resolved.shell,
            stdio: 'ignore',
            timeout: timeoutMs,
            windowsHide: true,
        });
        return true;
    } catch (_err) {
        return false;
    }
}

async function startOpenClaw() {
    if (!envFlag('JARVIS_OPENCLAW_AUTO_START', true)) {
        console.log('[dev] OpenClaw auto-start disabled.');
        return null;
    }

    let force = false;
    if (await canConnect(gatewayPort)) {
        console.log(`[dev] OpenClaw port ${gatewayPort} is busy; stopping existing gateway first.`);
        runOpenClawSync(['gateway', 'stop']);
        const stopped = await waitForPort(gatewayPort, false, 10000);
        if (!stopped) {
            console.log(`[dev] Port ${gatewayPort} stayed busy; starting OpenClaw with --force.`);
            force = true;
        }
    }

    const gatewayArgs = ['gateway'];
    if (force) gatewayArgs.push('--force');
    gatewayArgs.push('run', '--port', String(gatewayPort));

    const resolved = openclawArgs(gatewayArgs);
    const child = spawnManaged('openclaw', resolved.command, resolved.args, {
        shell: resolved.shell,
        env: {
            ...process.env,
            OPENCLAW_GATEWAY_PORT: String(gatewayPort),
        },
    });

    const ready = await waitForPort(gatewayPort, true, 30000);
    if (ready) {
        console.log(`[dev] OpenClaw gateway ready on 127.0.0.1:${gatewayPort}.`);
    } else {
        console.warn(`[dev] OpenClaw gateway did not become reachable on 127.0.0.1:${gatewayPort}.`);
    }
    return child;
}

function startVite() {
    const viteBin = localPath('node_modules', 'vite', 'bin', 'vite.js');
    return spawnManaged('vite', resolveNodeExecutable(), [viteBin], {
        shell: false,
        env: {
            ...process.env,
            PORT: String(vitePort),
        },
    });
}

async function startElectron() {
    const electronExe = process.platform === 'win32'
        ? localPath('node_modules', 'electron', 'dist', 'electron.exe')
        : localPath('node_modules', '.bin', 'electron');
    if (!fs.existsSync(electronExe)) {
        throw new Error(`Electron executable not found at ${electronExe}`);
    }

    const viteUrl = `http://localhost:${vitePort}/`;
    const ready = await waitForHttp(viteUrl, 30000);
    if (!ready) {
        throw new Error(`Vite did not become reachable at ${viteUrl}`);
    }

    return spawnManaged('electron', electronExe, ['.'], {
        shell: false,
        env: {
            ...process.env,
            JARVIS_OPENCLAW_AUTO_START: 'false',
            OPENCLAW_GATEWAY_PORT: String(gatewayPort),
        },
    });
}

function stopOpenClawGateway() {
    if (!envFlag('JARVIS_OPENCLAW_AUTO_START', true)) return;
    console.log('[dev] Stopping OpenClaw gateway.');
    runOpenClawSync(['gateway', 'stop'], 15000);
}

function shutdown(exitCode = 0) {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log('[dev] Shutting down Jarvis dev stack.');

    for (const child of Array.from(children)) {
        killProcessTree(child);
    }
    children.clear();
    stopOpenClawGateway();

    setTimeout(() => process.exit(exitCode), 200).unref?.();
}

process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));
process.on('SIGHUP', () => shutdown(0));
process.on('uncaughtException', (err) => {
    console.error(err);
    shutdown(1);
});
process.on('unhandledRejection', (err) => {
    console.error(err);
    shutdown(1);
});

(async () => {
    await startOpenClaw();
    startVite();
    await startElectron();
})().catch((err) => {
    console.error(err);
    shutdown(1);
});
