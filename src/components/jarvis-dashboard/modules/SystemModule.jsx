import React from 'react';
import { Activity, Cpu, DatabaseZap } from 'lucide-react';

const SystemModule = ({ context, actions }) => {
    const {
        activePrintStatus,
        backendStatus,
        connections,
        currentProject,
        faceAuthEnabled,
        isConnected,
        isHandTrackingEnabled,
        isMuted,
        isVideoOn,
        kasaDevices,
        openClawEvents,
        printerCount,
        socketConnected,
        status,
        systemItems,
    } = context;

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Telemetría real</span>
                    <h2>Sistema</h2>
                </div>
                <button type="button" className="jarvis-module-button" onClick={actions.onRefreshActivity}>Actualizar logs</button>
            </div>

            <div className="jarvis-module-grid three">
                {[...systemItems, ...connections].map(item => (
                    <article className="jarvis-module-card compact" key={`${item.label}-${item.value}`}>
                        <DatabaseZap size={18} />
                        <span>{item.label}</span>
                        <strong>{item.value || 'Sin datos'}</strong>
                        {item.detail && <p>{item.detail}</p>}
                    </article>
                ))}
                <article className="jarvis-module-card compact">
                    <Cpu size={18} />
                    <span>Proyecto</span>
                    <strong>{currentProject || 'No disponible'}</strong>
                    <p>Modelo: {status || 'Sin datos'}</p>
                </article>
                <article className="jarvis-module-card compact">
                    <Activity size={18} />
                    <span>Entrada</span>
                    <strong>{socketConnected ? 'Socket OK' : 'Socket Offline'}</strong>
                    <p>{isConnected ? (isMuted ? 'Mic pausado' : 'Mic activo') : 'Modelo apagado'}</p>
                </article>
            </div>

            <section className="jarvis-panel jarvis-system-log">
                <div className="jarvis-panel-title">Estados técnicos</div>
                <div className="jarvis-status-chip-row">
                    <span>Cámara {isVideoOn ? 'activa' : 'inactiva'}</span>
                    <span>Gestos {isHandTrackingEnabled ? 'activos' : 'inactivos'}</span>
                    <span>Face Auth {faceAuthEnabled ? 'activo' : 'inactivo'}</span>
                    <span>Impresoras {printerCount}</span>
                    <span>Kasa {kasaDevices.length}</span>
                    <span>{activePrintStatus?.state || 'Sin impresión activa'}</span>
                </div>
                <div className="jarvis-activity-list">
                    {openClawEvents.length === 0 && <div className="jarvis-empty-state">Sin actividad reciente.</div>}
                    {openClawEvents.slice(0, 20).map(event => (
                        <article className="jarvis-activity-item" key={event.id}>
                            <span className={`jarvis-status-dot ${event.success === false ? 'is-muted' : 'green'}`} />
                            <div>
                                <strong>{event.type || 'evento'}</strong>
                                <span>{event.message || event.error || event.display_target || 'Sin datos'}</span>
                            </div>
                            <time>{event.timestamp || ''}</time>
                        </article>
                    ))}
                </div>
                {backendStatus?.error && <div className="jarvis-soft-error">{backendStatus.error}</div>}
            </section>
        </section>
    );
};

export default SystemModule;
