import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Activity,
    Clock,
    Lightbulb,
    Palette,
    Pause,
    Play,
    Power,
    Printer,
    RefreshCw,
    RotateCcw,
    Square,
    Sun,
    Thermometer,
    Wifi,
    X,
    Zap,
} from 'lucide-react';

const API_BASE = 'http://localhost:8000';

const deviceIcon = (type) => {
    if (type === 'plug') return <Power size={16} className="text-emerald-300" />;
    if (type === 'strip') return <Palette size={16} className="text-cyan-300" />;
    return <Lightbulb size={16} className="text-yellow-300" />;
};

const formatHsv = (hsv) => {
    if (!hsv) return 'N/A';
    if (Array.isArray(hsv)) return `${hsv[0]} / ${hsv[1]} / ${hsv[2]}`;
    return `${hsv.h} / ${hsv.s} / ${hsv.v}`;
};

const statusTone = (state) => {
    const value = String(state || '').toLowerCase();
    if (value === 'printing') return 'text-green-300 border-green-400/30 bg-green-400/10';
    if (value === 'heating') return 'text-orange-300 border-orange-400/30 bg-orange-400/10';
    if (value === 'paused') return 'text-yellow-300 border-yellow-400/30 bg-yellow-400/10';
    if (value === 'completed') return 'text-cyan-300 border-cyan-400/30 bg-cyan-400/10';
    if (value === 'cancelled') return 'text-red-300 border-red-400/30 bg-red-400/10';
    return 'text-white/50 border-white/10 bg-white/5';
};

const SimulationDashboard = ({ socket, position, onClose, onMouseDown, zIndex = 45 }) => {
    const [state, setState] = useState({ simulation_mode: false, kasa_simulation: false, printer_simulation: false });
    const [devices, setDevices] = useState([]);
    const [printers, setPrinters] = useState([]);
    const [logs, setLogs] = useState([]);
    const [busy, setBusy] = useState(false);

    const active = Boolean(state.simulation_mode);

    const appendLog = useCallback((message) => {
        if (!message) return;
        const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        setLogs(prev => [{ timestamp, message }, ...prev].slice(0, 12));
    }, []);

    const loadSnapshot = useCallback(async (silent = true) => {
        try {
            const response = await fetch(`${API_BASE}/api/simulation/status`);
            const data = await response.json();
            setState(data.state || {});
            setDevices(data.kasa_devices || []);
            setPrinters(data.printers || []);
            if (!silent) appendLog('Estado de simulacion actualizado');
        } catch (err) {
            if (!silent) appendLog(`No se pudo actualizar: ${err.message}`);
        }
    }, [appendLog]);

    const postAction = useCallback(async (path, message, body) => {
        setBusy(true);
        try {
            await fetch(`${API_BASE}${path}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body ? JSON.stringify(body) : undefined,
            });
            appendLog(message);
            await loadSnapshot(true);
        } catch (err) {
            appendLog(`Accion no completada: ${err.message}`);
        } finally {
            setBusy(false);
        }
    }, [appendLog, loadSnapshot]);

    useEffect(() => {
        loadSnapshot(true);
        const timer = setInterval(() => loadSnapshot(true), active ? 1000 : 2000);
        return () => clearInterval(timer);
    }, [active, loadSnapshot]);

    useEffect(() => {
        if (!socket) return undefined;

        const onStatus = (nextState) => setState(nextState || {});
        const onDevices = (nextDevices) => setDevices(nextDevices || []);
        const onPrinters = (nextPrinters) => setPrinters(nextPrinters || []);
        const onEvent = (event) => appendLog(event?.message);

        socket.on('simulation_status', onStatus);
        socket.on('simulation_kasa_devices', onDevices);
        socket.on('simulation_printers', onPrinters);
        socket.on('simulation_event', onEvent);

        return () => {
            socket.off('simulation_status', onStatus);
            socket.off('simulation_kasa_devices', onDevices);
            socket.off('simulation_printers', onPrinters);
            socket.off('simulation_event', onEvent);
        };
    }, [appendLog, socket]);

    const badgeText = active ? 'Modo simulacion activo' : 'Modo simulacion desactivado';
    const sortedLogs = useMemo(() => logs, [logs]);

    return (
        <div
            id="simulation"
            onMouseDown={onMouseDown}
            style={{
                position: 'absolute',
                left: position.x,
                top: position.y,
                transform: 'translate(-50%, -50%)',
                width: '780px',
                maxHeight: '78vh',
                zIndex,
            }}
            className="pointer-events-auto backdrop-blur-xl bg-black/85 border border-cyan-400/30 rounded-lg shadow-[0_0_40px_rgba(34,211,238,0.16)] overflow-hidden flex flex-col"
        >
            <div data-drag-handle className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-white/5 cursor-grab active:cursor-grabbing">
                <div className="flex items-center gap-3">
                    <Activity size={18} className={active ? 'text-green-300' : 'text-white/40'} />
                    <div>
                        <div className="text-sm font-bold tracking-widest text-cyan-100 uppercase">Simulation Dashboard</div>
                        <div className={`inline-flex mt-1 px-2 py-0.5 rounded border text-[10px] uppercase tracking-wider ${active ? 'text-green-300 border-green-400/30 bg-green-400/10' : 'text-white/40 border-white/10 bg-white/5'}`}>
                            {badgeText}
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        disabled={busy}
                        onClick={() => postAction('/api/simulation/activate', 'Modo simulacion activado')}
                        className="px-3 py-1.5 rounded border border-green-400/30 bg-green-400/10 text-green-300 text-xs hover:bg-green-400/20 disabled:opacity-50"
                    >
                        Activar
                    </button>
                    <button
                        disabled={busy}
                        onClick={() => postAction('/api/simulation/deactivate', 'Modo simulacion desactivado')}
                        className="px-3 py-1.5 rounded border border-red-400/30 bg-red-400/10 text-red-300 text-xs hover:bg-red-400/20 disabled:opacity-50"
                    >
                        Desactivar
                    </button>
                    <button
                        disabled={busy}
                        onClick={() => postAction('/api/simulation/reset', 'Demo reiniciada')}
                        className="p-1.5 rounded border border-cyan-400/20 text-cyan-300 hover:bg-cyan-400/10 disabled:opacity-50"
                        title="Reiniciar demo"
                    >
                        <RotateCcw size={14} />
                    </button>
                    <button
                        onClick={() => loadSnapshot(false)}
                        className="p-1.5 rounded border border-white/10 text-white/50 hover:text-cyan-300 hover:bg-white/5"
                        title="Actualizar"
                    >
                        <RefreshCw size={14} />
                    </button>
                    <button onClick={onClose} className="p-1.5 rounded text-white/40 hover:text-white hover:bg-white/10">
                        <X size={16} />
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-[1fr_1fr_230px] gap-4 p-4 overflow-y-auto custom-scrollbar">
                <section>
                    <div className="flex items-center justify-between mb-3">
                        <h3 className="text-xs font-bold uppercase tracking-widest text-yellow-200/80">Kasa simulados</h3>
                        <button
                            disabled={!active || busy}
                            onClick={() => loadSnapshot(false)}
                            className="text-[10px] text-yellow-200/60 hover:text-yellow-200 disabled:opacity-30"
                        >
                            Detectar
                        </button>
                    </div>
                    <div className="space-y-3">
                        {devices.map(device => (
                            <div key={device.ip} className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
                                <div className="flex items-start justify-between gap-2">
                                    <div className="flex items-center gap-2 min-w-0">
                                        {deviceIcon(device.type)}
                                        <div className="min-w-0">
                                            <div className="text-sm font-bold text-white truncate">{device.alias}</div>
                                            <div className="text-[10px] text-white/40 truncate">{device.model} | {device.ip}</div>
                                        </div>
                                    </div>
                                    <button
                                        disabled={!active || busy}
                                        onClick={() => postAction(`/api/simulation/kasa/${encodeURIComponent(device.ip)}/${device.is_on ? 'off' : 'on'}`, `${device.alias} ${device.is_on ? 'apagada' : 'encendida'}`)}
                                        className={`p-1.5 rounded-full border ${device.is_on ? 'text-green-300 border-green-400/30 bg-green-400/10' : 'text-white/40 border-white/10 bg-white/5'} disabled:opacity-40`}
                                    >
                                        <Power size={14} />
                                    </button>
                                </div>

                                <div className="grid grid-cols-2 gap-2 mt-3 text-[10px] text-white/60">
                                    <div className="flex items-center gap-1"><Wifi size={11} /> {device.wifi_signal} dBm</div>
                                    <div className="flex items-center gap-1"><Zap size={11} /> {device.energy_w ?? 0} W</div>
                                    <div className="flex items-center gap-1"><Sun size={11} /> {device.brightness ?? 'N/A'}%</div>
                                    <div className="flex items-center gap-1"><Palette size={11} /> {formatHsv(device.hsv)}</div>
                                </div>

                                {device.has_brightness && (
                                    <input
                                        type="range"
                                        min="0"
                                        max="100"
                                        value={device.brightness ?? 0}
                                        disabled={!active || busy}
                                        onChange={(e) => postAction(`/api/simulation/kasa/${encodeURIComponent(device.ip)}/brightness`, `${device.alias} brillo ${e.target.value}%`, { brightness: Number(e.target.value) })}
                                        className="mt-3 w-full h-1 bg-white/10 rounded-full appearance-none cursor-pointer accent-cyan-300 disabled:opacity-40"
                                    />
                                )}
                                {device.has_color && (
                                    <div className="flex gap-2 mt-3">
                                        {[
                                            ['azul', 'bg-blue-400'],
                                            ['cyan', 'bg-cyan-300'],
                                            ['verde', 'bg-green-400'],
                                            ['morado', 'bg-purple-400'],
                                        ].map(([color, className]) => (
                                            <button
                                                key={color}
                                                disabled={!active || busy}
                                                onClick={() => postAction(`/api/simulation/kasa/${encodeURIComponent(device.ip)}/color`, `${device.alias} color ${color}`, { color })}
                                                className={`w-5 h-5 rounded-full border border-white/40 ${className} disabled:opacity-40`}
                                                title={color}
                                            />
                                        ))}
                                    </div>
                                )}
                                <div className="mt-2 text-[10px] text-white/30">Actualizado: {device.last_updated || 'N/A'}</div>
                            </div>
                        ))}
                    </div>
                </section>

                <section>
                    <div className="flex items-center justify-between mb-3">
                        <h3 className="text-xs font-bold uppercase tracking-widest text-green-200/80">Impresoras simuladas</h3>
                        <button
                            disabled={!active || busy}
                            onClick={() => loadSnapshot(false)}
                            className="text-[10px] text-green-200/60 hover:text-green-200 disabled:opacity-30"
                        >
                            Detectar
                        </button>
                    </div>
                    <div className="space-y-3">
                        {printers.map(printer => {
                            const status = printer.status || printer;
                            const progress = Number(status.progress_percent || 0);
                            return (
                                <div key={printer.host || status.host} className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
                                    <div className="flex items-start justify-between gap-2">
                                        <div className="min-w-0">
                                            <div className="flex items-center gap-2 text-sm font-bold text-white truncate">
                                                <Printer size={15} className="text-green-300" />
                                                {printer.name || status.name}
                                            </div>
                                            <div className="text-[10px] text-white/40 truncate">{status.printer_type} | {status.host}:{status.port}</div>
                                        </div>
                                        <span className={`px-2 py-0.5 rounded border text-[10px] uppercase ${statusTone(status.state)}`}>
                                            {status.state}
                                        </span>
                                    </div>

                                    <div className="mt-3">
                                        <div className="flex justify-between text-[10px] text-white/50 mb-1">
                                            <span>{status.filename || 'sin archivo'}</span>
                                            <span>{progress.toFixed(1)}%</span>
                                        </div>
                                        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                                            <div className="h-full bg-green-400 transition-all duration-500" style={{ width: `${progress}%` }} />
                                        </div>
                                    </div>

                                    <div className="simulation-printer mt-3" style={{ '--progress': `${progress}%` }}>
                                        <div className="simulation-printer-head" />
                                        <div className="simulation-printer-part" style={{ height: `${Math.max(5, progress * 0.42)}px` }} />
                                        <div className="simulation-printer-bed" />
                                    </div>

                                    <div className="grid grid-cols-2 gap-2 mt-3 text-[10px] text-white/60">
                                        <div className="flex items-center gap-1"><Thermometer size={11} /> H {status.temperatures?.hotend?.current} / {status.temperatures?.hotend?.target}</div>
                                        <div className="flex items-center gap-1"><Thermometer size={11} /> B {status.temperatures?.bed?.current} / {status.temperatures?.bed?.target}</div>
                                        <div className="flex items-center gap-1"><Clock size={11} /> {status.time_elapsed}</div>
                                        <div className="flex items-center gap-1"><Clock size={11} /> {status.time_remaining}</div>
                                    </div>

                                    <div className="grid grid-cols-4 gap-2 mt-3">
                                        <button disabled={!active || busy} onClick={() => postAction(`/api/simulation/printers/${encodeURIComponent(status.host)}/start`, `Impresion demo iniciada en ${status.printer}`, { filename: 'jarvis_demo_part.gcode' })} className="p-1.5 rounded border border-green-400/25 text-green-300 bg-green-400/10 hover:bg-green-400/20 disabled:opacity-40"><Play size={13} /></button>
                                        <button disabled={!active || busy} onClick={() => postAction(`/api/simulation/printers/${encodeURIComponent(status.host)}/pause`, `Impresion pausada en ${status.printer}`)} className="p-1.5 rounded border border-yellow-400/25 text-yellow-300 bg-yellow-400/10 hover:bg-yellow-400/20 disabled:opacity-40"><Pause size={13} /></button>
                                        <button disabled={!active || busy} onClick={() => postAction(`/api/simulation/printers/${encodeURIComponent(status.host)}/resume`, `Impresion reanudada en ${status.printer}`)} className="p-1.5 rounded border border-cyan-400/25 text-cyan-300 bg-cyan-400/10 hover:bg-cyan-400/20 disabled:opacity-40"><Play size={13} /></button>
                                        <button disabled={!active || busy} onClick={() => postAction(`/api/simulation/printers/${encodeURIComponent(status.host)}/cancel`, `Impresion cancelada en ${status.printer}`)} className="p-1.5 rounded border border-red-400/25 text-red-300 bg-red-400/10 hover:bg-red-400/20 disabled:opacity-40"><Square size={13} /></button>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </section>

                <section>
                    <h3 className="text-xs font-bold uppercase tracking-widest text-cyan-200/80 mb-3">Eventos</h3>
                    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-3 min-h-[360px] max-h-[560px] overflow-y-auto custom-scrollbar">
                        {sortedLogs.length === 0 ? (
                            <div className="text-xs text-white/30">Sin eventos todavia.</div>
                        ) : (
                            <div className="space-y-2">
                                {sortedLogs.map((entry, index) => (
                                    <div key={`${entry.timestamp}-${index}`} className="text-[10px] leading-relaxed border-b border-white/5 pb-2 last:border-0">
                                        <span className="text-cyan-300/60">{entry.timestamp}</span>
                                        <div className="text-white/70">{entry.message}</div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </section>
            </div>
        </div>
    );
};

export default SimulationDashboard;
