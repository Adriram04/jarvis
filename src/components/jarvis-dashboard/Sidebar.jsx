import React from 'react';
import {
    CalendarDays,
    CheckSquare,
    Grid3X3,
    Home,
    Mail,
    MessageCircle,
    Settings,
    Share2,
    Sparkles,
} from 'lucide-react';

const navigationItems = [
    { label: 'Inicio', icon: Home, active: true },
    { label: 'Chat', icon: MessageCircle },
    { label: 'Agenda', icon: CalendarDays },
    { label: 'Tareas', icon: CheckSquare },
    { label: 'Email', icon: Mail },
    { label: 'Social', icon: Share2 },
    { label: 'Apps', icon: Grid3X3 },
    { label: 'Ajustes', icon: Settings },
];

const Sidebar = ({ onOpenSettings }) => {
    return (
        <aside className="jarvis-sidebar">
            <div className="jarvis-brand">
                <div className="jarvis-brand-mark" aria-hidden="true">
                    <span />
                </div>
                <div>
                    <div className="jarvis-brand-name">JARVIS</div>
                    <div className="jarvis-brand-subtitle">Personal OS</div>
                </div>
            </div>

            <nav className="jarvis-nav" aria-label="Navegacion principal">
                {navigationItems.map((item) => {
                    const Icon = item.icon;
                    const handleClick = item.label === 'Ajustes' ? onOpenSettings : undefined;

                    return (
                        <button
                            key={item.label}
                            type="button"
                            className={`jarvis-nav-item ${item.active ? 'is-active' : ''}`}
                            onClick={handleClick}
                        >
                            <Icon size={20} />
                            <span>{item.label}</span>
                        </button>
                    );
                })}
            </nav>

            <div className="jarvis-user-status">
                <div className="jarvis-user-avatar">A</div>
                <div className="jarvis-user-copy">
                    <strong>Adrián</strong>
                    <span><Sparkles size={11} /> Modo Productividad</span>
                </div>
            </div>
        </aside>
    );
};

export default Sidebar;
