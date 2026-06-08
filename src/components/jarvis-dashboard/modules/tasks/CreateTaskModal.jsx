import React, { useState } from 'react';
import { X } from 'lucide-react';

const CreateTaskModal = ({ onClose, onCreate }) => {
    const [title, setTitle] = useState('');
    const [description, setDescription] = useState('');
    const [busy, setBusy] = useState(false);

    const submit = async (event) => {
        event.preventDefault();
        const value = title.trim();
        if (!value || busy) return;
        setBusy(true);
        const created = await onCreate?.(value, description.trim());
        setBusy(false);
        if (created) onClose?.();
    };

    return (
        <div className="jarvis-modal-overlay" onClick={onClose}>
            <div className="jarvis-modal" onClick={(e) => e.stopPropagation()}>
                <div className="jarvis-modal-header">
                    <h3>Nueva tarea</h3>
                    <button type="button" onClick={onClose} title="Cerrar"><X size={18} /></button>
                </div>
                <form onSubmit={submit} className="jarvis-modal-body">
                    <label>
                        <span>Nombre de la tarea</span>
                        <input
                            type="text"
                            value={title}
                            autoFocus
                            placeholder="Ej. Tareas para la fiesta"
                            onChange={(e) => setTitle(e.target.value)}
                        />
                    </label>
                    <label>
                        <span>Descripción (opcional)</span>
                        <textarea
                            rows={3}
                            value={description}
                            placeholder="Detalle de la tarea…"
                            onChange={(e) => setDescription(e.target.value)}
                        />
                    </label>
                    <div className="jarvis-modal-actions">
                        <button type="button" className="jarvis-modal-cancel" onClick={onClose}>Cancelar</button>
                        <button type="submit" className="jarvis-modal-confirm" disabled={!title.trim() || busy}>
                            {busy ? 'Creando…' : 'Crear tarea'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default CreateTaskModal;
