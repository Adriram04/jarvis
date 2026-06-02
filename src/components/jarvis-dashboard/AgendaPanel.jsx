import React from 'react';
import { CalendarDays, ExternalLink, RefreshCw } from 'lucide-react';

const AgendaPanel = ({ events = [], dateLabel, onRefresh, loading, error }) => {
    return (
        <section className="jarvis-panel jarvis-list-panel">
            <div className="jarvis-panel-header">
                <h2>Agenda de hoy</h2>
                <div className="jarvis-panel-header-actions">
                    <button type="button" onClick={() => onRefresh()} title="Actualizar agenda">
                        <RefreshCw size={14} /> Actualizar
                    </button>
                </div>
            </div>
            <p className="jarvis-panel-date">{dateLabel}</p>
            {error && <div className="jarvis-soft-error">{error}</div>}
            {loading && <div className="jarvis-empty-state compact">Cargando agenda...</div>}
            <div className="jarvis-event-list">
                {!loading && events.length === 0 && <div className="jarvis-empty-state">Sin eventos próximos</div>}
                {events.map((event) => (
                    <article className="jarvis-event-item" key={event.id}>
                        <div className={`jarvis-event-accent ${event.tone || 'cyan'}`} />
                        <div className="jarvis-event-time">
                            <strong>{event.startTime}</strong>
                            <span>{event.endTime}</span>
                        </div>
                        <div className="jarvis-event-copy">
                            <strong>{event.summary}</strong>
                            <span>{event.location || 'Sin ubicación'}</span>
                        </div>
                        {event.htmlLink ? (
                            <button
                                type="button"
                                className="jarvis-inline-icon"
                                onClick={() => window.open(event.htmlLink, '_blank')}
                                title="Abrir evento"
                            >
                                <ExternalLink size={15} />
                            </button>
                        ) : (
                            <CalendarDays size={16} />
                        )}
                    </article>
                ))}
            </div>
        </section>
    );
};

export default AgendaPanel;
