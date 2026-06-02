import React from 'react';
import { Activity, FolderKanban, Maximize2, Minus, X } from 'lucide-react';
import AgendaPanel from './AgendaPanel';
import IntegrationsPanel from './IntegrationsPanel';
import MobileDashboard from './MobileDashboard';
import RecentActivity from './RecentActivity';
import Sidebar from './Sidebar';
import TasksPanel from './TasksPanel';
import ActionsModule from './modules/ActionsModule';
import AutomationsModule from './modules/AutomationsModule';
import Cad3DModule from './modules/Cad3DModule';
import CalendarModule from './modules/CalendarModule';
import ChatModule from './modules/ChatModule';
import DevicesModule from './modules/DevicesModule';
import HomeModule from './modules/HomeModule';
import ProjectsModule from './modules/ProjectsModule';
import SettingsModule from './modules/SettingsModule';
import SocialModule from './modules/SocialModule';
import SystemModule from './modules/SystemModule';
import WebAgentModule from './modules/WebAgentModule';
import { getCalendarDateKey } from '../../services/jarvisDashboardApi';
import { formatPrinterState } from '../../utils/printerStatus';
import './jarvis-dashboard.css';

const moduleTitles = {
    home: ['Inicio', 'Centro de mando personal'],
    chat: ['Chat', 'Conversación viva con Jarvis'],
    calendar: ['Agenda', 'Google Calendar real'],
    actions: ['Acciones', 'Confirmaciones pendientes'],
    automations: ['Automatizaciones', 'Procesos y workflows'],
    social: ['Social', 'LinkedIn y WhatsApp'],
    projects: ['Proyectos', 'Workspace y archivos creados'],
    cad3d: ['CAD / 3D', 'Diseño, slicing e impresión'],
    devices: ['Dispositivos', 'Kasa y smart devices'],
    web: ['Web Agent', 'Automatización web visual'],
    system: ['Sistema', 'Estado técnico real'],
    settings: ['Ajustes', 'Permisos y preferencias'],
};

const JarvisDashboard = ({
    activeModule,
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
    messages,
    onCommandSubmit,
    onToggleListening,
    onQuickAction,
    onModuleChange,
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
    onPrepareLinkedInPost,
    onPublishLinkedInPost,
    onDiscoverKasa,
    onControlKasa,
    onRunWebAgent,
    onRefreshProjects,
    onLoadProjectTree,
    onRefreshAutomations,
    onCreateAutomation,
    onUpdateAutomation,
    onDeleteAutomation,
    onRunAutomation,
    onDispatchAutomationEvent,
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
    const runtime = dashboardData?.runtime || {};
    const activeTitle = moduleTitles[activeModule] || moduleTitles.home;

    const context = {
        ...runtime,
        agenda,
        audioLevel,
        calendarEvents: agenda,
        capabilities,
        connections,
        currentTime,
        errors,
        faceAuthEnabled,
        inputValue,
        integrations,
        isConnected,
        isHandTrackingEnabled,
        isListening,
        isMuted,
        isVideoOn,
        loading,
        messages,
        openClawEvents: recentActivity,
        pendingActions,
        recentActivity,
        setInputValue,
        socketConnected,
        status,
        systemItems,
    };

    const actions = {
        onCancelPending,
        onCommandSubmit,
        onConfirmPending,
        onControlKasa,
        onDiscoverKasa,
        onOpenSettings,
        onPrepareLinkedInPost,
        onPublishLinkedInPost,
        onQuickAction,
        onRefreshActivity,
        onRefreshCalendar,
        onRefreshIntegrations,
        onRefreshPending,
        onRunWebAgent,
        onRefreshProjects,
        onRefreshAutomations,
        onLoadProjectTree,
        onCreateAutomation,
        onUpdateAutomation,
        onDeleteAutomation,
        onRunAutomation,
        onDispatchAutomationEvent,
        onToggleListening,
        setInputValue,
    };

    const moduleProps = { context, actions };
    const activeModuleView = {
        home: <HomeModule {...moduleProps} />,
        chat: <ChatModule {...moduleProps} />,
        calendar: <CalendarModule {...moduleProps} />,
        actions: <ActionsModule {...moduleProps} />,
        automations: <AutomationsModule {...moduleProps} />,
        social: <SocialModule {...moduleProps} />,
        projects: <ProjectsModule {...moduleProps} />,
        cad3d: <Cad3DModule {...moduleProps} />,
        devices: <DevicesModule {...moduleProps} />,
        web: <WebAgentModule {...moduleProps} />,
        system: <SystemModule {...moduleProps} />,
        settings: <SettingsModule {...moduleProps} />,
    }[activeModule] || <HomeModule {...moduleProps} />;

    const userMessages = messages.filter(message => String(message.sender || '').toLowerCase().match(/you|user|tu|tú/)).length;
    const jarvisMessages = messages.filter(message => String(message.sender || '').toLowerCase().match(/jarvis|assistant/)).length;
    const latestMessage = messages[messages.length - 1];
    const todayKey = getCalendarDateKey(currentTime);
    const todayAgenda = agenda.filter(event => (event.startDateKey || getCalendarDateKey(event.start)) === todayKey);
    const homeAgenda = todayAgenda.length ? todayAgenda : agenda.slice(0, 3);
    const projectCount = runtime.projects?.length || 0;

    const renderActiveProjectPanel = () => (
        <section className="jarvis-panel jarvis-current-project-panel">
            <div className="jarvis-panel-header compact">
                <div className="jarvis-panel-title">Proyecto actual activo</div>
                <button type="button" onClick={() => onModuleChange('projects')}>
                    <FolderKanban size={14} /> Ver
                </button>
            </div>
            <strong>{runtime.currentProject || 'No disponible'}</strong>
            <span>{projectCount ? `${projectCount} proyecto(s) detectado(s)` : 'Sin datos de proyectos'}</span>
        </section>
    );

    const renderContextPanel = () => {
        if (activeModule === 'chat') {
            return (
                <>
                    <section className="jarvis-panel jarvis-list-panel">
                        <div className="jarvis-panel-header"><h2>Sesión actual</h2></div>
                        <div className="jarvis-status-chip-row">
                            <span>{socketConnected ? 'Socket OK' : 'Socket Offline'}</span>
                            <span>{isConnected ? (isMuted ? 'Mic pausado' : 'Mic activo') : 'Modelo apagado'}</span>
                            <span>{isListening ? 'Escuchando' : 'En espera'}</span>
                        </div>
                        <div className="jarvis-context-metric"><span>Mensajes tuyos</span><strong>{userMessages}</strong></div>
                        <div className="jarvis-context-metric"><span>Respuestas Jarvis</span><strong>{jarvisMessages}</strong></div>
                        <div className="jarvis-empty-state compact">{latestMessage?.text || 'Sin mensajes todavía.'}</div>
                    </section>
                    <TasksPanel actions={pendingActions} onAddTask={() => onQuickAction('new-task')} onConfirm={onConfirmPending} onCancel={onCancelPending} loading={loading.pending} error={errors.pending} />
                </>
            );
        }

        if (activeModule === 'calendar') {
            return <AgendaPanel events={agenda} dateLabel={dateLabel} onViewCalendar={() => onQuickAction('create-event')} onRefresh={onRefreshCalendar} loading={loading.calendar} error={errors.calendar} />;
        }

        if (activeModule === 'actions') {
            return (
                <>
                    <TasksPanel actions={pendingActions} onAddTask={() => onQuickAction('new-task')} onConfirm={onConfirmPending} onCancel={onCancelPending} loading={loading.pending} error={errors.pending} />
                    <RecentActivity items={recentActivity} onRefresh={onRefreshActivity} loading={loading.activity} error={errors.activity} />
                </>
            );
        }

        if (activeModule === 'automations') {
            const automations = runtime.automations || [];
            return (
                <section className="jarvis-panel jarvis-list-panel">
                    <div className="jarvis-panel-header"><h2>Automatizaciones</h2></div>
                    <div className="jarvis-context-metric"><span>Total</span><strong>{automations.length}</strong></div>
                    <div className="jarvis-context-metric"><span>Activas</span><strong>{automations.filter(item => item.enabled).length}</strong></div>
                    <div className="jarvis-empty-state compact">
                        {automations[0]?.next_run_at ? `Proxima: ${automations[0].next_run_at}` : 'Sin proximas ejecuciones.'}
                    </div>
                </section>
            );
        }

        if (activeModule === 'social') {
            return (
                <>
                    <IntegrationsPanel integrations={integrations} onManage={() => onQuickAction('manage-integrations')} onRefresh={onRefreshIntegrations} loading={loading.integrations} />
                    <RecentActivity items={recentActivity} onRefresh={onRefreshActivity} loading={loading.activity} error={errors.activity} />
                </>
            );
        }

        if (activeModule === 'projects') {
            return (
                <section className="jarvis-panel jarvis-list-panel">
                    <div className="jarvis-panel-header"><h2>Proyecto activo</h2></div>
                    <div className="jarvis-context-metric"><span>Actual</span><strong>{runtime.currentProject || 'No disponible'}</strong></div>
                    <div className="jarvis-context-metric"><span>Proyectos</span><strong>{runtime.projects?.length || 0}</strong></div>
                </section>
            );
        }

        if (activeModule === 'cad3d') {
            return (
                <section className="jarvis-panel jarvis-list-panel">
                    <div className="jarvis-panel-header"><h2>CAD / 3D</h2></div>
                    <div className="jarvis-context-metric"><span>Impresoras</span><strong>{runtime.printerCount || 0}</strong></div>
                    <div className="jarvis-empty-state compact">{runtime.activePrintStatus?.state ? formatPrinterState(runtime.activePrintStatus.state) : runtime.slicingStatus?.message || 'Sin impresión activa.'}</div>
                </section>
            );
        }

        if (activeModule === 'devices') {
            return (
                <section className="jarvis-panel jarvis-list-panel">
                    <div className="jarvis-panel-header"><h2>Dispositivos</h2></div>
                    <div className="jarvis-context-metric"><span>Kasa</span><strong>{runtime.kasaDevices?.length || 0}</strong></div>
                    <div className="jarvis-empty-state compact">{runtime.kasaDevices?.length ? 'Dispositivos detectados.' : 'No hay dispositivos Kasa detectados.'}</div>
                </section>
            );
        }

        if (activeModule === 'web') {
            return (
                <section className="jarvis-panel jarvis-list-panel">
                    <div className="jarvis-panel-header"><h2>Web Agent</h2></div>
                    <div className="jarvis-empty-state compact">{runtime.showBrowserWindow ? 'Agente web abierto.' : 'Agente web cerrado.'}</div>
                    <div className="jarvis-empty-state compact">{runtime.browserData?.logs?.slice(-1)[0] || 'Sin logs web recientes.'}</div>
                </section>
            );
        }

        if (activeModule === 'system') {
            return <RecentActivity items={recentActivity} onRefresh={onRefreshActivity} loading={loading.activity} error={errors.activity} />;
        }

        if (activeModule === 'settings') {
            return (
                <section className="jarvis-panel jarvis-list-panel">
                    <div className="jarvis-panel-header"><h2>Perfil</h2></div>
                    <div className="jarvis-empty-state compact">Usa el bloque de Adrián de la barra lateral para preferencias visuales.</div>
                    <button type="button" className="jarvis-panel-action" onClick={onOpenSettings}>Abrir ajustes</button>
                </section>
            );
        }

        return (
            <>
                <AgendaPanel events={homeAgenda} dateLabel={dateLabel} onViewCalendar={() => onQuickAction('create-event')} onRefresh={onRefreshCalendar} loading={loading.calendar} error={errors.calendar} />
                <TasksPanel actions={pendingActions} onAddTask={() => onQuickAction('new-task')} onConfirm={onConfirmPending} onCancel={onCancelPending} loading={loading.pending} error={errors.pending} />
                <RecentActivity items={recentActivity} onRefresh={onRefreshActivity} loading={loading.activity} error={errors.activity} />
            </>
        );
    };

    return (
        <main className="jarvis-dashboard-root">
            <div className="jarvis-background-grid" aria-hidden="true" />

            <section className="jarvis-desktop-dashboard">
                <Sidebar activeModule={activeModule} onModuleChange={onModuleChange} />

                <section className="jarvis-center-column">
                    <header className="jarvis-hero-copy">
                        <div>
                            <span className="jarvis-module-kicker">{activeTitle[1]}</span>
                            <h1>{activeTitle[0]}, <span>Adrián</span></h1>
                            <p>{activeModule === 'home' ? '¿En qué puedo ayudarte hoy?' : 'Centro de mando modular de Jarvis'}</p>
                        </div>
                        <div className="jarvis-system-strip">
                            <span className={socketConnected ? 'is-online' : 'is-offline'}>{socketConnected ? 'Socket online' : 'Socket offline'}</span>
                            <span>{status || 'Sin estado de modelo'}</span>
                            <span>{isConnected ? (isMuted ? 'Micrófono pausado' : 'Micrófono activo') : 'Modelo apagado'}</span>
                        </div>
                    </header>

                    {activeModuleView}

                </section>

                <aside className="jarvis-right-column">
                    <div className="jarvis-window-controls">
                        <button type="button" onClick={onMinimize} title="Minimizar"><Minus size={15} /></button>
                        <button type="button" onClick={onMaximize} title="Maximizar"><Maximize2 size={15} /></button>
                        <button type="button" onClick={onClose} title="Cerrar"><X size={16} /></button>
                    </div>

                    <div className="jarvis-clock-panel">
                        <div className="jarvis-signal-chip"><Activity size={18} /><span /></div>
                        <strong>{timeLabel}</strong>
                        <span>{dateLabel}</span>
                    </div>

                    {renderActiveProjectPanel()}
                    {renderContextPanel()}
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
