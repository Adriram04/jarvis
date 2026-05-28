import React, { useState } from 'react';
import { X } from 'lucide-react';

const emptyForm = {
    title: '',
    start: '',
    end: '',
    location: '',
    description: '',
};

const isConfirmationRequired = (result) => {
    const warnings = result?.data?.data?.warnings || result?.data?.warnings || [];
    return Array.isArray(warnings) && warnings.includes('confirmation_required');
};

const CalendarEventModal = ({ open, onClose, onCreate, onDryRun }) => {
    const [form, setForm] = useState(emptyForm);
    const [loading, setLoading] = useState(false);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');

    if (!open) return null;

    const update = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

    const payload = (dryRun = false) => ({
        title: form.title.trim(),
        summary: form.title.trim(),
        start: form.start,
        end: form.end,
        location: form.location.trim(),
        description: form.description.trim(),
        dry_run: dryRun,
    });

    const run = async (dryRun) => {
        setError('');
        setNotice('');
        if (!form.title.trim() || !form.start || !form.end) {
            setError('Título, inicio y fin son obligatorios.');
            return;
        }
        setLoading(true);
        const result = dryRun ? await onDryRun(payload(true)) : await onCreate(payload(false));
        setLoading(false);
        if (!result?.ok || (!result?.success && !isConfirmationRequired(result))) {
            setError(result?.error || result?.data?.error || 'No se pudo procesar el evento.');
            return;
        }
        const body = result?.data || {};
        setNotice(body?.message || body?.data?.summary || body?.summary || (dryRun ? 'Dry-run completado.' : 'Evento enviado a Jarvis.'));
    };

    return (
        <div className="jarvis-modal-backdrop">
            <section className="jarvis-modal">
                <header>
                    <div>
                        <h2>Crear evento</h2>
                        <p>Google Calendar mediante Jarvis.</p>
                    </div>
                    <button type="button" onClick={onClose}><X size={18} /></button>
                </header>
                <div className="jarvis-modal-grid">
                    <label>
                        Título
                        <input value={form.title} onChange={(event) => update('title', event.target.value)} placeholder="Reunión, entrega, llamada..." />
                    </label>
                    <label>
                        Inicio
                        <input type="datetime-local" value={form.start} onChange={(event) => update('start', event.target.value)} />
                    </label>
                    <label>
                        Fin
                        <input type="datetime-local" value={form.end} onChange={(event) => update('end', event.target.value)} />
                    </label>
                    <label>
                        Ubicación
                        <input value={form.location} onChange={(event) => update('location', event.target.value)} placeholder="Opcional" />
                    </label>
                    <label className="full">
                        Descripción
                        <textarea value={form.description} onChange={(event) => update('description', event.target.value)} placeholder="Opcional" />
                    </label>
                </div>
                {error && <div className="jarvis-soft-error">{error}</div>}
                {notice && <div className="jarvis-soft-success">{notice}</div>}
                <footer>
                    <button type="button" onClick={() => run(true)} disabled={loading}>Dry-run</button>
                    <button type="button" onClick={() => run(false)} disabled={loading}>Crear evento</button>
                </footer>
            </section>
        </div>
    );
};

export default CalendarEventModal;
