import React, { useEffect, useMemo, useState } from 'react';
import { Activity, Clock, Play, Plus, RefreshCw, ToggleLeft, ToggleRight, Trash2 } from 'lucide-react';

const defaultWorkflow = {
    steps: [
        {
            action_type: 'list_calendar_events',
            payload: { max_results: 5 },
            human_summary: 'Consultar los proximos eventos del calendario.',
            stop_on_error: true,
        },
    ],
};

const eventTypeOptions = [
    'openclaw.inbound_message',
    'pending_action.created',
    'automation.started',
    'automation.completed',
    'automation.failed',
    'camera.real_person_verified',
    'camera.deepfake_suspected',
    'system.startup',
    'printer.finished',
    'kasa.device_changed',
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

const describeTrigger = (trigger = {}) => {
    if (trigger.type === 'once') return trigger.run_at ? `Una vez: ${new Date(trigger.run_at).toLocaleString('es-ES')}` : 'Una vez: sin fecha';
    if (trigger.type === 'daily') return `Diaria: ${String(trigger.hour ?? 0).padStart(2, '0')}:${String(trigger.minute ?? 0).padStart(2, '0')}`;
    if (trigger.type === 'interval') return `Intervalo: cada ${trigger.minutes || 0} min`;
    if (trigger.type === 'event') return `Evento: ${trigger.event_type || 'sin tipo'}`;
    return 'Manual';
};

const formatDate = (value, fallback = 'No programada') => {
    if (!value) return fallback;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return fallback;
    return date.toLocaleString('es-ES');
};

const stepList = (workflow = {}) => {
    const steps = Array.isArray(workflow) ? workflow : workflow.steps;
    return Array.isArray(steps) ? steps : [];
};

const AutomationsModule = ({ context, actions }) => {
    const { automations = [], automationsError, automationsLoading } = context;
    const [name, setName] = useState('');
    const [triggerType, setTriggerType] = useState('daily');
    const [runAt, setRunAt] = useState(localDateTimeValue());
    const [dailyHour, setDailyHour] = useState('9');
    const [dailyMinute, setDailyMinute] = useState('0');
    const [intervalMinutes, setIntervalMinutes] = useState('60');
    const [eventType, setEventType] = useState(eventTypeOptions[0]);
    const [enabled, setEnabled] = useState(true);
    const [workflowText, setWorkflowText] = useState(JSON.stringify(defaultWorkflow, null, 2));
    const [notice, setNotice] = useState('');
    const [busyId, setBusyId] = useState('');
    const [creating, setCreating] = useState(false);

    useEffect(() => {
        if (!automations.length) {
            actions.onRefreshAutomations?.();
        }
    }, []);

    const sortedAutomations = useMemo(() => [...automations].sort((a, b) => {
        const aNext = a.next_run_at || '9999';
        const bNext = b.next_run_at || '9999';
        return String(aNext).localeCompare(String(bNext));
    }), [automations]);

    const buildTrigger = () => {
        if (triggerType === 'once') {
            return { type: 'once', run_at: runAt ? new Date(runAt).toISOString() : null };
        }
        if (triggerType === 'daily') {
            return { type: 'daily', hour: Number(dailyHour || 0), minute: Number(dailyMinute || 0) };
        }
        if (triggerType === 'interval') {
            return { type: 'interval', minutes: Number(intervalMinutes || 1) };
        }
        if (triggerType === 'event') {
            return { type: 'event', event_type: eventType, filters: {} };
        }
        return { type: 'manual' };
    };

    const create = async (event) => {
        event.preventDefault();
        setNotice('');
        let workflow;
        try {
            workflow = JSON.parse(workflowText);
        } catch {
            setNotice('El workflow no es JSON valido.');
            return;
        }

        setCreating(true);
        const response = await actions.onCreateAutomation?.({
            name: name.trim(),
            trigger: buildTrigger(),
            workflow,
            enabled: triggerType === 'manual' ? false : enabled,
        });
        setCreating(false);

        const automation = getAutomation(response);
        if (response?.success && automation) {
            setName('');
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

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Procesos reales de Jarvis</span>
                    <h2>Automatizaciones</h2>
                </div>
                <button type="button" className="jarvis-module-button" onClick={actions.onRefreshAutomations}>
                    <RefreshCw size={14} /> Actualizar
                </button>
            </div>

            {automationsError && <div className="jarvis-soft-error">{automationsError}</div>}
            {notice && <div className={notice.includes('No se') || notice.includes('JSON') ? 'jarvis-soft-error' : 'jarvis-soft-success'}>{notice}</div>}

            <div className="jarvis-automations-layout">
                <section className="jarvis-panel jarvis-automation-list">
                    <div className="jarvis-panel-title">Automatizaciones guardadas</div>
                    {automationsLoading && <div className="jarvis-empty-state compact">Cargando automatizaciones...</div>}
                    {sortedAutomations.length === 0 && !automationsLoading && <div className="jarvis-empty-state">Sin automatizaciones.</div>}

                    {sortedAutomations.map(automation => {
                        const steps = stepList(automation.workflow);
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

                                <div className="jarvis-automation-state-row">
                                    <span className={automation.enabled ? 'is-good' : ''}>enabled: {automation.enabled ? 'si' : 'no'}</span>
                                    <span className={automation.running ? 'is-running' : ''}><Activity size={12} /> running: {automation.running ? 'si' : 'no'}</span>
                                    <span>runs: {automation.run_count || 0}</span>
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

                                <div className="jarvis-automation-steps">
                                    {steps.length === 0 && <span>Workflow sin pasos.</span>}
                                    {steps.map((step, index) => (
                                        <span key={`${automation.id}-${index}`}>
                                            {index + 1}. {step.action_type} {step.human_summary ? `- ${step.human_summary}` : ''}
                                        </span>
                                    ))}
                                </div>

                                <details className="jarvis-automation-details">
                                    <summary>Ver trigger y workflow</summary>
                                    <pre>{JSON.stringify({ trigger: automation.trigger, workflow: automation.workflow }, null, 2)}</pre>
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

                <form className="jarvis-panel jarvis-automation-form" onSubmit={create}>
                    <div className="jarvis-panel-title"><Plus size={15} /> Nueva automatizacion</div>

                    <label>
                        Nombre
                        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Ej. Revisar agenda diaria" />
                    </label>

                    <label>
                        Trigger
                        <select value={triggerType} onChange={(event) => setTriggerType(event.target.value)}>
                            <option value="daily">Diaria</option>
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

                    {triggerType === 'daily' && (
                        <div className="jarvis-automation-form-row">
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

                    {triggerType === 'event' && (
                        <label>
                            Tipo de evento
                            <select value={eventType} onChange={(event) => setEventType(event.target.value)}>
                                {eventTypeOptions.map(option => (
                                    <option value={option} key={option}>{option}</option>
                                ))}
                            </select>
                        </label>
                    )}

                    <label className="jarvis-automation-check">
                        <input type="checkbox" checked={enabled} disabled={triggerType === 'manual'} onChange={(event) => setEnabled(event.target.checked)} />
                        Activar al crear
                    </label>

                    <label>
                        Workflow JSON
                        <textarea value={workflowText} onChange={(event) => setWorkflowText(event.target.value)} spellCheck="false" />
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
