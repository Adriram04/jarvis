import React from 'react';
import { CalendarPlus, FileText, Linkedin, Mail, PlusSquare } from 'lucide-react';

const actions = [
    { id: 'new-task', label: 'Nueva tarea', icon: PlusSquare },
    { id: 'create-event', label: 'Crear evento', icon: CalendarPlus },
    { id: 'write-email', label: 'Escribir email', icon: Mail },
    { id: 'linkedin-post', label: 'Publicar en LinkedIn', icon: Linkedin },
    { id: 'open-notes', label: 'Abrir notas', icon: FileText },
];

const QuickActions = ({ onAction }) => {
    return (
        <section className="jarvis-panel jarvis-quick-actions">
            <div className="jarvis-panel-title">Acciones rápidas</div>
            <div className="jarvis-action-grid">
                {actions.map((action) => {
                    const Icon = action.icon;
                    return (
                        <button key={action.id} type="button" onClick={() => onAction(action.id)}>
                            <span><Icon size={19} /></span>
                            {action.label}
                        </button>
                    );
                })}
            </div>
        </section>
    );
};

export default QuickActions;
