import React, { useState } from 'react';
import { Check, Clock, Flag, Pencil, Trash2, X } from 'lucide-react';

const PRIORITY_LABEL = { high: 'Alta', medium: 'Media', low: 'Baja' };

const SubtaskItem = ({ subtask, onToggle, onRename, onDelete }) => {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(subtask.title);

    const completed = Boolean(subtask.completed);

    const commitRename = () => {
        const value = draft.trim();
        setEditing(false);
        if (value && value !== subtask.title) {
            onRename?.(subtask.id, value);
        } else {
            setDraft(subtask.title);
        }
    };

    return (
        <div className={`jarvis-subtask ${completed ? 'is-done' : ''}`}>
            <button
                type="button"
                className="jarvis-subtask-check"
                onClick={() => onToggle?.(subtask.id, !completed)}
                title={completed ? 'Marcar como pendiente' : 'Marcar como completada'}
                aria-pressed={completed}
            >
                {completed && <Check size={13} />}
            </button>

            {editing ? (
                <input
                    className="jarvis-subtask-edit"
                    value={draft}
                    autoFocus
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={commitRename}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') commitRename();
                        if (e.key === 'Escape') { setDraft(subtask.title); setEditing(false); }
                    }}
                />
            ) : (
                <span className="jarvis-subtask-title" onDoubleClick={() => setEditing(true)}>
                    {subtask.title}
                </span>
            )}

            <div className="jarvis-subtask-meta">
                {subtask.priority && (
                    <span className={`jarvis-subtask-chip priority-${subtask.priority}`}>
                        <Flag size={11} /> {PRIORITY_LABEL[subtask.priority] || subtask.priority}
                    </span>
                )}
                {subtask.estimated_duration && (
                    <span className="jarvis-subtask-chip">
                        <Clock size={11} /> {subtask.estimated_duration}
                    </span>
                )}
            </div>

            <div className="jarvis-subtask-actions">
                {editing ? (
                    <button type="button" onClick={commitRename} title="Guardar"><Check size={14} /></button>
                ) : (
                    <button type="button" onClick={() => setEditing(true)} title="Editar"><Pencil size={14} /></button>
                )}
                <button type="button" onClick={() => onDelete?.(subtask.id)} title="Eliminar subtarea">
                    {editing ? <X size={14} /> : <Trash2 size={14} />}
                </button>
            </div>
        </div>
    );
};

export default SubtaskItem;
