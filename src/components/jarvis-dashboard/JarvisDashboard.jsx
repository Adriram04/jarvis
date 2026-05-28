import React from 'react';
import { Activity, Bell, Maximize2, Minus, Settings, SlidersHorizontal, X } from 'lucide-react';
import AgendaPanel from './AgendaPanel';
import CommandBar from './CommandBar';
import IntegrationsPanel from './IntegrationsPanel';
import JarvisCore from './JarvisCore';
import MobileDashboard from './MobileDashboard';
import QuickActions from './QuickActions';
import RecentActivity from './RecentActivity';
import Sidebar from './Sidebar';
import StatusCard from './StatusCard';
import TasksPanel from './TasksPanel';
import './jarvis-dashboard.css';

const JarvisDashboard = ({
    currentTime,
    status,
    socketConnected,
    isConnected,
    isListening,
    isVideoOn,
    isHandTrackingEnabled,
    inputValue,
    setInputValue,
    onCommandSubmit,
    onToggleListening,
    onQuickAction,
    onOpenSettings,
    onMinimize,
    onMaximize,
    onClose,
    dashboardData,
    audioLevel,
}) => {
    const timeLabel = currentTime.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
    const dateLabel = currentTime.toLocaleDateString('es-ES', {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
        year: 'numeric',
    });

    const metrics = dashboardData?.metrics || [];
    const connections = dashboardData?.connections || [];
    const agenda = dashboardData?.agenda || [];
    const tasks = dashboardData?.tasks || [];
    const integrations = dashboardData?.integrations || [];
    const recentActivity = dashboardData?.recentActivity || [];

    return (
        <main className="jarvis-dashboard-root">
            <div className="jarvis-background-grid" aria-hidden="true" />

            <section className="jarvis-desktop-dashboard">
                <Sidebar onOpenSettings={onOpenSettings} />

                <section className="jarvis-center-column">
                    <header className="jarvis-hero-copy">
                        <div>
                            <h1>Buenas tardes, <span>Adrián</span></h1>
                            <p>¿En qué puedo ayudarte hoy?</p>
                        </div>
                        <div className="jarvis-system-strip">
                            <span className={socketConnected ? 'is-online' : 'is-offline'}>{socketConnected ? 'Socket online' : 'Socket offline'}</span>
                            <span>{status}</span>
                            {isVideoOn && <span>Vision activa</span>}
                            {isHandTrackingEnabled && <span>Gestos activos</span>}
                        </div>
                    </header>

                    <div className="jarvis-core-stage">
                        <StatusCard title="Estado del sistema" items={metrics} className="floating left" />
                        <JarvisCore isListening={isListening} audioLevel={audioLevel} />
                        <StatusCard title="Conexiones activas" items={connections} className="floating right" />
                    </div>

                    <CommandBar
                        value={inputValue}
                        onChange={setInputValue}
                        onSubmit={onCommandSubmit}
                        onToggleListening={onToggleListening}
                        isListening={isListening}
                        isConnected={isConnected}
                    />

                    <div className="jarvis-bottom-panels">
                        <QuickActions onAction={onQuickAction} />
                        <RecentActivity items={recentActivity} />
                    </div>
                </section>

                <aside className="jarvis-right-column">
                    <div className="jarvis-window-controls">
                        <button type="button" onClick={onMinimize} title="Minimizar"><Minus size={15} /></button>
                        <button type="button" onClick={onMaximize} title="Maximizar"><Maximize2 size={15} /></button>
                        <button type="button" onClick={onOpenSettings} title="Ajustes"><Settings size={15} /></button>
                        <button type="button" onClick={onClose} title="Cerrar"><X size={16} /></button>
                    </div>

                    <div className="jarvis-clock-panel">
                        <div className="jarvis-signal-chip"><Activity size={18} /><span /></div>
                        <button type="button" className="jarvis-top-icon" title="Notificaciones"><Bell size={17} /></button>
                        <button type="button" className="jarvis-top-icon" onClick={onOpenSettings} title="Preferencias"><SlidersHorizontal size={17} /></button>
                        <strong>{timeLabel}</strong>
                        <span>{dateLabel}</span>
                    </div>

                    <AgendaPanel
                        events={agenda}
                        dateLabel={dateLabel}
                        onViewCalendar={() => onQuickAction('view-calendar')}
                    />
                    <TasksPanel tasks={tasks} onAddTask={() => onQuickAction('new-task')} />
                    <IntegrationsPanel integrations={integrations} onManage={() => onQuickAction('manage-integrations')} />
                </aside>
            </section>

            <MobileDashboard
                currentTime={currentTime}
                isListening={isListening}
                audioLevel={audioLevel}
                onToggleListening={onToggleListening}
                agenda={agenda}
                tasks={tasks}
                integrations={integrations}
            />
        </main>
    );
};

export default JarvisDashboard;
