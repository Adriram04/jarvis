import React from 'react';
import { Activity, Bell, Maximize2, Minus, Settings, SlidersHorizontal, X } from 'lucide-react';
import AgendaPanel from './AgendaPanel';
import CapabilitiesPanel from './CapabilitiesPanel';
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
    isMuted,
    isListening,
    isVideoOn,
    isHandTrackingEnabled,
    faceAuthEnabled,
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
    onRefreshCalendar,
    onRefreshPending,
    onRefreshActivity,
    onRefreshIntegrations,
    onConfirmPending,
    onCancelPending,
}) => {
    const timeLabel = currentTime.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
    const dateLabel = currentTime.toLocaleDateString('es-ES', {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
        year: 'numeric',
    });

    const systemItems = dashboardData?.systemItems || [];
    const connections = dashboardData?.connections || [];
    const agenda = dashboardData?.agenda || [];
    const pendingActions = dashboardData?.pendingActions || [];
    const integrations = dashboardData?.integrations || [];
    const recentActivity = dashboardData?.recentActivity || [];
    const capabilities = dashboardData?.capabilities || [];
    const loading = dashboardData?.loading || {};
    const errors = dashboardData?.errors || {};

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
                            <span>{status || 'Sin estado de modelo'}</span>
                            <span>{isConnected ? (isMuted ? 'Micrófono pausado' : 'Micrófono activo') : 'Modelo apagado'}</span>
                            <span>{isVideoOn ? 'Cámara activa' : 'Cámara inactiva'}</span>
                            <span>{isHandTrackingEnabled ? 'Gestos activos' : 'Gestos inactivos'}</span>
                            <span>{faceAuthEnabled ? 'Face Auth activo' : 'Face Auth inactivo'}</span>
                        </div>
                    </header>

                    <div className="jarvis-core-stage">
                        <StatusCard title="Estado del sistema" items={systemItems} className="floating left" />
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

                    <CapabilitiesPanel capabilities={capabilities} onAction={onQuickAction} />

                    <div className="jarvis-bottom-panels">
                        <QuickActions onAction={onQuickAction} />
                        <RecentActivity
                            items={recentActivity}
                            onRefresh={onRefreshActivity}
                            loading={loading.activity}
                            error={errors.activity}
                        />
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
                        onViewCalendar={() => onQuickAction('create-event')}
                        onRefresh={onRefreshCalendar}
                        loading={loading.calendar}
                        error={errors.calendar}
                    />
                    <TasksPanel
                        actions={pendingActions}
                        onAddTask={() => onQuickAction('new-task')}
                        onConfirm={onConfirmPending}
                        onCancel={onCancelPending}
                        loading={loading.pending}
                        error={errors.pending}
                    />
                    <IntegrationsPanel
                        integrations={integrations}
                        onManage={() => onQuickAction('manage-integrations')}
                        onRefresh={onRefreshIntegrations}
                        loading={loading.integrations}
                    />
                </aside>
            </section>

            <MobileDashboard
                currentTime={currentTime}
                isListening={isListening}
                audioLevel={audioLevel}
                onToggleListening={onToggleListening}
                agenda={agenda}
                tasks={pendingActions}
                integrations={integrations}
            />
        </main>
    );
};

export default JarvisDashboard;
