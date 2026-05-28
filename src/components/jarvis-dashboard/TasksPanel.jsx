import React from 'react';
import { Check, Plus, X } from 'lucide-react';

const TasksPanel = ({ actions = [], onAddTask, onConfirm, onCancel, loading, error }) => {
    return (
        <section className="jarvis-panel jarvis-list-panel">
            <div className="jarvis-panel-header">
                <h2>Acciones pendientes</h2>
                <button type="button" onClick={onAddTask}>Nueva tarea</button>
            </div>
            {error && <div className="jarvis-soft-error">{error}</div>}
            {loading && <div className="jarvis-empty-state compact">Cargando acciones...</div>}
            <div className="jarvis-pending-list">
                {!loading && actions.length === 0 && <div className="jarvis-empty-state">No hay acciones pendientes</div>}
                {actions.map((action) => (
                    <article className="jarvis-pending-item" key={action.id}>
                        <div>
                            <strong>{action.action_type || 'acción'}</strong>
                            <span>{action.human_summary || 'Sin resumen'}</span>
                            {action.created_at && <time>{new Date(action.created_at).toLocaleString('es-ES')}</time>}
                        </div>
                        <div className="jarvis-pending-actions">
                            <button type="button" onClick={() => onConfirm(action.id)} title="Confirmar">
                                <Check size={14} />
                            </button>
                            <button type="button" onClick={() => onCancel(action.id)} title="Cancelar">
                                <X size={14} />
                            </button>
                        </div>
                    </article>
                ))}
            </div>
            <button type="button" className="jarvis-panel-action" onClick={onAddTask}>
                <Plus size={15} /> Preparar tarea
            </button>
        </section>
    );
};

export default TasksPanel;
