import React, { useState } from 'react';
import {
    Box,
    CalendarPlus,
    Camera,
    ChevronDown,
    ChevronUp,
    Cpu,
    FileText,
    Hand,
    Linkedin,
    Lightbulb,
    MessageCircle,
    PlusSquare,
    Printer,
    Webcam,
} from 'lucide-react';

const actions = [
    { id: 'new-task', label: 'Nueva tarea', icon: PlusSquare },
    { id: 'create-event', label: 'Crear evento', icon: CalendarPlus },
    { id: 'linkedin-post', label: 'LinkedIn', icon: Linkedin },
    { id: 'toggle-video', label: 'Cámara', icon: Camera },
    { id: 'toggle-hand', label: 'Gestos', icon: Hand },
    { id: 'toggle-cad', label: 'CAD', icon: Box },
    { id: 'toggle-browser', label: 'Web Agent', icon: Webcam },
    { id: 'toggle-kasa', label: 'Kasa', icon: Lightbulb },
    { id: 'toggle-printer', label: 'Impresión 3D', icon: Printer },
    { id: 'toggle-simulation', label: 'Simulación', icon: Cpu },
    { id: 'toggle-openclaw', label: 'WhatsApp', icon: MessageCircle },
    { id: 'open-notes', label: 'Notas', icon: FileText },
];

const QuickActions = ({ onAction }) => {
    const [expanded, setExpanded] = useState(false);
    const visibleActions = expanded ? actions : actions.slice(0, 5);
    const hiddenCount = Math.max(0, actions.length - visibleActions.length);

    return (
        <section className="jarvis-panel jarvis-quick-actions">
            <div className="jarvis-panel-header compact">
                <div className="jarvis-panel-title">Acciones rápidas</div>
                {actions.length > 5 && (
                    <button
                        type="button"
                        className="jarvis-expand-button"
                        onClick={() => setExpanded(prev => !prev)}
                    >
                        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        {expanded ? 'Mostrar menos' : `Ver más (${hiddenCount})`}
                    </button>
                )}
            </div>
            <div className="jarvis-action-grid">
                {visibleActions.map((action) => {
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
