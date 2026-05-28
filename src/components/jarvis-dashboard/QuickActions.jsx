import React from 'react';
import {
    Box,
    CalendarPlus,
    Camera,
    Cpu,
    FileText,
    Hand,
    Linkedin,
    Lightbulb,
    PlusSquare,
    Printer,
    Settings,
    ShieldCheck,
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
    { id: 'toggle-openclaw', label: 'OpenClaw', icon: ShieldCheck },
    { id: 'open-notes', label: 'Notas', icon: FileText },
    { id: 'settings', label: 'Ajustes', icon: Settings },
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
