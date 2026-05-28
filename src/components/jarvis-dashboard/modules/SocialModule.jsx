import React, { useMemo, useState } from 'react';
import { Linkedin, RefreshCw, Send } from 'lucide-react';

const SocialModule = ({ context, actions }) => {
    const { integrations, openClawEvents, openClawStatus } = context;
    const [content, setContent] = useState('');
    const [notice, setNotice] = useState('');
    const [loading, setLoading] = useState(false);
    const [confirmPublish, setConfirmPublish] = useState(false);

    const statusByName = useMemo(() => new Map(integrations.map(item => [item.name, item])), [integrations]);
    const linkedIn = statusByName.get('LinkedIn');
    const whatsapp = statusByName.get('WhatsApp');

    const prepare = async () => {
        if (!content.trim()) {
            setNotice('No se puede preparar una publicación vacía.');
            return;
        }
        setLoading(true);
        const response = await actions.onPrepareLinkedInPost(content.trim());
        setNotice(response.success ? 'Preparación completada.' : response.error || 'No se pudo preparar.');
        setLoading(false);
        setConfirmPublish(false);
    };

    const publish = async () => {
        if (!content.trim()) {
            setNotice('No se puede publicar contenido vacío.');
            return;
        }
        if (!confirmPublish) {
            setConfirmPublish(true);
            setNotice('Pulsa Publicar otra vez para confirmar.');
            return;
        }
        setLoading(true);
        const response = await actions.onPublishLinkedInPost(content.trim());
        setNotice(response.success ? 'Publicación enviada o pendiente de confirmación.' : response.error || 'No se pudo publicar.');
        setLoading(false);
        setConfirmPublish(false);
    };

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Social real</span>
                    <h2>LinkedIn y WhatsApp</h2>
                </div>
                <button type="button" className="jarvis-module-button" onClick={actions.onRefreshIntegrations}>
                    <RefreshCw size={14} /> Revisar
                </button>
            </div>

            <div className="jarvis-social-layout">
                <section className="jarvis-panel jarvis-social-composer">
                    <div className="jarvis-panel-title"><Linkedin size={15} /> LinkedIn</div>
                    <textarea
                        value={content}
                        onChange={(event) => {
                            setContent(event.target.value);
                            setConfirmPublish(false);
                        }}
                        placeholder="Escribe una publicación para LinkedIn..."
                    />
                    {notice && <div className={notice.includes('No se') ? 'jarvis-soft-error' : 'jarvis-soft-success'}>{notice}</div>}
                    <div className="jarvis-module-actions">
                        <button type="button" disabled={loading} onClick={prepare}>Preparar</button>
                        <button type="button" disabled={loading} onClick={publish}>
                            <Send size={14} /> {confirmPublish ? 'Confirmar publicación' : 'Publicar'}
                        </button>
                    </div>
                    <div className="jarvis-muted-line">Estado LinkedIn: {linkedIn?.shortStatus || linkedIn?.meta || 'Sin datos'}</div>
                </section>

                <section className="jarvis-panel jarvis-social-events">
                    <div className="jarvis-panel-title">WhatsApp / Automatización</div>
                    <div className="jarvis-status-chip-row">
                        <span>{openClawStatus?.success ? 'OpenClaw OK' : 'OpenClaw Offline'}</span>
                        <span>{whatsapp?.shortStatus || whatsapp?.meta || 'Sin datos'}</span>
                    </div>
                    <div className="jarvis-activity-list">
                        {openClawEvents.length === 0 && <div className="jarvis-empty-state">Sin actividad reciente.</div>}
                        {openClawEvents.slice(0, 10).map(event => (
                            <article className="jarvis-activity-item" key={event.id}>
                                <span className={`jarvis-status-dot ${event.success === false ? 'is-muted' : 'green'}`} />
                                <div>
                                    <strong>{event.type || 'evento'}</strong>
                                    <span>{event.message || event.error || event.display_target || 'Sin datos'}</span>
                                </div>
                                <time>{event.timestamp || ''}</time>
                            </article>
                        ))}
                    </div>
                </section>
            </div>
        </section>
    );
};

export default SocialModule;
