import React, { useMemo, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, ExternalLink, KeyRound, RefreshCw } from 'lucide-react';
import { getCalendarDateKey, reauthGoogleCalendar } from '../../../services/jarvisDashboardApi';

const looksLikeTokenExpired = (msg) => {
    const text = String(msg || '').toLowerCase();
    return text.includes('caducado') || text.includes('invalid_grant') || text.includes('expired') || text.includes('revoked') || text.includes('google_token');
};

const sameDay = (value, date) => {
    if (!value || !date) return false;
    const eventKey = getCalendarDateKey(value?.startDateKey || value?.start || value);
    const dateKey = getCalendarDateKey(date);
    return Boolean(eventKey && dateKey && eventKey === dateKey);
};

const CalendarModule = ({ context, actions }) => {
    const [selectedDate, setSelectedDate] = useState(new Date());
    const [reauthing, setReauthing] = useState(false);
    const [reauthMsg, setReauthMsg] = useState('');
    const { calendarEvents, loading, errors } = context;

    const needsReauth = looksLikeTokenExpired(errors.calendar);

    const handleReauth = async () => {
        setReauthing(true);
        setReauthMsg('Abriendo el navegador para reconectar Google Calendar. Acepta los permisos...');
        const res = await reauthGoogleCalendar();
        if (res.success) {
            setReauthMsg('Google Calendar reconectado. Actualizando agenda...');
            await actions.onRefreshCalendar();
            setReauthMsg('');
        } else {
            setReauthMsg(res.error || 'No se pudo reconectar. Inténtalo de nuevo.');
        }
        setReauthing(false);
    };

    const days = useMemo(() => {
        const first = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1);
        const last = new Date(selectedDate.getFullYear(), selectedDate.getMonth() + 1, 0);
        const offset = (first.getDay() + 6) % 7;
        const items = [];
        for (let i = 0; i < offset; i += 1) items.push(null);
        for (let day = 1; day <= last.getDate(); day += 1) {
            items.push(new Date(selectedDate.getFullYear(), selectedDate.getMonth(), day));
        }
        return items;
    }, [selectedDate]);

    const selectedEvents = calendarEvents.filter(event => sameDay(event, selectedDate));
    const monthLabel = selectedDate.toLocaleDateString('es-ES', { month: 'long', year: 'numeric' });
    const changeMonth = (delta) => {
        setSelectedDate((current) => new Date(current.getFullYear(), current.getMonth() + delta, 1));
    };
    const goToday = () => setSelectedDate(new Date());

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Google Calendar</span>
                    <h2>Agenda</h2>
                </div>
                <div className="jarvis-module-actions">
                    <button type="button" onClick={() => actions.onRefreshCalendar()}><RefreshCw size={14} /> Actualizar</button>
                </div>
            </div>

            {errors.calendar && !needsReauth && <div className="jarvis-soft-error">{errors.calendar}</div>}
            {needsReauth && (
                <div className="jarvis-soft-error" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                    <span>El acceso a Google Calendar ha caducado. Reconecta tu cuenta para volver a ver la agenda.</span>
                    <button
                        type="button"
                        className="jarvis-module-button"
                        disabled={reauthing}
                        onClick={handleReauth}
                        style={{ flexShrink: 0 }}
                    >
                        <KeyRound size={14} /> {reauthing ? 'Reconectando...' : 'Reconectar Google Calendar'}
                    </button>
                </div>
            )}
            {reauthMsg && <div className="jarvis-muted-line">{reauthMsg}</div>}
            {loading.calendar && <div className="jarvis-empty-state compact">Cargando agenda real...</div>}

            <div className="jarvis-calendar-layout">
                <section className="jarvis-panel jarvis-calendar-board">
                    <div className="jarvis-calendar-heading">
                        <div className="jarvis-calendar-title">{monthLabel}</div>
                        <div className="jarvis-calendar-month-controls">
                            <button type="button" onClick={() => changeMonth(-1)} title="Mes anterior">
                                <ChevronLeft size={15} />
                            </button>
                            <button type="button" onClick={goToday} title="Volver a hoy">
                                <CalendarDays size={14} />
                                <span>Hoy</span>
                            </button>
                            <button type="button" onClick={() => changeMonth(1)} title="Mes siguiente">
                                <ChevronRight size={15} />
                            </button>
                        </div>
                    </div>
                    <div className="jarvis-calendar-weekdays">
                        {['L', 'M', 'X', 'J', 'V', 'S', 'D'].map(day => <span key={day}>{day}</span>)}
                    </div>
                    <div className="jarvis-calendar-grid">
                        {days.map((day, index) => {
                            const hasEvents = day && calendarEvents.some(event => sameDay(event, day));
                            const active = day && sameDay(day, selectedDate);
                            return (
                                <button
                                    key={day?.toISOString() || `empty-${index}`}
                                    type="button"
                                    disabled={!day}
                                    className={`${active ? 'is-active' : ''} ${hasEvents ? 'has-events' : ''}`}
                                    onClick={() => day && setSelectedDate(day)}
                                >
                                    {day?.getDate() || ''}
                                </button>
                            );
                        })}
                    </div>
                </section>

                <section className="jarvis-panel jarvis-day-events">
                    <div className="jarvis-panel-title">
                        {selectedDate.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' })}
                    </div>
                    <div className="jarvis-event-list">
                        {selectedEvents.length === 0 && <div className="jarvis-empty-state">Sin eventos próximos.</div>}
                        {selectedEvents.map(event => (
                            <article className="jarvis-event-item module-event" key={event.id}>
                                <span className="jarvis-event-accent" />
                                <div className="jarvis-event-time">
                                    <strong>{event.startTime}</strong>
                                    <span>{event.endTime}</span>
                                </div>
                                <div className="jarvis-event-copy">
                                    <strong>{event.summary}</strong>
                                    <span>{event.location || event.description || 'Sin ubicación'}</span>
                                </div>
                                {event.htmlLink && (
                                    <button type="button" className="jarvis-inline-icon" onClick={() => window.open(event.htmlLink, '_blank')}>
                                        <ExternalLink size={14} />
                                    </button>
                                )}
                            </article>
                        ))}
                    </div>
                </section>
            </div>
        </section>
    );
};

export default CalendarModule;
