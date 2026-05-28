import React from 'react';
import { Lightbulb, RefreshCw } from 'lucide-react';

const DevicesModule = ({ context, actions }) => {
    const { kasaDevices, showKasaWindow } = context;

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Smart devices</span>
                    <h2>Dispositivos</h2>
                </div>
                <div className="jarvis-module-actions">
                    <button type="button" onClick={actions.onDiscoverKasa}><RefreshCw size={14} /> Descubrir</button>
                    <button type="button" onClick={() => actions.onQuickAction('toggle-kasa')}>{showKasaWindow ? 'Cerrar Kasa' : 'Abrir Kasa'}</button>
                </div>
            </div>

            <div className="jarvis-module-grid two">
                {kasaDevices.length === 0 && <div className="jarvis-empty-state">No hay dispositivos Kasa detectados.</div>}
                {kasaDevices.map(device => (
                    <article className="jarvis-module-card" key={device.ip || device.alias}>
                        <Lightbulb size={22} />
                        <span>{device.ip || 'Sin IP'}</span>
                        <strong>{device.alias || 'Dispositivo Kasa'}</strong>
                        <p>{device.is_on ? 'Encendido' : 'Apagado'}</p>
                        <button type="button" onClick={() => actions.onControlKasa(device.ip, device.is_on ? 'off' : 'on')}>
                            {device.is_on ? 'Apagar' : 'Encender'}
                        </button>
                    </article>
                ))}
            </div>
        </section>
    );
};

export default DevicesModule;
