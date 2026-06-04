import React, { useEffect, useMemo, useState } from 'react';
import { Activity, Clock, History, Layers, Play, Plus, RefreshCw, Shield, ToggleLeft, ToggleRight, Trash2 } from 'lucide-react';

const defaultActions = [
    {
        action_type: 'summarize_day',
        payload: {},
        human_summary: 'Resumen del dia (agenda, mensajes y pendientes).',
        stop_on_error: false,
    },
];

const eventTypeOptions = [
    'whatsapp.message_received',
    'openwa.connected',
    'calendar.event_upcoming',
    'printer.finished',
    'pending_action.created',
    'system.startup',
    'openclaw.inbound_message',
    'camera.real_person_verified',
    'camera.deepfake_suspected',
    'kasa.device_changed',
];

const conditionTypeOptions = [
    'always',
    'message_contains',
    'sender_in_allowlist',
    'provider_connected',
    'time_between',
    'has_calendar_events',
    'project_active',
    'simulation_enabled',
];

const localDateTimeValue = (date = new Date(Date.now() + 60 * 60 * 1000)) => {
    const copy = new Date(date);
    copy.setMinutes(copy.getMinutes() - copy.getTimezoneOffset());
    return copy.toISOString().slice(0, 16);
};

const getAutomation = (response) => (
    response?.data?.data?.automation ||
    response?.data?.automation ||
    response?.raw?.data?.automation ||
    null
);

const scheduleKind = (trigger = {}) => trigger.schedule?.kind || trigger.kind || trigger.type;

const describeTrigger = (trigger = {}) => {
    const type = trigger.type;
    if (type === 'manual') return 'Manual';
    if (type === 'schedule' || ['daily', 'weekly', 'once', 'interval'].includes(type)) {
        const schedule = trigger.schedule || trigger;
        const kind = scheduleKind(trigger);
        if (kind === 'once') return schedule.run_at ? `Una vez: ${new Date(schedule.run_at).toLocaleString('es-ES')}` : 'Una vez: sin fecha';
        if (kind === 'daily') return `Diaria: ${String(schedule.hour ?? 0).padStart(2, '0')}:${String(schedule.minute ?? 0).padStart(2, '0')}`;
        if (kind === 'weekly') {
            const days = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab', 'Dom'];
            return `Semanal: ${days[schedule.weekday ?? 0]} ${String(schedule.hour ?? 0).padStart(2, '0')}:${String(schedule.minute ?? 0).padStart(2, '0')}`;
        }
        if (kind === 'interval') return `Intervalo: cada ${schedule.minutes || 0} min`;
        return 'Programada';
    }
    // Event-name trigger.
    return `Evento: ${type || 'sin tipo'}`;
};

const formatDate = (value, fallback = 'No programada') => {
    if (!value) return fallback;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return fallback;
    return date.toLocaleString('es-ES');
};

const actionList = (automation = {}) => {
    if (Array.isArray(automation.actions)) return automation.actions;
    const steps = automation.workflow?.steps;
    return Array.isArray(steps) ? steps : [];
};

const AutomationsModule = ({ context, actions }) => {
    const {
        automations = [],
        automationsHistory = [],
        automationTemplates = [],
        automationsError,
        automationsLoading,
    } = context;

    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [triggerType, setTriggerType] = useState('daily');
    const [runAt, setRunAt] = useState(localDateTimeValue());
    const [dailyHour, setDailyHour] = useState('9');
    const [dailyMinute, setDailyMinute] = useState('0');
    const [weekday, setWeekday] = useState('0');
    const [intervalMinutes, setIntervalMinutes] = useState('60');
    const [eventType, setEventType] = useState(eventTypeOptions[0]);
    const [safetyPolicy, setSafetyPolicy] = useState('auto');
    const [enabled, setEnabled] = useState(true);
    const [conditionsText, setConditionsText] = useState('[]');
    const [actionsText, setActionsText] = useState(JSON.stringify(defaultActions, null, 2));
    const [notice, setNotice] = useState('');
    const [busyId, setBusyId] = useState('');
    const [creating, setCreating] = useState(false);

    useEffect(() => {
        if (!automations.length) actions.onRefreshAutomations?.();
        actions.onRefreshAutomationsHistory?.();
        actions.onRefreshAutomationTemplates?.();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const sortedAutomations = useMemo(() => [...automations].sort((a, b) => {
        const aNext = a.next_run_at || '9999';
        const bNext = b.next_run_at || '9999';
        return String(aNext).localeCompare(String(bNext));
    }), [automations]);

    const enabledCount = sortedAutomations.filter(item => item.enabled).length;
    const runningCount = sortedAutomations.filter(item => item.running).length;
    const scheduledCount = sortedAutomations.filter(item => Boolean(item.next_run_at)).length;

    const buildTrigger = () => {
        if (triggerType === 'once') {
            return { type: 'schedule', schedule: { kind: 'once', run_at: runAt ? new Date(runAt).toISOString() : null } };
        }
        if (triggerType === 'daily') {
            return { type: 'schedule', schedule: { kind: 'daily', hour: Number(dailyHour || 0), minute: Number(dailyMinute || 0) } };
        }
        if (triggerType === 'weekly') {
            return { type: 'schedule', schedule: { kind: 'weekly', weekday: Number(weekday || 0), hour: Number(dailyHour || 0), minute: Number(dailyMinute || 0) } };
        }
        if (triggerType === 'interval') {
            return { type: 'schedule', schedule: { kind: 'interval', minutes: Number(intervalMinutes || 1) } };
        }
        if (triggerType === 'event') {
            return { type: eventType, filters: {} };
        }
        return { type: 'manual' };
    };

    const isEventTrigger = triggerType === 'event';

    const create = async (event) => {
        event.preventDefault();
        setNotice('');

        let parsedActions;
        try {
            parsedActions = JSON.parse(actionsText);
            if (!Array.isArray(parsedActions)) throw new Error('actions debe ser una lista');
        } catch (err) {
            setNotice('Las acciones no son un JSON valido (debe ser una lista).');
            return;
        }

        let parsedConditions = [];
        try {
            parsedConditions = conditionsText.trim() ? JSON.parse(conditionsText) : [];
            if (!Array.isArray(parsedConditions)) throw new Error('conditions debe ser una lista');
        } catch (err) {
            setNotice('Las condiciones no son un JSON valido (debe ser una lista).');
            return;
        }

        setCreating(true);
        const response = await actions.onCreateAutomation?.({
            name: name.trim(),
            description: description.trim(),
            trigger: buildTrigger(),
            conditions: parsedConditions,
            actions: parsedActions,
            safety: { requires_confirmation: safetyPolicy },
            enabled: triggerType === 'manual' ? false : enabled,
        });
        setCreating(false);

        const automation = getAutomation(response);
        if (response?.success && automation) {
            setName('');
            setDescription('');
            setNotice(`Automatizacion creada: ${automation.name}`);
        } else {
            setNotice(response?.error || 'No se pudo crear la automatizacion.');
        }
    };

    const toggle = async (automation) => {
        setBusyId(automation.id);
        const response = await actions.onUpdateAutomation?.(automation.id, { enabled: !automation.enabled });
        setBusyId('');
        setNotice(response?.success ? 'Estado actualizado.' : response?.error || 'No se pudo actualizar.');
    };

    const run = async (automation) => {
        setBusyId(automation.id);
        const response = await actions.onRunAutomation?.(automation.id);
        setBusyId('');
        const resultStatus = response?.data?.data?.result?.status || response?.data?.data?.status;
        setNotice(response?.success ? `Ejecucion procesada: ${resultStatus || 'OK'}` : response?.error || 'No se pudo ejecutar.');
    };

    const remove = async (automation) => {
        if (!window.confirm(`Eliminar automatizacion "${automation.name}"?`)) return;
        setBusyId(automation.id);
        const response = await actions.onDeleteAutomation?.(automation.id);
        setBusyId('');
        setNotice(response?.success ? 'Automatizacion eliminada.' : response?.error || 'No se pudo eliminar.');
    };

    const applyTemplate = async (template) => {
        setBusyId(template.id);
        const response = await actions.onApplyAutomationTemplate?.(template.id);
        setBusyId('');
        setNotice(response?.success ? `Plantilla aplicada: ${template.name}` : response?.error || 'No se pudo aplicar la plantilla.');
    };

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Eventos, reglas, condiciones y acciones confirmables</span>
                    <h2>Automatizaciones</h2>
                </div>
                <button type="button" className="jarvis-module-button" onClick={() => {
                    actions.onRefreshAutomations?.();
                    actions.onRefreshAutomationsHistory?.();
                }}>
                    <RefreshCw size={14} /> Actualizar
                </button>
            </div>

            {automationsError && <div className="jarvis-soft-error">{automationsError}</div>}
            {notice && <div className={notice.includes('No se') || notice.includes('JSON') ? 'jarvis-soft-error' : 'jarvis-soft-success'}>{notice}</div>}

            <div className="jarvis-automation-overview">
                <div className="jarvis-automation-metric">
                    <Layers size={16} />
                    <span>Guardadas</span>
                    <strong>{sortedAutomations.length}</strong>
                </div>
                <div className="jarvis-automation-metric">
                    <ToggleRight size={16} />
                    <span>Activas</span>
                    <strong>{enabledCount}</strong>
                </div>
                <div className="jarvis-automation-metric">
                    <Clock size={16} />
                    <span>Programadas</span>
                    <strong>{scheduledCount}</strong>
                </div>
                <div className="jarvis-automation-metric">
                    <Activity size={16} />
                    <span>Ejecutando</span>
                    <strong>{runningCount}</strong>
                </div>
            </div>

            {automationTemplates.length > 0 && (
                <section className="jarvis-panel">
                    <div className="jarvis-panel-title"><Layers size={15} /> Plantillas rapidas</div>
                    <div className="jarvis-automation-templates">
                        {automationTemplates.map(template => (
                            <article className="jarvis-automation-template-card" key={template.id}>
                                <div>
                                    <strong>{template.name}</strong>
                                    <span>{template.description}</span>
                                    <small>{describeTrigger(template.trigger)}</small>
                                </div>
                                <button type="button" disabled={busyId === template.id} onClick={() => applyTemplate(template)}>
                                    <Plus size={14} /> Usar
                                </button>
                            </article>
                        ))}
                    </div>
                </section>
            )}

            <div className="jarvis-automations-layout">
                <div className="jarvis-automation-main-column">
                    <section className="jarvis-panel jarvis-automation-list">
                        <div className="jarvis-panel-title">Automatizaciones guardadas</div>
                        {automationsLoading && <div className="jarvis-empty-state compact">Cargando automatizaciones...</div>}
                        {sortedAutomations.length === 0 && !automationsLoading && <div className="jarvis-empty-state">Sin automatizaciones.</div>}

                        {sortedAutomations.map(automation => {
                            const steps = actionList(automation);
                            const conditions = Array.isArray(automation.conditions) ? automation.conditions : [];
                            const safety = automation.safety || {};
                            const isBusy = busyId === automation.id;
                            return (
                                <article className="jarvis-automation-card" key={automation.id}>
                                    <div className="jarvis-automation-card-head">
                                        <div>
                                            <strong>{automation.name}</strong>
                                            <span>{describeTrigger(automation.trigger)}</span>
                                        </div>
                                        <button type="button" disabled={isBusy} onClick={() => toggle(automation)} title={automation.enabled ? 'Desactivar' : 'Activar'}>
                                            {automation.enabled ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                                            {automation.enabled ? 'Activa' : 'Inactiva'}
                                        </button>
                                    </div>

                                    {automation.description && (
                                        <div className="jarvis-automation-summary">{automation.description}</div>
                                    )}

                                    <div className="jarvis-automation-state-row">
                                        <span className={automation.enabled ? 'is-good' : ''}>enabled: {automation.enabled ? 'si' : 'no'}</span>
                                        <span className={automation.running ? 'is-running' : ''}><Activity size={12} /> running: {automation.running ? 'si' : 'no'}</span>
                                        <span>runs: {automation.run_count || 0}</span>
                                        <span><Shield size={12} /> {safety.requires_confirmation || 'auto'}</span>
                                    </div>

                                    <div className="jarvis-automation-meta">
                                        <span><Clock size={13} /> Proxima: {formatDate(automation.next_run_at)}</span>
                                        <span>Ultima: {formatDate(automation.last_run_at, 'Sin ejecuciones')}</span>
                                        <span>Resultado: {automation.last_result_status || 'Sin resultado'}</span>
                                    </div>

                                    {automation.last_result_summary && (
                                        <div className="jarvis-automation-summary">{automation.last_result_summary}</div>
                                    )}
                                    {automation.last_error && (
                                        <div className="jarvis-automation-error">{automation.last_error}</div>
                                    )}

                                    {conditions.length > 0 && (
                                        <div className="jarvis-automation-steps">
                                            <span>Condiciones:</span>
                                            {conditions.map((condition, index) => (
                                                <span key={`${automation.id}-cond-${index}`}>- {condition.type}</span>
                                            ))}
                                        </div>
                                    )}

                                    <div className="jarvis-automation-steps">
                                        {steps.length === 0 && <span>Sin acciones.</span>}
                                        {steps.map((step, index) => (
                                            <span key={`${automation.id}-${index}`}>
                                                {index + 1}. {step.action_type} {step.human_summary ? `- ${step.human_summary}` : ''}
                                            </span>
                                        ))}
                                    </div>

                                    <details className="jarvis-automation-details">
                                        <summary>Ver trigger, condiciones y acciones</summary>
                                        <pre>{JSON.stringify({ trigger: automation.trigger, conditions, actions: steps, safety }, null, 2)}</pre>
                                    </details>

                                    <div className="jarvis-module-actions">
                                        <button type="button" disabled={isBusy || automation.running} onClick={() => run(automation)}>
                                            <Play size={14} /> Ejecutar
                                        </button>
                                        <button type="button" disabled={isBusy} onClick={() => remove(automation)}>
                                            <Trash2 size={14} /> Eliminar
                                        </button>
                                    </div>
                                </article>
                            );
                        })}
                    </section>

                    <section className="jarvis-panel jarvis-automation-history-panel">
                        <div className="jarvis-panel-title"><History size={15} /> Historial de ejecuciones</div>
                        {automationsHistory.length === 0 && <div className="jarvis-empty-state compact">Sin ejecuciones registradas.</div>}
                        <div className="jarvis-automation-history">
                            {automationsHistory.map(item => (
                                <div className={`jarvis-automation-history-row ${item.success ? '' : 'is-error'}`} key={item.id}>
                                    <span className="jarvis-automation-history-type">{item.type}</span>
                                    <span className="jarvis-automation-history-target">{item.display_target || '-'}</span>
                                    <span className="jarvis-automation-history-message">{item.message}</span>
                                    <span className="jarvis-automation-history-date">{formatDate(item.created_at, '')}</span>
                                </div>
                            ))}
                        </div>
                    </section>
                </div>

                <form className="jarvis-panel jarvis-automation-form" onSubmit={create}>
                    <div className="jarvis-panel-title"><Plus size={15} /> Nueva automatizacion</div>

                    <label>
                        Nombre
                        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Ej. Revisar agenda diaria" />
                    </label>

                    <label>
                        Descripcion
                        <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Que hace esta automatizacion" />
                    </label>

                    <label>
                        Trigger
                        <select value={triggerType} onChange={(event) => setTriggerType(event.target.value)}>
                            <option value="daily">Diaria</option>
                            <option value="weekly">Semanal</option>
                            <option value="once">Una vez</option>
                            <option value="interval">Intervalo</option>
                            <option value="event">Evento</option>
                            <option value="manual">Manual</option>
                        </select>
                    </label>

                    {triggerType === 'once' && (
                        <label>
                            Ejecutar en
                            <input type="datetime-local" value={runAt} onChange={(event) => setRunAt(event.target.value)} />
                        </label>
                    )}

                    {(triggerType === 'daily' || triggerType === 'weekly') && (
                        <div className="jarvis-automation-form-row">
                            {triggerType === 'weekly' && (
                                <label>
                                    Dia
                                    <select value={weekday} onChange={(event) => setWeekday(event.target.value)}>
                                        {['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo'].map((day, index) => (
                                            <option value={String(index)} key={day}>{day}</option>
                                        ))}
                                    </select>
                                </label>
                            )}
                            <label>
                                Hora
                                <input type="number" min="0" max="23" value={dailyHour} onChange={(event) => setDailyHour(event.target.value)} />
                            </label>
                            <label>
                                Minuto
                                <input type="number" min="0" max="59" value={dailyMinute} onChange={(event) => setDailyMinute(event.target.value)} />
                            </label>
                        </div>
                    )}

                    {triggerType === 'interval' && (
                        <label>
                            Cada X minutos
                            <input type="number" min="1" value={intervalMinutes} onChange={(event) => setIntervalMinutes(event.target.value)} />
                        </label>
                    )}

                    {isEventTrigger && (
                        <label>
                            Tipo de evento
                            <select value={eventType} onChange={(event) => setEventType(event.target.value)}>
                                {eventTypeOptions.map(option => (
                                    <option value={option} key={option}>{option}</option>
                                ))}
                            </select>
                        </label>
                    )}

                    <label>
                        Seguridad (confirmacion)
                        <select value={safetyPolicy} onChange={(event) => setSafetyPolicy(event.target.value)}>
                            <option value="auto">Auto (segun la accion)</option>
                            <option value="always">Siempre pedir confirmacion</option>
                            <option value="never">Sin friccion extra</option>
                        </select>
                    </label>

                    <label className="jarvis-automation-check">
                        <input type="checkbox" checked={enabled} disabled={triggerType === 'manual'} onChange={(event) => setEnabled(event.target.checked)} />
                        Activar al crear
                    </label>

                    <label>
                        Condiciones JSON (lista). Tipos: {conditionTypeOptions.join(', ')}
                        <textarea className="jarvis-automation-conditions-json" value={conditionsText} onChange={(event) => setConditionsText(event.target.value)} spellCheck="false" rows={4} />
                    </label>

                    <label>
                        Acciones JSON (lista de pasos)
                        <textarea className="jarvis-automation-actions-json" value={actionsText} onChange={(event) => setActionsText(event.target.value)} spellCheck="false" rows={8} />
                    </label>

                    <button type="submit" className="jarvis-module-button" disabled={creating}>
                        <Plus size={14} /> Crear automatizacion
                    </button>
                </form>
            </div>
        </section>
    );
};

export default AutomationsModule;
