import React, { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, Image, Linkedin, RefreshCw, Send, Users, X } from 'lucide-react';

const API = 'http://localhost:8000';

const req = async (path, options = {}) => {
    try {
        const res = await fetch(`${API}${path}`, {
            headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
            ...options,
        });
        return await res.json();
    } catch (e) {
        return { success: false, error: String(e) };
    }
};

const TABS = [
    { id: 'contacts', label: 'Contactos', icon: <Users size={13} /> },
    { id: 'groups', label: 'Grupos', icon: <Users size={13} /> },
    { id: 'image', label: 'Enviar imagen', icon: <Image size={13} /> },
    { id: 'linkedin', label: 'LinkedIn', icon: <Linkedin size={13} /> },
];

const SocialModule = ({ context, actions }) => {
    const { integrations } = context;
    const [tab, setTab] = useState('contacts');
    const [contacts, setContacts] = useState([]);
    const [groups, setGroups] = useState([]);
    const [notice, setNotice] = useState('');
    const [noticeType, setNoticeType] = useState('info'); // info | ok | error
    const [busy, setBusy] = useState(false);
    const [search, setSearch] = useState('');

    // Image form
    const [imgTarget, setImgTarget] = useState('');
    const [imgUrl, setImgUrl] = useState('');
    const [imgBase64, setImgBase64] = useState('');
    const [imgCaption, setImgCaption] = useState('');
    const [imgFileName, setImgFileName] = useState('');
    const fileRef = useRef(null);

    // LinkedIn
    const [linkedinContent, setLinkedinContent] = useState('');
    const [confirmPublish, setConfirmPublish] = useState(false);

    const statusByName = new Map((integrations || []).map(i => [i.name, i]));
    const linkedIn = statusByName.get('LinkedIn');
    const whatsapp = statusByName.get('WhatsApp');

    const showNotice = (msg, type = 'info') => {
        setNotice(msg);
        setNoticeType(type);
    };

    // Load local agenda (whatsapp contacts & groups from openclaw targets)
    const loadLocalAgenda = useCallback(async () => {
        const body = await req('/api/openclaw/targets');
        const all = body.data || [];
        setContacts(all.filter(t => t.channel === 'whatsapp' && t.kind !== 'group').sort((a, b) => (a.display_name || '').localeCompare(b.display_name || '')));
        setGroups(all.filter(t => t.channel === 'whatsapp' && t.kind === 'group').sort((a, b) => (a.display_name || '').localeCompare(b.display_name || '')));
    }, []);

    useEffect(() => { loadLocalAgenda(); }, [loadLocalAgenda]);

    const syncContacts = async () => {
        setBusy(true);
        showNotice('Sincronizando contactos desde WhatsApp...', 'info');
        const body = await req('/api/whatsapp/contacts/sync', { method: 'POST', body: '{}' });
        if (body.success) {
            showNotice(body.data?.summary || 'Contactos sincronizados.', 'ok');
            await loadLocalAgenda();
        } else {
            showNotice(body.error || body.data?.summary || 'No se pudo sincronizar.', 'error');
        }
        setBusy(false);
    };

    const syncGroups = async () => {
        setBusy(true);
        showNotice('Sincronizando grupos desde WhatsApp...', 'info');
        const body = await req('/api/whatsapp/groups/sync', { method: 'POST', body: '{}' });
        if (body.success) {
            showNotice(body.data?.summary || 'Grupos sincronizados.', 'ok');
            await loadLocalAgenda();
        } else {
            showNotice(body.error || body.data?.summary || 'No se pudo sincronizar.', 'error');
        }
        setBusy(false);
    };

    const handleFileChange = (e) => {
        const file = e.target.files[0];
        if (!file) return;
        setImgFileName(file.name);
        setImgUrl('');
        const reader = new FileReader();
        reader.onload = (ev) => {
            // Strip "data:image/...;base64," prefix
            const result = ev.target.result;
            const b64 = result.includes(',') ? result.split(',')[1] : result;
            setImgBase64(b64);
        };
        reader.readAsDataURL(file);
    };

    const clearImageFile = () => {
        setImgBase64('');
        setImgFileName('');
        if (fileRef.current) fileRef.current.value = '';
    };

    const sendImage = async () => {
        if (!imgTarget.trim()) { showNotice('Indica el contacto o grupo de destino.', 'error'); return; }
        if (!imgUrl.trim() && !imgBase64) { showNotice('Selecciona una imagen o introduce una URL.', 'error'); return; }
        setBusy(true);
        const payload = {
            target: imgTarget.trim(),
            canonical_target: imgTarget.trim(),
            caption: imgCaption.trim(),
        };
        if (imgUrl.trim()) payload.image_url = imgUrl.trim();
        if (imgBase64) { payload.base64 = imgBase64; payload.mimetype = 'image/jpeg'; }

        const body = await req('/api/whatsapp/send-image', { method: 'POST', body: JSON.stringify(payload) });
        if (body.success) {
            showNotice('Imagen preparada. Confirma la acción pendiente para enviarla.', 'ok');
            setImgTarget(''); setImgUrl(''); setImgCaption(''); clearImageFile();
        } else {
            showNotice(body.error || 'No se pudo preparar la imagen.', 'error');
        }
        setBusy(false);
    };

    const prepareLinkedIn = async () => {
        if (!linkedinContent.trim()) { showNotice('El contenido no puede estar vacío.', 'error'); return; }
        setBusy(true);
        const r = await actions.onPrepareLinkedInPost(linkedinContent.trim());
        showNotice(r.success ? 'Preparación completada.' : r.error || 'Error.', r.success ? 'ok' : 'error');
        setBusy(false);
        setConfirmPublish(false);
    };

    const publishLinkedIn = async () => {
        if (!linkedinContent.trim()) { showNotice('El contenido no puede estar vacío.', 'error'); return; }
        if (!confirmPublish) { setConfirmPublish(true); showNotice('Pulsa Publicar otra vez para confirmar.', 'info'); return; }
        setBusy(true);
        const r = await actions.onPublishLinkedInPost(linkedinContent.trim());
        showNotice(r.success ? 'Publicación enviada o pendiente.' : r.error || 'Error.', r.success ? 'ok' : 'error');
        setBusy(false);
        setConfirmPublish(false);
    };

    const filtered = (list) => {
        const q = search.trim().toLowerCase();
        if (!q) return list;
        return list.filter(t =>
            (t.display_name || '').toLowerCase().includes(q) ||
            (t.canonical_target || '').toLowerCase().includes(q) ||
            (t.aliases || []).some(a => a.toLowerCase().includes(q))
        );
    };

    const noticeClass = noticeType === 'ok' ? 'jarvis-soft-success' : noticeType === 'error' ? 'jarvis-soft-error' : 'jarvis-muted-line';

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>WhatsApp</span>
                    <h2>Contactos y Mensajería</h2>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span style={{ fontSize: '0.75em', opacity: 0.6 }}>
                        {whatsapp?.meta || 'Sin estado'}
                    </span>
                    <button type="button" className="jarvis-module-button" onClick={actions.onRefreshIntegrations}>
                        <RefreshCw size={13} />
                    </button>
                </div>
            </div>

            {/* Tab bar */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 12, flexWrap: 'wrap' }}>
                {TABS.map(t => (
                    <button
                        key={t.id}
                        type="button"
                        onClick={() => { setTab(t.id); setNotice(''); setSearch(''); }}
                        style={{
                            display: 'flex', alignItems: 'center', gap: 4,
                            padding: '4px 10px', borderRadius: 6, fontSize: '0.8em',
                            background: tab === t.id ? 'var(--jarvis-accent, #22d3ee)' : 'transparent',
                            color: tab === t.id ? '#000' : 'inherit',
                            border: '1px solid',
                            borderColor: tab === t.id ? 'var(--jarvis-accent, #22d3ee)' : 'rgba(255,255,255,0.15)',
                            cursor: 'pointer', fontWeight: tab === t.id ? 700 : 400,
                        }}
                    >
                        {t.icon} {t.label}
                        {t.id === 'contacts' && contacts.length > 0 && <span style={{ marginLeft: 2, opacity: 0.7 }}>({contacts.length})</span>}
                        {t.id === 'groups' && groups.length > 0 && <span style={{ marginLeft: 2, opacity: 0.7 }}>({groups.length})</span>}
                    </button>
                ))}
            </div>

            {notice && <div className={noticeClass} style={{ marginBottom: 8 }}>{notice}</div>}

            {/* CONTACTS TAB */}
            {tab === 'contacts' && (
                <div>
                    <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                        <button type="button" className="jarvis-module-button" disabled={busy} onClick={syncContacts}>
                            <RefreshCw size={13} /> Sincronizar contactos
                        </button>
                        <input
                            placeholder="Buscar..."
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            style={{ flex: 1, fontSize: '0.85em', padding: '3px 8px', borderRadius: 4, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'inherit' }}
                        />
                    </div>
                    <div style={{ maxHeight: 340, overflowY: 'auto' }}>
                        {filtered(contacts).length === 0 && (
                            <div className="jarvis-empty-state">
                                {contacts.length === 0 ? 'Sin contactos sincronizados. Pulsa "Sincronizar contactos".' : 'Sin resultados.'}
                            </div>
                        )}
                        {filtered(contacts).map(c => (
                            <article key={c.id} className="jarvis-activity-item" style={{ opacity: c.allowed ? 1 : 0.5 }}>
                                <CheckCircle2 size={13} style={{ color: c.allowed ? 'var(--jarvis-accent, #22d3ee)' : 'currentColor', opacity: c.allowed ? 1 : 0.3, flexShrink: 0 }} />
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <strong style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {c.display_name || c.canonical_target}
                                    </strong>
                                    <span style={{ fontSize: '0.8em', opacity: 0.6 }}>
                                        {c.canonical_target}
                                        {c.aliases?.length > 0 && ` · ${c.aliases.slice(0, 2).join(', ')}`}
                                    </span>
                                </div>
                                <span style={{ fontSize: '0.7em', opacity: 0.5, flexShrink: 0 }}>{c.source || ''}</span>
                            </article>
                        ))}
                    </div>
                </div>
            )}

            {/* GROUPS TAB */}
            {tab === 'groups' && (
                <div>
                    <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                        <button type="button" className="jarvis-module-button" disabled={busy} onClick={syncGroups}>
                            <RefreshCw size={13} /> Sincronizar grupos
                        </button>
                        <input
                            placeholder="Buscar..."
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            style={{ flex: 1, fontSize: '0.85em', padding: '3px 8px', borderRadius: 4, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'inherit' }}
                        />
                    </div>
                    <div style={{ maxHeight: 340, overflowY: 'auto' }}>
                        {filtered(groups).length === 0 && (
                            <div className="jarvis-empty-state">
                                {groups.length === 0 ? 'Sin grupos sincronizados. Pulsa "Sincronizar grupos".' : 'Sin resultados.'}
                            </div>
                        )}
                        {filtered(groups).map(g => (
                            <article key={g.id} className="jarvis-activity-item">
                                <Users size={13} style={{ color: 'var(--jarvis-accent, #22d3ee)', flexShrink: 0 }} />
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <strong style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {g.display_name || g.canonical_target}
                                    </strong>
                                    <span style={{ fontSize: '0.78em', opacity: 0.55, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {g.canonical_target}
                                    </span>
                                </div>
                                <span style={{ fontSize: '0.7em', opacity: 0.5, flexShrink: 0 }}>{g.source || ''}</span>
                            </article>
                        ))}
                    </div>
                </div>
            )}

            {/* IMAGE TAB */}
            {tab === 'image' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <p style={{ fontSize: '0.82em', opacity: 0.65, margin: 0 }}>
                        Elige un contacto o grupo y una imagen (fichero o URL). Se creará una acción pendiente que deberás confirmar.
                    </p>

                    <input
                        placeholder="Contacto o grupo (nombre o número @c.us)"
                        value={imgTarget}
                        onChange={e => setImgTarget(e.target.value)}
                        style={{ fontSize: '0.85em', padding: '5px 8px', borderRadius: 4, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'inherit' }}
                        list="img-contacts-list"
                    />
                    <datalist id="img-contacts-list">
                        {[...contacts, ...groups].map(c => (
                            <option key={c.id} value={c.canonical_target}>{c.display_name}</option>
                        ))}
                    </datalist>

                    {/* File upload */}
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <button
                            type="button"
                            className="jarvis-module-button"
                            onClick={() => fileRef.current?.click()}
                            style={{ flexShrink: 0 }}
                        >
                            <Image size={13} /> {imgFileName || 'Subir imagen'}
                        </button>
                        {imgFileName && (
                            <button type="button" onClick={clearImageFile} style={{ background: 'none', border: 'none', cursor: 'pointer', opacity: 0.6 }}>
                                <X size={13} />
                            </button>
                        )}
                        <input
                            ref={fileRef}
                            type="file"
                            accept="image/*"
                            onChange={handleFileChange}
                            style={{ display: 'none' }}
                        />
                    </div>

                    {/* OR URL */}
                    {!imgBase64 && (
                        <input
                            placeholder="O pega una URL pública de imagen..."
                            value={imgUrl}
                            onChange={e => setImgUrl(e.target.value)}
                            style={{ fontSize: '0.85em', padding: '5px 8px', borderRadius: 4, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'inherit' }}
                        />
                    )}

                    <input
                        placeholder="Caption (opcional)..."
                        value={imgCaption}
                        onChange={e => setImgCaption(e.target.value)}
                        style={{ fontSize: '0.85em', padding: '5px 8px', borderRadius: 4, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'inherit' }}
                    />

                    <button
                        type="button"
                        className="jarvis-module-button"
                        disabled={busy || (!imgUrl && !imgBase64) || !imgTarget}
                        onClick={sendImage}
                        style={{ alignSelf: 'flex-start' }}
                    >
                        <Send size={13} /> Preparar envío de imagen
                    </button>
                </div>
            )}

            {/* LINKEDIN TAB */}
            {tab === 'linkedin' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <div style={{ fontSize: '0.8em', opacity: 0.6 }}>
                        Estado LinkedIn: {linkedIn?.shortStatus || linkedIn?.meta || 'Sin datos'}
                    </div>
                    <textarea
                        value={linkedinContent}
                        onChange={e => { setLinkedinContent(e.target.value); setConfirmPublish(false); }}
                        placeholder="Escribe una publicación para LinkedIn..."
                        rows={5}
                        style={{ fontSize: '0.85em', padding: '6px 8px', borderRadius: 4, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'inherit', resize: 'vertical' }}
                    />
                    <div style={{ display: 'flex', gap: 8 }}>
                        <button type="button" className="jarvis-module-button" disabled={busy} onClick={prepareLinkedIn}>
                            Preparar
                        </button>
                        <button type="button" className="jarvis-module-button" disabled={busy} onClick={publishLinkedIn}>
                            <Send size={13} /> {confirmPublish ? 'Confirmar' : 'Publicar'}
                        </button>
                    </div>
                </div>
            )}
        </section>
    );
};

export default SocialModule;
