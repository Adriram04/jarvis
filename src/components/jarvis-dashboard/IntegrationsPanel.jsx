import React from 'react';
import { CheckCircle2 } from 'lucide-react';

const IntegrationsPanel = ({ integrations = [], onManage }) => {
    return (
        <section className="jarvis-panel jarvis-list-panel">
            <div className="jarvis-panel-header">
                <h2>Integraciones</h2>
                <button type="button" onClick={onManage}>Gestionar</button>
            </div>
            <div className="jarvis-integration-list">
                {integrations.map((item) => (
                    <article className="jarvis-integration-item" key={item.name}>
                        <div className={`jarvis-integration-icon ${item.tone || ''}`}>{item.shortName}</div>
                        <div>
                            <strong>{item.name}</strong>
                            <span>{item.meta}</span>
                        </div>
                        <CheckCircle2 size={16} />
                    </article>
                ))}
            </div>
        </section>
    );
};

export default IntegrationsPanel;
