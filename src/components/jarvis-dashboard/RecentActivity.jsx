import React from 'react';
import { CheckCheck, MessageCircle, RefreshCw } from 'lucide-react';

const formatTime = (timestamp) => {
    if (!timestamp) return '';
    try {
        const date = new Date(timestamp);
        if (Number.isNaN(date.getTime())) return '';
        const now = new Date();
        const diffMs = now - date;
        const diffMin = Math.floor(diffMs / 60000);
        if (diffMin < 1) return 'ahora';
        if (diffMin < 60) return `${diffMin}m`;
        const diffH = Math.floor(diffMin / 60);
        if (diffH < 24) return `${diffH}h`;
        return date.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' });
    } catch {
        return '';
    }
};

const RecentActivity = ({ items = [], unreadCount = 0, onRefresh, onMarkAllRead, loading, error }) => {
    return (
        <section className="jarvis-panel jarvis-recent-activity">
            <div className="jarvis-panel-header compact">
                <div className="jarvis-panel-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <MessageCircle size={14} />
                    Mensajes WhatsApp
                    {unreadCount > 0 && (
                        <span style={{
                            background: 'var(--jarvis-accent, #22d3ee)',
                            color: '#000',
                            borderRadius: '999px',
                            fontSize: '10px',
                            fontWeight: 700,
                            padding: '1px 6px',
                            lineHeight: '16px',
                        }}>
                            {unreadCount}
                        </span>
                    )}
                </div>
                <div style={{ display: 'flex', gap: '4px' }}>
                    {unreadCount > 0 && onMarkAllRead && (
                        <button type="button" onClick={onMarkAllRead} title="Marcar todos como leídos">
                            <CheckCheck size={14} />
                        </button>
                    )}
                    <button type="button" onClick={onRefresh} title="Actualizar mensajes">
                        <RefreshCw size={14} />
                    </button>
                </div>
            </div>

            {error && <div className="jarvis-soft-error">{error}</div>}
            {loading && <div className="jarvis-empty-state compact">Cargando mensajes...</div>}

            <div className="jarvis-activity-list">
                {!loading && items.length === 0 && (
                    <div className="jarvis-empty-state">Sin mensajes recientes</div>
                )}
                {items.map((msg) => {
                    const isUnread = !msg.read;
                    const sender = msg.display_target || msg.sender_name || msg.sender || msg.target || 'Desconocido';
                    const preview = msg.message || '';
                    const time = formatTime(msg.timestamp || msg.created_at);

                    return (
                        <article
                            className="jarvis-activity-item"
                            key={msg.id}
                            style={{ opacity: isUnread ? 1 : 0.65 }}
                        >
                            <div style={{
                                width: 8,
                                height: 8,
                                borderRadius: '50%',
                                background: isUnread ? 'var(--jarvis-accent, #22d3ee)' : 'transparent',
                                border: isUnread ? 'none' : '1.5px solid currentColor',
                                flexShrink: 0,
                                marginTop: 2,
                            }} />
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <strong style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {sender}
                                </strong>
                                <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.85em' }}>
                                    {preview || <em style={{ opacity: 0.5 }}>Sin contenido</em>}
                                </span>
                            </div>
                            <time style={{ flexShrink: 0, fontSize: '0.75em', opacity: 0.7 }}>{time}</time>
                        </article>
                    );
                })}
            </div>
        </section>
    );
};

export default RecentActivity;
