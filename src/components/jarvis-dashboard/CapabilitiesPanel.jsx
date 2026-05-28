import React from 'react';
import {
    Box,
    Camera,
    Cpu,
    Fingerprint,
    Globe,
    Hand,
    Lightbulb,
    Mic,
    Printer,
    ShieldCheck,
} from 'lucide-react';

const iconMap = {
    voice: Mic,
    camera: Camera,
    gestures: Hand,
    auth: Fingerprint,
    cad: Box,
    browser: Globe,
    kasa: Lightbulb,
    printer: Printer,
    simulation: Cpu,
    openclaw: ShieldCheck,
};

const CapabilitiesPanel = ({ capabilities = [], onAction }) => {
    return (
        <section className="jarvis-panel jarvis-capabilities">
            <div className="jarvis-panel-header compact">
                <div className="jarvis-panel-title">Centro de capacidades</div>
            </div>
            <div className="jarvis-capability-grid">
                {capabilities.map((item) => {
                    const Icon = iconMap[item.icon] || Cpu;
                    return (
                        <article className="jarvis-capability-card" key={item.id}>
                            <div className="jarvis-capability-top">
                                <span className={`jarvis-capability-icon ${item.tone || ''}`}><Icon size={18} /></span>
                                <span className={`jarvis-capability-state ${item.stateTone || ''}`}>{item.state}</span>
                            </div>
                            <strong>{item.title}</strong>
                            <p>{item.description}</p>
                            <div className="jarvis-capability-actions">
                                {item.primaryAction && (
                                    <button type="button" onClick={() => onAction(item.primaryAction)}>
                                        {item.primaryLabel}
                                    </button>
                                )}
                                {item.secondaryAction && (
                                    <button type="button" onClick={() => onAction(item.secondaryAction)}>
                                        {item.secondaryLabel}
                                    </button>
                                )}
                            </div>
                        </article>
                    );
                })}
            </div>
        </section>
    );
};

export default CapabilitiesPanel;
