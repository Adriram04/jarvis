import React from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react';

const RecentActivity = ({ items = [], onRefresh, loading, error }) => {
    return (
        <section className="jarvis-panel jarvis-recent-activity">
            <div className="jarvis-panel-header compact">
                <div className="jarvis-panel-title">Actividad reciente</div>
                <button type="button" onClick={onRefresh}>
                    <RefreshCw size={14} /> Actualizar
                </button>
            </div>
            {error && <div className="jarvis-soft-error">{error}</div>}
            {loading && <div className="jarvis-empty-state compact">Cargando actividad...</div>}
            <div className="jarvis-activity-list">
                {!loading && items.length === 0 && <div className="jarvis-empty-state">Sin actividad reciente</div>}
                {items.map((item) => (
                    <article className="jarvis-activity-item" key={item.id}>
                        {item.success === false ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}
                        <div>
                            <strong>{item.type}{item.channel ? ` · ${item.channel}` : ''}</strong>
                            <span>{item.error || item.message || item.display_target || 'Sin detalle'}</span>
                        </div>
                        <time>{item.timestamp ? new Date(item.timestamp).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }) : ''}</time>
                    </article>
                ))}
            </div>
        </section>
    );
};

export default RecentActivity;
