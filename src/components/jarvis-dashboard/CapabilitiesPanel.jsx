import React, { useState } from 'react';
import {
    Box,
    Camera,
    ChevronDown,
    ChevronUp,
    Cpu,
    Fingerprint,
    Globe,
    Hand,
    Lightbulb,
    MessageCircle,
    Mic,
    Printer,
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
    openclaw: MessageCircle,
};

const CapabilitiesPanel = ({ capabilities = [], onAction }) => {
    const [expanded, setExpanded] = useState(false);
    const visibleCapabilities = expanded ? capabilities : capabilities.slice(0, 5);
    const hiddenCount = Math.max(0, capabilities.length - visibleCapabilities.length);

    return (
        <section className="jarvis-panel jarvis-capabilities">
            <div className="jarvis-panel-header compact">
                <div className="jarvis-panel-title">Centro de capacidades</div>
                {capabilities.length > 5 && (
                    <button
                        type="button"
                        className="jarvis-expand-button"
                        onClick={() => setExpanded(prev => !prev)}
                    >
                        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        {expanded ? 'Mostrar menos' : `Ver todas (${hiddenCount})`}
                    </button>
                )}
            </div>
            <div className="jarvis-capability-grid">
                {visibleCapabilities.map((item) => {
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
