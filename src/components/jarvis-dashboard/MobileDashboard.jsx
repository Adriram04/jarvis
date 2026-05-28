import React from 'react';
import { CalendarDays, CheckSquare, Home, Menu, MessageCircle, Mic, MoreHorizontal } from 'lucide-react';
import JarvisCore from './JarvisCore';

const MobileDashboard = ({
    currentTime,
    isListening,
    audioLevel,
    onToggleListening,
    agenda = [],
    tasks = [],
    integrations = [],
}) => {
    const nextEvent = agenda[0];
    const connectedIntegrations = integrations.filter((item) => item.state === 'connected').length;
    const dateLabel = currentTime.toLocaleDateString('es-ES', {
        day: 'numeric',
        month: 'long',
    });

    return (
        <section className="jarvis-mobile-dashboard">
            <header className="jarvis-mobile-header">
                <div className="jarvis-brand compact">
                    <div className="jarvis-brand-mark" aria-hidden="true"><span /></div>
                    <div className="jarvis-brand-name">JARVIS</div>
                </div>
                <button type="button" className="jarvis-icon-button" title="Menu">
                    <Menu size={20} />
                </button>
            </header>

            <JarvisCore isListening={isListening} audioLevel={audioLevel} compact />

            <div className="jarvis-mobile-greeting">
                <h1>Buenas tardes, <span>Adrián</span></h1>
                <p>¿En qué puedo ayudarte hoy?</p>
            </div>

            <button
                type="button"
                className={`jarvis-mobile-mic ${isListening ? 'is-listening' : ''}`}
                onClick={onToggleListening}
            >
                <Mic size={30} />
            </button>

            <div className="jarvis-mobile-card-stack">
                <article className="jarvis-panel jarvis-mobile-card">
                    <div>
                        <span>Próximo evento</span>
                        <strong>{nextEvent?.summary || 'Sin eventos'}</strong>
                    </div>
                    <div className="jarvis-mobile-card-meta">
                        <strong>{nextEvent?.startTime || '--:--'}</strong>
                        <span>{nextEvent?.location || dateLabel}</span>
                    </div>
                </article>

                <article className="jarvis-panel jarvis-mobile-card">
                    <div>
                        <span>Acciones pendientes</span>
                        <strong>{tasks.length}</strong>
                    </div>
                    <div className="jarvis-mobile-progress">
                        <span />
                    </div>
                </article>

                <article className="jarvis-panel jarvis-mobile-card integrations">
                    <div>
                        <span>Integraciones</span>
                        <strong>{connectedIntegrations ? `${connectedIntegrations} conectadas` : 'Sin conexiones confirmadas'}</strong>
                    </div>
                    <div className="jarvis-mobile-integration-dots">
                        {integrations.map((item) => <span key={item.name} title={item.name} />)}
                    </div>
                </article>
            </div>

            <nav className="jarvis-mobile-nav" aria-label="Navegación móvil">
                <button type="button" className="is-active"><Home size={18} />Inicio</button>
                <button type="button"><MessageCircle size={18} />Chat</button>
                <button type="button"><CalendarDays size={18} />Agenda</button>
                <button type="button"><CheckSquare size={18} />Tareas</button>
                <button type="button"><MoreHorizontal size={18} />Más</button>
            </nav>
        </section>
    );
};

export default MobileDashboard;
