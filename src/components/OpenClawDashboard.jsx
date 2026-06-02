import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle,
    CheckCircle2,
    ClipboardCheck,
    FileText,
    MessageCircle,
    RefreshCw,
    Send,
    ShieldCheck,
    Trash2,
    UserPlus,
    Users,
    X,
} from 'lucide-react';

const API_BASE = 'http://localhost:8000';

const emptyTargetForm = {
    channel: 'whatsapp',
    kind: 'auto',
    display_name: '',
    raw_target: '',
    canonical_target: '',
    aliases: '',
    relationship: '',
    favorite: false,
    allowed: false,
};

const extractJson = (response) => {
    const data = response?.data;
    return data?.raw?.json ?? data?.raw ?? data;
};

const asArray = (value) => {
    if (Array.isArray(value)) return value;
    if (Array.isArray(value?.items)) return value.items;
    if (Array.isArray(value?.messages)) return value.messages;
    if (Array.isArray(value?.peers)) return value.peers;
    if (Array.isArray(value?.groups)) return value.groups;
    return [];
};

const targetLabel = (target) => target?.display_name || target?.display_target || target?.raw_target || target?.canonical_target || target?.target || 'Target';

const compactText = (value) => {
    if (value === null || typeof value === 'undefined') return '';
    if (typeof value === 'string') return value;
    return JSON.stringify(value);
};

const OpenClawDashboard = ({ position, onClose, onMouseDown, zIndex = 45 }) => {
    const [status, setStatus] = useState(null);
    const [selfAccount, setSelfAccount] = useState(null);
    const [groups, setGroups] = useState([]);
    const [targets, setTargets] = useState([]);
    const [events, setEvents] = useState([]);
    const [pendingActions, setPendingActions] = useState([]);
    const [rules, setRules] = useState([]);
    const [conversation, setConversation] = useState([]);
    const [selectedTargetId, setSelectedTargetId] = useState('');
    const [readLimit, setReadLimit] = useState(10);
    const [testMessage, setTestMessage] = useState('Hola desde Jarvis');
    const [targetForm, setTargetForm] = useState(emptyTargetForm);
    const [targetSearch, setTargetSearch] = useState('');
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState('');
    const [allowlistError, setAllowlistError] = useState('');
    const [importSummary, setImportSummary] = useState(null);

    const selectedTarget = useMemo(
        () => targets.find(target => target.id === selectedTargetId) || targets[0],
        [selectedTargetId, targets]
    );

    const filteredTargets = useMemo(() => {
        const query = targetSearch.trim().toLowerCase();
        if (!query) return targets;
        return targets.filter(target => [
            target.display_name,
            target.raw_target,
            target.canonical_target,
            target.relationship,
            ...(target.aliases || []),
        ].some(value => compactText(value).toLowerCase().includes(query)));
    }, [targetSearch, targets]);

    const requestJson = useCallback(async (path, options = {}) => {
        const { allowFailure, ...fetchOptions } = options;
        const response = await fetch(`${API_BASE}${path}`, {
            headers: { 'Content-Type': 'application/json', ...(fetchOptions.headers || {}) },
            ...fetchOptions,
        });
        const body = await response.json();
        if (!allowFailure && (!response.ok || body?.success === false)) {
            const error = body?.error || body?.data?.summary || 'OpenClaw request failed.';
            if (body?.data?.code === 'OPENCLAW_WHATSAPP_ALLOWLIST_BLOCKED' || body?.code === 'OPENCLAW_WHATSAPP_ALLOWLIST_BLOCKED') {
                setAllowlistError(error);
            }
            throw new Error(error);
        }
        return body;
    }, []);

    const loadDashboard = useCallback(async (silent = true) => {
        setBusy(true);
        try {
            const [statusRes, selfRes, groupsRes, targetsRes, eventsRes, pendingRes, rulesRes] = await Promise.allSettled([
                requestJson('/api/openclaw/status', { allowFailure: true }),
                requestJson('/api/openclaw/directory/self', { allowFailure: true }),
                requestJson('/api/openclaw/directory/groups', { allowFailure: true }),
                requestJson('/api/openclaw/targets'),
                requestJson('/api/openclaw/events?limit=30'),
                fetch(`${API_BASE}/api/pending-actions`).then(res => res.json()),
                fetch(`${API_BASE}/api/openclaw/autopilot/rules`).then(res => res.json()),
            ]);

            if (statusRes.status === 'fulfilled') setStatus(statusRes.value.data);
            if (selfRes.status === 'fulfilled') setSelfAccount(extractJson(selfRes.value));
            if (groupsRes.status === 'fulfilled') setGroups(asArray(extractJson(groupsRes.value)));
            if (targetsRes.status === 'fulfilled') {
                const nextTargets = targetsRes.value.data || [];
                setTargets(nextTargets);
                setSelectedTargetId(prev => prev || nextTargets[0]?.id || '');
            }
            if (eventsRes.status === 'fulfilled') setEvents(eventsRes.value.data || []);
            if (pendingRes.status === 'fulfilled') {
                setPendingActions((pendingRes.value.actions || []).filter(action => String(action.action_type || '').includes('openclaw') || compactText(action.payload).includes('whatsapp')));
            }
            if (rulesRes.status === 'fulfilled') setRules(rulesRes.value.rules || []);
            if (!silent) setNotice('OpenClaw actualizado.');
        } catch (err) {
            if (!silent) setNotice(err.message);
        } finally {
            setBusy(false);
        }
    }, [requestJson]);

    useEffect(() => {
        loadDashboard(true);
        const timer = setInterval(() => loadDashboard(true), 30000);
        return () => clearInterval(timer);
    }, [loadDashboard]);

    const addTarget = async (event) => {
        event.preventDefault();
        setBusy(true);
        try {
            const payload = {
                ...targetForm,
                aliases: targetForm.aliases.split(',').map(alias => alias.trim()).filter(Boolean),
                canonical_target: targetForm.canonical_target || targetForm.raw_target,
                phone: targetForm.canonical_target,
                allowed: targetForm.allowed,
            };
            const body = await requestJson('/api/openclaw/targets', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            const savedTarget = body.data?.target || body.data;
            setTargets(prev => {
                const exists = prev.some(target => target.id === savedTarget.id);
                return exists ? prev.map(target => target.id === savedTarget.id ? savedTarget : target) : [...prev, savedTarget];
            });
            setSelectedTargetId(savedTarget.id);
            setTargetForm(emptyTargetForm);
            setNotice('Target guardado.');
        } catch (err) {
            setNotice(err.message);
        } finally {
            setBusy(false);
        }
    };

    const markAllowed = async (targetId, allowed) => {
        setBusy(true);
        try {
            const body = await requestJson(`/api/openclaw/targets/${targetId}/mark-allowed`, {
                method: 'POST',
                body: JSON.stringify({ allowed }),
                allowFailure: true,
            });
            const updatedTarget = body?.data?.target || body?.data;
            setNotice(updatedTarget?.allowed ? 'Target permitido para WhatsApp.' : 'Target restringido para WhatsApp.');
            await loadDashboard(true);
        } catch (err) {
            setNotice(err.message);
        } finally {
            setBusy(false);
        }
    };

    const syncAllowlist = async () => {
        setBusy(true);
        try {
            const body = await requestJson('/api/openclaw/whatsapp/sync-allowlist', {
                method: 'POST',
                body: JSON.stringify({}),
            });
            const synced = body.data || {};
            setNotice(`Allowlist sincronizada: ${synced.direct_numbers?.length || 0} personas, ${synced.group_targets?.length || 0} grupos.`);
            await loadDashboard(true);
        } catch (err) {
            setNotice(err.message);
        } finally {
            setBusy(false);
        }
    };

    const deleteTarget = async (targetId) => {
        setBusy(true);
        try {
            await requestJson(`/api/openclaw/targets/${targetId}`, { method: 'DELETE' });
            setNotice('Target eliminado.');
            await loadDashboard(true);
        } catch (err) {
            setNotice(err.message);
        } finally {
            setBusy(false);
        }
    };

    const readConversation = async () => {
        if (!selectedTarget) return;
        setBusy(true);
        try {
            const body = await requestJson(`/api/openclaw/targets/${selectedTarget.id}/messages/new`, {
                method: 'POST',
                body: JSON.stringify({ limit: readLimit, mark_read: true }),
            });
            setConversation(body.data || []);
            setNotice('Mensajes inbound nuevos leidos desde Jarvis.');
        } catch (err) {
            setNotice(err.message);
        } finally {
            setBusy(false);
        }
    };

    const sendDryRun = async () => {
        if (!selectedTarget) return;
        setBusy(true);
        try {
            await requestJson('/api/openclaw/send-dry-run', {
                method: 'POST',
                body: JSON.stringify({ target_id: selectedTarget.id, message: testMessage }),
            });
            setNotice('Dry-run registrado.');
            await loadDashboard(true);
        } catch (err) {
            setNotice(err.message);
        } finally {
            setBusy(false);
        }
    };

    const createPendingSend = async () => {
        if (!selectedTarget) return;
        setBusy(true);
        try {
            const body = await requestJson('/api/openclaw/send-pending', {
                method: 'POST',
                body: JSON.stringify({ target_id: selectedTarget.id, message: testMessage }),
            });
            setNotice(body?.data?.pending_action_id ? `Envio pendiente creado: ${body.data.pending_action_id}` : 'Envio pendiente creado.');
            await loadDashboard(true);
        } catch (err) {
            setNotice(err.message);
        } finally {
            setBusy(false);
        }
    };

    const importContacts = async (file, type) => {
        if (!file) return;
        setBusy(true);
        try {
            const form = new FormData();
            form.append('file', file);
            const response = await fetch(`${API_BASE}/api/openclaw/contacts/import-${type}`, {
                method: 'POST',
                body: form,
            });
            const body = await response.json();
            if (!response.ok || body?.success === false) {
                throw new Error(body?.error || 'No se pudo importar contactos.');
            }
            setImportSummary(body.data);
            setNotice(`Importacion ${type.toUpperCase()}: ${body.data.created} creados, ${body.data.updated} actualizados, ${body.data.skipped} omitidos.`);
            await loadDashboard(true);
        } catch (err) {
            setNotice(err.message);
        } finally {
            setBusy(false);
        }
    };

    const confirmPending = async (id) => {
        await fetch(`${API_BASE}/api/pending-actions/${id}/confirm`, { method: 'POST' });
        await loadDashboard(true);
    };

    const cancelPending = async (id) => {
        await fetch(`${API_BASE}/api/pending-actions/${id}/cancel`, { method: 'POST' });
        await loadDashboard(true);
    };

    const statusOk = Boolean(status?.success);
    const accountText = compactText(selfAccount?.account || selfAccount?.id || selfAccount?.phone || selfAccount?.number || selfAccount);

    return (
        <div
            id="openclaw"
            onMouseDown={onMouseDown}
            style={{
                position: 'absolute',
                left: position.x,
                top: position.y,
                transform: 'translate(-50%, -50%)',
                width: '920px',
                maxHeight: '82vh',
                zIndex,
            }}
            className="pointer-events-auto backdrop-blur-xl bg-black/90 border border-cyan-400/30 rounded-lg shadow-[0_0_40px_rgba(34,211,238,0.16)] overflow-hidden flex flex-col"
        >
            <div data-drag-handle className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-white/5 cursor-grab active:cursor-grabbing">
                <div className="flex items-center gap-3 min-w-0">
                    <ShieldCheck size={18} className={statusOk ? 'text-green-300' : 'text-yellow-300'} />
                    <div className="min-w-0">
                        <div className="text-sm font-bold tracking-widest text-cyan-100 uppercase">OpenClaw Gateway</div>
                        <div className="flex items-center gap-2 mt-1 text-[10px] uppercase tracking-wider">
                            <span className={`px-2 py-0.5 rounded border ${statusOk ? 'text-green-300 border-green-400/30 bg-green-400/10' : 'text-yellow-300 border-yellow-400/30 bg-yellow-400/10'}`}>
                                {statusOk ? 'online' : 'revisar'}
                            </span>
                            <span className="text-white/40 truncate max-w-[520px]">{status?.summary || 'Sin estado cargado'}</span>
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button disabled={busy} onClick={() => loadDashboard(false)} className="p-1.5 rounded border border-cyan-400/20 text-cyan-300 hover:bg-cyan-400/10 disabled:opacity-50" title="Actualizar">
                        <RefreshCw size={14} />
                    </button>
                    <button disabled={busy} onClick={syncAllowlist} className="p-1.5 rounded border border-green-400/20 text-green-300 hover:bg-green-400/10 disabled:opacity-50" title="Sincronizar allowlist WhatsApp">
                        <ShieldCheck size={14} />
                    </button>
                    <button onClick={onClose} className="p-1.5 rounded text-white/40 hover:text-white hover:bg-white/10" title="Cerrar">
                        <X size={16} />
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-[270px_1fr_260px] gap-4 p-4 overflow-y-auto custom-scrollbar">
                <section className="space-y-4">
                    <div className="rounded-lg border border-yellow-400/25 bg-yellow-400/10 p-3 text-[11px] leading-relaxed text-yellow-100">
                        WhatsApp permite envio por numero, pero no soporta resolve/read/directory completo. Los contactos se guardan localmente y los mensajes nuevos llegan por inbound events.
                    </div>

                    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
                        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-cyan-200/80 mb-2">
                            <CheckCircle2 size={14} /> WhatsApp
                        </div>
                        <div className="text-xs text-white/70 break-words">{accountText || 'Cuenta no cargada'}</div>
                        {groups.length === 0 && (
                            <div className="mt-3 flex gap-2 text-[11px] leading-relaxed text-yellow-200/80 border border-yellow-400/20 bg-yellow-400/10 rounded p-2">
                                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                                <span>OpenClaw WhatsApp no expone listado de grupos actualmente; los grupos se registran manualmente o mediante eventos entrantes.</span>
                            </div>
                        )}
                    </div>

                    <form onSubmit={addTarget} className="rounded-lg border border-white/10 bg-white/[0.04] p-3 space-y-2">
                        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-green-200/80">
                            <UserPlus size={14} /> Nuevo target
                        </div>
                        <select value={targetForm.channel} onChange={(e) => setTargetForm(prev => ({ ...prev, channel: e.target.value }))} className="w-full bg-black/60 border border-white/10 rounded p-2 text-xs text-white">
                            <option value="whatsapp">whatsapp</option>
                        </select>
                        <select value={targetForm.kind} onChange={(e) => setTargetForm(prev => ({ ...prev, kind: e.target.value }))} className="w-full bg-black/60 border border-white/10 rounded p-2 text-xs text-white">
                            <option value="auto">auto</option>
                            <option value="user">user</option>
                            <option value="group">group</option>
                        </select>
                        <input value={targetForm.display_name} onChange={(e) => setTargetForm(prev => ({ ...prev, display_name: e.target.value }))} placeholder="Nombre visible" className="w-full bg-black/60 border border-white/10 rounded p-2 text-xs text-white outline-none focus:border-cyan-400/40" />
                        <input value={targetForm.canonical_target} onChange={(e) => setTargetForm(prev => ({ ...prev, canonical_target: e.target.value, raw_target: e.target.value }))} placeholder="Telefono/target canonico, ej. +34722129717" className="w-full bg-black/60 border border-white/10 rounded p-2 text-xs text-white outline-none focus:border-cyan-400/40" />
                        <input value={targetForm.aliases} onChange={(e) => setTargetForm(prev => ({ ...prev, aliases: e.target.value }))} placeholder="Aliases separados por coma" className="w-full bg-black/60 border border-white/10 rounded p-2 text-xs text-white outline-none focus:border-cyan-400/40" />
                        <input value={targetForm.relationship} onChange={(e) => setTargetForm(prev => ({ ...prev, relationship: e.target.value }))} placeholder="Relacion, ej. novia" className="w-full bg-black/60 border border-white/10 rounded p-2 text-xs text-white outline-none focus:border-cyan-400/40" />
                        <label className="flex items-center justify-between text-[11px] text-white/70 border border-white/10 rounded p-2">
                            Favorito
                            <input type="checkbox" checked={targetForm.favorite} onChange={(e) => setTargetForm(prev => ({ ...prev, favorite: e.target.checked }))} className="accent-cyan-300" />
                        </label>
                        <label className="flex items-center justify-between text-[11px] text-white/70 border border-white/10 rounded p-2">
                            Allowlist Jarvis
                            <input type="checkbox" checked={targetForm.allowed} onChange={(e) => setTargetForm(prev => ({ ...prev, allowed: e.target.checked }))} className="accent-green-300" />
                        </label>
                        <button disabled={busy || !targetForm.canonical_target} className="w-full flex items-center justify-center gap-2 rounded border border-green-400/30 bg-green-400/10 text-green-200 text-xs py-2 hover:bg-green-400/20 disabled:opacity-40">
                            <UserPlus size={13} /> Guardar
                        </button>
                    </form>

                    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-3 space-y-2">
                        <div className="text-xs font-bold uppercase tracking-widest text-cyan-200/80">Importar contactos</div>
                        <label className="block text-[11px] text-white/60">
                            CSV
                            <input type="file" accept=".csv,text/csv" onChange={(e) => importContacts(e.target.files?.[0], 'csv')} className="mt-1 w-full text-[10px] text-white/70 file:mr-2 file:rounded file:border-0 file:bg-cyan-900 file:px-2 file:py-1 file:text-cyan-200" />
                        </label>
                        <label className="block text-[11px] text-white/60">
                            VCF
                            <input type="file" accept=".vcf,text/vcard" onChange={(e) => importContacts(e.target.files?.[0], 'vcf')} className="mt-1 w-full text-[10px] text-white/70 file:mr-2 file:rounded file:border-0 file:bg-cyan-900 file:px-2 file:py-1 file:text-cyan-200" />
                        </label>
                        {importSummary && (
                            <div className="text-[10px] text-white/55">
                                {importSummary.created} creados | {importSummary.updated} actualizados | {importSummary.skipped} omitidos
                            </div>
                        )}
                    </div>

                    {(notice || allowlistError) && (
                        <div className={`rounded-lg border p-3 text-xs leading-relaxed ${allowlistError ? 'border-red-400/30 bg-red-400/10 text-red-200' : 'border-cyan-400/20 bg-cyan-400/10 text-cyan-100'}`}>
                            {allowlistError || notice}
                        </div>
                    )}
                </section>

                <section className="space-y-4">
                    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
                        <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-cyan-200/80">
                                <Users size={14} /> Agenda WhatsApp
                            </div>
                            <span className="text-[10px] text-white/35">{filteredTargets.length}/{targets.length} agenda local</span>
                        </div>
                        <input
                            value={targetSearch}
                            onChange={(event) => setTargetSearch(event.target.value)}
                            placeholder="Buscar contacto, alias o telefono"
                            className="mb-3 w-full bg-black/60 border border-white/10 rounded p-2 text-xs text-white outline-none focus:border-cyan-400/40"
                        />
                        <div className="space-y-2 max-h-[260px] overflow-y-auto custom-scrollbar">
                            {filteredTargets.map(target => (
                                <div key={target.id} className={`rounded border p-2 ${selectedTarget?.id === target.id ? 'border-cyan-400/40 bg-cyan-400/10' : 'border-white/10 bg-black/30'}`}>
                                    <button onClick={() => setSelectedTargetId(target.id)} className="w-full text-left">
                                        <div className="flex items-center justify-between gap-2">
                                            <span className="text-sm font-bold text-white truncate">{targetLabel(target)}</span>
                                            <span className={`text-[10px] px-1.5 py-0.5 rounded border ${target.allowed ? 'text-green-300 border-green-400/30' : 'text-yellow-300 border-yellow-400/30'}`}>
                                                {target.allowed ? 'allowed' : 'restricted'}
                                            </span>
                                        </div>
                                        <div className="text-[10px] text-white/40 truncate">{target.kind} | {target.canonical_target || target.raw_target}</div>
                                        {target.aliases?.length > 0 && <div className="text-[10px] text-cyan-200/50 truncate">alias: {target.aliases.join(', ')}</div>}
                                        <div className="text-[10px] text-white/30 truncate">{target.favorite ? 'favorito' : 'normal'} | {target.source || 'manual'}</div>
                                    </button>
                                    <div className="flex gap-2 mt-2">
                                        <button
                                            disabled={busy}
                                            onClick={() => setTargetForm({
                                                channel: target.channel || 'whatsapp',
                                                kind: target.kind || 'auto',
                                                display_name: target.display_name || '',
                                                raw_target: target.raw_target || target.canonical_target || '',
                                                canonical_target: target.canonical_target || target.raw_target || '',
                                                aliases: (target.aliases || []).join(', '),
                                                relationship: target.relationship || '',
                                                favorite: Boolean(target.favorite),
                                                allowed: Boolean(target.allowed),
                                            })}
                                            className="px-2 py-1 rounded border border-cyan-400/20 text-[10px] text-cyan-200 hover:bg-cyan-400/10"
                                            title="Editar en formulario"
                                        >
                                            Editar
                                        </button>
                                        <button disabled={busy} onClick={() => markAllowed(target.id, !target.allowed)} className={`p-1.5 rounded border ${target.allowed ? 'border-yellow-400/20 text-yellow-200 hover:bg-yellow-400/10' : 'border-green-400/20 text-green-200 hover:bg-green-400/10'}`} title={target.allowed ? 'Quitar de allowlist' : 'Marcar allowed'}>
                                            <ClipboardCheck size={12} />
                                        </button>
                                        <button disabled={busy} onClick={() => deleteTarget(target.id)} className="p-1.5 rounded border border-red-400/20 text-red-200 hover:bg-red-400/10" title="Eliminar contacto local">
                                            <Trash2 size={12} />
                                        </button>
                                    </div>
                                </div>
                            ))}
                            {targets.length === 0 && <div className="text-xs text-white/40">Sin contactos guardados.</div>}
                            {targets.length > 0 && filteredTargets.length === 0 && <div className="text-xs text-white/40">Sin resultados para esa busqueda.</div>}
                        </div>
                    </div>

                    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
                        <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-green-200/80">
                                <MessageCircle size={14} /> Inbound nuevos
                            </div>
                            <div className="flex items-center gap-2">
                                <input type="number" min="1" max="50" value={readLimit} onChange={(e) => setReadLimit(Number(e.target.value))} className="w-16 bg-black/60 border border-white/10 rounded p-1 text-xs text-white" />
                                <button disabled={busy || !selectedTarget} onClick={readConversation} className="flex items-center gap-1.5 rounded border border-green-400/25 bg-green-400/10 text-green-200 text-[11px] px-2 py-1 hover:bg-green-400/20 disabled:opacity-40">
                                    <RefreshCw size={12} /> Leer nuevos
                                </button>
                            </div>
                        </div>
                        <div className="rounded border border-white/10 bg-black/30 p-2 min-h-[160px] max-h-[260px] overflow-y-auto custom-scrollbar">
                            {conversation.length === 0 ? (
                                <div className="text-xs text-white/35">Sin mensajes inbound nuevos guardados.</div>
                            ) : conversation.map((message, index) => (
                                <div key={message.id || message.message_id || index} className="border-b border-white/5 last:border-0 py-2">
                                    <div className="text-[10px] text-cyan-300/60">{message.sender_name || message.sender || message.from || 'mensaje'}</div>
                                    <div className="text-xs text-white/75 break-words">{message.text || message.body || message.message || compactText(message)}</div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
                        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-cyan-200/80 mb-3">
                            <Send size={14} /> Prueba envio
                        </div>
                        <textarea value={testMessage} onChange={(e) => setTestMessage(e.target.value)} className="w-full min-h-[70px] bg-black/60 border border-white/10 rounded p-2 text-xs text-white outline-none focus:border-cyan-400/40" />
                        <div className="grid grid-cols-2 gap-2 mt-2">
                            <button disabled={busy || !selectedTarget || !testMessage} onClick={sendDryRun} className="rounded border border-cyan-400/25 bg-cyan-400/10 text-cyan-200 text-[11px] px-2 py-2 hover:bg-cyan-400/20 disabled:opacity-40">Dry-run</button>
                            <button disabled={busy || !selectedTarget || !testMessage} onClick={createPendingSend} className="rounded border border-yellow-400/25 bg-yellow-400/10 text-yellow-100 text-[11px] px-2 py-2 hover:bg-yellow-400/20 disabled:opacity-40">Crear pendiente</button>
                        </div>
                    </div>
                </section>

                <section className="space-y-4">
                    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
                        <div className="text-xs font-bold uppercase tracking-widest text-yellow-200/80 mb-2">Pending OpenClaw</div>
                        <div className="space-y-2 max-h-[150px] overflow-y-auto custom-scrollbar">
                            {pendingActions.map(action => (
                                <div key={action.id} className="rounded border border-white/10 bg-black/30 p-2">
                                    <div className="text-[11px] text-white/80 break-words">{action.human_summary}</div>
                                    <div className="flex gap-2 mt-2">
                                        <button onClick={() => confirmPending(action.id)} className="text-[10px] px-2 py-1 rounded border border-green-400/30 text-green-200 bg-green-400/10">Confirmar</button>
                                        <button onClick={() => cancelPending(action.id)} className="text-[10px] px-2 py-1 rounded border border-red-400/30 text-red-200 bg-red-400/10">Cancelar</button>
                                    </div>
                                </div>
                            ))}
                            {pendingActions.length === 0 && <div className="text-xs text-white/35">Sin acciones pendientes.</div>}
                        </div>
                    </div>

                    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
                        <div className="text-xs font-bold uppercase tracking-widest text-cyan-200/80 mb-2">Autopilot</div>
                        <div className="space-y-2 max-h-[150px] overflow-y-auto custom-scrollbar">
                            {rules.map(rule => (
                                <div key={rule.id} className="rounded border border-white/10 bg-black/30 p-2">
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="text-[11px] text-white/80 truncate">{rule.display_target || rule.target}</span>
                                        <span className={rule.enabled ? 'text-[10px] text-green-300' : 'text-[10px] text-white/35'}>{rule.mode}</span>
                                    </div>
                                    <div className="text-[10px] text-white/35 truncate">{rule.kind || 'auto'} | {rule.target}</div>
                                </div>
                            ))}
                            {rules.length === 0 && <div className="text-xs text-white/35">Sin reglas activas.</div>}
                        </div>
                    </div>

                    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
                        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-green-200/80 mb-2">
                            <FileText size={14} /> Eventos
                        </div>
                        <div className="space-y-2 max-h-[230px] overflow-y-auto custom-scrollbar">
                            {events.map(event => (
                                <div key={event.id} className="border-b border-white/5 pb-2 last:border-0">
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="text-[10px] text-cyan-300/70 uppercase">{event.type}</span>
                                        <span className={event.success ? 'text-[10px] text-green-300' : 'text-[10px] text-red-300'}>{event.success ? 'ok' : 'error'}</span>
                                    </div>
                                    <div className="text-[11px] text-white/70 break-words">{event.display_target || event.target}</div>
                                    <div className="text-[10px] text-white/40 break-words">{event.message || event.error}</div>
                                </div>
                            ))}
                            {events.length === 0 && <div className="text-xs text-white/35">Sin eventos.</div>}
                        </div>
                    </div>
                </section>
            </div>
        </div>
    );
};

export default OpenClawDashboard;
