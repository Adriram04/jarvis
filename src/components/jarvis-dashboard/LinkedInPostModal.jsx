import React, { useState } from 'react';
import { X } from 'lucide-react';

const isConfirmationRequired = (result) => {
    const warnings = result?.data?.data?.warnings || result?.data?.warnings || [];
    return Array.isArray(warnings) && warnings.includes('confirmation_required');
};

const LinkedInPostModal = ({ open, onClose, onPrepare, onPublish }) => {
    const [content, setContent] = useState('');
    const [loading, setLoading] = useState(false);
    const [confirming, setConfirming] = useState(false);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');

    if (!open) return null;

    const runPrepare = async () => {
        setError('');
        setNotice('');
        if (!content.trim()) {
            setError('El contenido no puede estar vacío.');
            return;
        }
        setLoading(true);
        const result = await onPrepare(content.trim());
        setLoading(false);
        if (!result?.ok || !result?.success) {
            setError(result?.error || result?.data?.error || 'No se pudo preparar el post.');
            return;
        }
        setNotice(result?.data?.message || result?.data?.data?.summary || result?.data?.summary || 'Post preparado correctamente.');
    };

    const runPublish = async () => {
        setError('');
        setNotice('');
        if (!content.trim()) {
            setError('El contenido no puede estar vacío.');
            return;
        }
        if (!confirming) {
            setConfirming(true);
            setNotice('Revisa el texto y pulsa de nuevo para solicitar publicación.');
            return;
        }
        setLoading(true);
        const result = await onPublish(content.trim());
        setLoading(false);
        setConfirming(false);
        if (!result?.ok || (!result?.success && !isConfirmationRequired(result))) {
            setError(result?.error || result?.data?.error || 'No se pudo solicitar la publicación.');
            return;
        }
        setNotice(result?.data?.message || result?.data?.data?.summary || result?.data?.summary || 'Publicación enviada a Jarvis.');
    };

    return (
        <div className="jarvis-modal-backdrop">
            <section className="jarvis-modal">
                <header>
                    <div>
                        <h2>LinkedIn</h2>
                        <p>Prepara o solicita una publicación. Jarvis mantendrá las confirmaciones externas.</p>
                    </div>
                    <button type="button" onClick={onClose}><X size={18} /></button>
                </header>
                <label className="jarvis-modal-field">
                    Contenido
                    <textarea
                        value={content}
                        onChange={(event) => {
                            setContent(event.target.value);
                            setConfirming(false);
                        }}
                        placeholder="Escribe el post que quieres revisar..."
                    />
                </label>
                {error && <div className="jarvis-soft-error">{error}</div>}
                {notice && <div className="jarvis-soft-success">{notice}</div>}
                <footer>
                    <button type="button" onClick={runPrepare} disabled={loading}>Preparar</button>
                    <button type="button" onClick={runPublish} disabled={loading || !content.trim()}>
                        {confirming ? 'Confirmar publicación' : 'Publicar'}
                    </button>
                </footer>
            </section>
        </div>
    );
};

export default LinkedInPostModal;
