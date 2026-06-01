import React, { useState } from 'react';
import {
    CalendarDays,
    CheckSquare,
    Cpu,
    FolderKanban,
    GitBranch,
    Home,
    MessageCircle,
    Settings,
    Share2,
    Sparkles,
    Box,
    Globe,
    Lightbulb,
} from 'lucide-react';
import ProfilePanel from './ProfilePanel';

const navigationItems = [
    { id: 'home', label: 'Inicio', icon: Home },
    { id: 'chat', label: 'Chat', icon: MessageCircle },
    { id: 'calendar', label: 'Agenda', icon: CalendarDays },
    { id: 'actions', label: 'Acciones', icon: CheckSquare },
    { id: 'automations', label: 'Automatizaciones', icon: GitBranch },
    { id: 'social', label: 'Social', icon: Share2 },
    { id: 'projects', label: 'Proyectos', icon: FolderKanban },
    { id: 'cad3d', label: 'CAD / 3D', icon: Box },
    { id: 'devices', label: 'Dispositivos', icon: Lightbulb },
    { id: 'web', label: 'Web Agent', icon: Globe },
    { id: 'system', label: 'Sistema', icon: Cpu },
    { id: 'settings', label: 'Ajustes', icon: Settings },
];

const Sidebar = ({ activeModule, onModuleChange }) => {
    const [showProfilePrefs, setShowProfilePrefs] = useState(false);

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

                    return (
                        <button
                            key={item.label}
                            type="button"
                            className={`jarvis-nav-item ${activeModule === item.id ? 'is-active' : ''}`}
                            onClick={() => onModuleChange(item.id)}
                        >
                            <Icon size={20} />
                            <span>{item.label}</span>
                        </button>
                    );
                })}
            </nav>

            <div className="jarvis-sidebar-profile">
                <button
                    type="button"
                    className={`jarvis-user-status ${showProfilePrefs ? 'is-active' : ''}`}
                    onClick={() => setShowProfilePrefs(prev => !prev)}
                    aria-expanded={showProfilePrefs}
                >
                    <div className="jarvis-user-avatar">A</div>
                    <div className="jarvis-user-copy">
                        <strong>Adrián</strong>
                        <span><Sparkles size={11} /> Modo Productividad</span>
                    </div>
                </button>
                <ProfilePanel expanded={showProfilePrefs} />
            </div>
        </aside>
    );
};

export default Sidebar;
