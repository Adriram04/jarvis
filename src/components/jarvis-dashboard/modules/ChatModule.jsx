import React, { useEffect, useRef } from 'react';
import { Check, Clipboard, RotateCcw, X } from 'lucide-react';
import CommandBar from '../CommandBar';

const senderLabel = (sender = '') => {
    const value = String(sender).toLowerCase();
    if (['you', 'user', 'tu', 'tú'].includes(value)) return 'Tú';
    if (value.includes('jarvis') || value.includes('assistant')) return 'Jarvis';
    return 'Sistema';
};

const messageClass = (sender = '') => {
    const label = senderLabel(sender);
    if (label === 'Tú') return 'user';
    if (label === 'Jarvis') return 'jarvis';
    return 'system';
};

const ChatModule = ({ context, actions }) => {
    const timelineRef = useRef(null);
    const {
        inputValue,
        isConnected,
        isListening,
        isMuted,
        messages,
        pendingActions,
        setInputValue,
        socketConnected,
        status,
    } = context;

    useEffect(() => {
        timelineRef.current?.scrollTo({ top: timelineRef.current.scrollHeight, behavior: 'smooth' });
    }, [messages, pendingActions]);

    const stateText = !socketConnected
        ? 'Desconectado'
        : !isConnected
            ? 'Modelo apagado'
            : isListening
                ? 'Escuchando'
                : isMuted
                    ? 'Micrófono pausado'
                    : status || 'Disponible';

    const copyMessage = async (text) => {
        try {
            await navigator.clipboard.writeText(text);
        } catch {
            // Clipboard may be unavailable in some Electron contexts.
        }
    };

    return (
        <section className="jarvis-module chat">
            <div className="jarvis-module-header">
                <div>
                    <span>Conversación viva</span>
                    <h2>Chat con Jarvis</h2>
                </div>
                <strong className={isListening ? 'is-hot' : ''}>{stateText}</strong>
            </div>

            <div className="jarvis-chat-layout">
                <div className="jarvis-chat-timeline" ref={timelineRef}>
                    {messages.length === 0 && (
                        <div className="jarvis-empty-state">Aún no hay conversación. Escribe o habla con Jarvis para empezar.</div>
                    )}

                    {messages.map((message, index) => (
                        <article className={`jarvis-chat-entry ${messageClass(message.sender)}`} key={`${message.time || 'msg'}-${index}`}>
                            <div className="jarvis-chat-meta">
                                <strong>{senderLabel(message.sender)}</strong>
                                <time>{message.time || ''}</time>
                            </div>
                            <p>{message.text || 'Sin datos'}</p>
                            <div className="jarvis-chat-tools">
                                <button type="button" onClick={() => copyMessage(message.text || '')} title="Copiar">
                                    <Clipboard size={13} /> Copiar
                                </button>
                                {senderLabel(message.sender) === 'Tú' && (
                                    <button type="button" onClick={() => actions.onCommandSubmit(message.text || '')} title="Reenviar comando">
                                        <RotateCcw size={13} /> Reenviar
                                    </button>
                                )}
                            </div>
                        </article>
                    ))}

                </div>

                <aside className="jarvis-chat-side">
                    <h3>Acciones pendientes</h3>
                    {pendingActions.length === 0 && <div className="jarvis-empty-state compact">No hay acciones pendientes.</div>}
                    {pendingActions.map(action => (
                        <article className="jarvis-mini-card" key={action.id}>
                            <strong>{action.human_summary || action.action_type || 'Acción pendiente'}</strong>
                            <span>{action.action_type || 'Sin tipo'}</span>
                            {action.created_at && <time>{action.created_at}</time>}
                            <div className="jarvis-mini-actions">
                                <button type="button" onClick={() => actions.onConfirmPending(action.id)}><Check size={13} /> Confirmar</button>
                                <button type="button" onClick={() => actions.onCancelPending(action.id)}><X size={13} /> Cancelar</button>
                            </div>
                        </article>
                    ))}
                </aside>
            </div>

            <CommandBar
                value={inputValue}
                onChange={setInputValue}
                onSubmit={actions.onCommandSubmit}
                onToggleListening={actions.onToggleListening}
                isListening={isListening}
                isConnected={isConnected}
                placeholder="Habla o escribe a Jarvis..."
            />
        </section>
    );
};

export default ChatModule;
