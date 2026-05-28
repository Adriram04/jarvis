import React from 'react';
import { AlertTriangle, CheckCircle2, CircleDashed, RefreshCw } from 'lucide-react';

const IntegrationsPanel = ({ integrations = [], onManage, onRefresh, loading }) => {
    return (
        <section className="jarvis-panel jarvis-list-panel">
            <div className="jarvis-panel-header">
                <h2>Integraciones</h2>
                <div className="jarvis-panel-header-actions">
                    <button type="button" onClick={onRefresh} title="Revisar integraciones">
                        <RefreshCw size={14} /> Revisar
                    </button>
                    <button type="button" onClick={onManage}>Gestionar</button>
                </div>
            </div>
            {loading && <div className="jarvis-empty-state compact">Comprobando integraciones...</div>}
            <div className="jarvis-integration-list">
                {!loading && integrations.length === 0 && <div className="jarvis-empty-state">Sin datos de integraciones</div>}
                {integrations.map((item) => (
                    <article className="jarvis-integration-item" key={item.name}>
                        <div className={`jarvis-integration-icon ${item.tone || ''}`}>{item.shortName}</div>
                        <div>
                            <strong>{item.name}</strong>
                            <span>{item.meta}</span>
                        </div>
                        {item.state === 'connected' && <CheckCircle2 size={16} className="is-ok" />}
                        {item.state === 'error' && <AlertTriangle size={16} className="is-error" />}
                        {item.state !== 'connected' && item.state !== 'error' && <CircleDashed size={16} className="is-muted" />}
                    </article>
                ))}
            </div>
        </section>
    );
};

export default IntegrationsPanel;
