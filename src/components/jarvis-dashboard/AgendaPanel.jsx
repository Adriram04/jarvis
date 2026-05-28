import React from 'react';
import { CalendarDays } from 'lucide-react';

const AgendaPanel = ({ events = [], dateLabel, onViewCalendar }) => {
    return (
        <section className="jarvis-panel jarvis-list-panel">
            <div className="jarvis-panel-header">
                <h2>Agenda de hoy</h2>
                <button type="button" onClick={onViewCalendar}>Ver calendario</button>
            </div>
            <p className="jarvis-panel-date">{dateLabel}</p>
            <div className="jarvis-event-list">
                {events.map((event) => (
                    <article className="jarvis-event-item" key={`${event.time}-${event.title}`}>
                        <div className={`jarvis-event-accent ${event.tone || 'cyan'}`} />
                        <div className="jarvis-event-time">
                            <strong>{event.time}</strong>
                            <span>{event.end}</span>
                        </div>
                        <div className="jarvis-event-copy">
                            <strong>{event.title}</strong>
                            <span>{event.location}</span>
                        </div>
                        <CalendarDays size={16} />
                    </article>
                ))}
            </div>
        </section>
    );
};

export default AgendaPanel;
