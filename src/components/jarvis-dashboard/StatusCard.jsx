import React from 'react';

const StatusCard = ({ title, items = [], className = '' }) => {
    return (
        <section className={`jarvis-panel jarvis-status-card ${className}`}>
            <div className="jarvis-panel-title">{title}</div>
            <div className="jarvis-status-list">
                {items.length === 0 && <div className="jarvis-empty-state compact">Sin datos</div>}
                {items.map((item) => (
                    <div className="jarvis-status-row" key={item.label}>
                        <span className={`jarvis-status-dot ${item.connected === false ? 'is-muted' : item.tone || ''}`} />
                        <div className="jarvis-status-main">
                            <span>{item.label}</span>
                            {item.detail && <small>{item.detail}</small>}
                        </div>
                        <strong>{item.value}{item.unit || ''}</strong>
                        {typeof item.percent === 'number' && (
                            <span
                                className="jarvis-meter"
                                style={{ '--metric-value': `${Math.max(4, Math.min(item.percent, 100))}%` }}
                            />
                        )}
                    </div>
                ))}
            </div>
        </section>
    );
};

export default StatusCard;
