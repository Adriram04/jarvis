import React, { useState } from 'react';
import { Plus, SlidersHorizontal } from 'lucide-react';

const AddSubtaskForm = ({ onAdd }) => {
    const [title, setTitle] = useState('');
    const [duration, setDuration] = useState('');
    const [priority, setPriority] = useState('');
    const [showMeta, setShowMeta] = useState(false);
    const [busy, setBusy] = useState(false);

    const submit = async (event) => {
        event.preventDefault();
        const value = title.trim();
        if (!value || busy) return;
        setBusy(true);
        await onAdd?.({
            title: value,
            estimated_duration: duration.trim() || undefined,
            priority: priority || undefined,
        });
        setBusy(false);
        setTitle('');
        setDuration('');
        setPriority('');
    };

    return (
        <form className="jarvis-add-subtask" onSubmit={submit}>
            <div className="jarvis-add-subtask-row">
                <input
                    type="text"
                    value={title}
                    placeholder="Nueva subtarea…"
                    onChange={(e) => setTitle(e.target.value)}
                />
                <button
                    type="button"
                    className={`jarvis-add-subtask-meta-toggle ${showMeta ? 'is-active' : ''}`}
                    onClick={() => setShowMeta((v) => !v)}
                    title="Prioridad y duración"
                >
                    <SlidersHorizontal size={15} />
                </button>
                <button type="submit" className="jarvis-add-subtask-submit" disabled={!title.trim() || busy}>
                    <Plus size={15} /> Añadir
                </button>
            </div>

            {showMeta && (
                <div className="jarvis-add-subtask-meta">
                    <select value={priority} onChange={(e) => setPriority(e.target.value)}>
                        <option value="">Sin prioridad</option>
                        <option value="high">Prioridad alta</option>
                        <option value="medium">Prioridad media</option>
                        <option value="low">Prioridad baja</option>
                    </select>
                    <input
                        type="text"
                        value={duration}
                        placeholder="Duración estimada (p. ej. 30 min, 2h)"
                        onChange={(e) => setDuration(e.target.value)}
                    />
                </div>
            )}
        </form>
    );
};

export default AddSubtaskForm;
