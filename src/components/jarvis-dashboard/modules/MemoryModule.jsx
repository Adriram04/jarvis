import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
    BrainCircuit,
    FileText,
    MessageSquare,
    RefreshCw,
    Search,
    StickyNote,
    Trash2,
    UploadCloud,
} from 'lucide-react';
import {
    clearMemory,
    getMemoryStats,
    ingestMemoryFile,
    rememberMemory,
    searchMemory,
} from '../../../services/jarvisDashboardApi';

const sourceIcon = (source) => {
    const value = String(source || '').toLowerCase();
    if (value.startsWith('chat:')) return <MessageSquare size={14} />;
    if (value === 'nota') return <StickyNote size={14} />;
    return <FileText size={14} />;
};

const relevanceLabel = (score) => {
    if (score >= 0.75) return 'Alta';
    if (score >= 0.55) return 'Media';
    return 'Baja';
};

const MemoryModule = () => {
    const [stats, setStats] = useState(null);
    const [statsError, setStatsError] = useState('');

    const [query, setQuery] = useState('');
    const [results, setResults] = useState(null);
    const [searching, setSearching] = useState(false);

    const [note, setNote] = useState('');
    const [savingNote, setSavingNote] = useState(false);

    const [uploading, setUploading] = useState(false);
    const [dragActive, setDragActive] = useState(false);
    const [feedback, setFeedback] = useState(null);
    const fileInputRef = useRef(null);

    const refreshStats = useCallback(async () => {
        const response = await getMemoryStats();
        if (response.ok && response.data?.stats) {
            setStats(response.data.stats);
            setStatsError('');
        } else {
            setStatsError(response.error || 'No se pudo leer el estado de la memoria.');
        }
    }, []);

    useEffect(() => {
        refreshStats();
    }, [refreshStats]);

    const flash = (type, text) => {
        setFeedback({ type, text });
        window.setTimeout(() => setFeedback(null), 4000);
    };

    const runSearch = async (event) => {
        event?.preventDefault?.();
        const q = query.trim();
        if (!q || searching) return;
        setSearching(true);
        const response = await searchMemory(q, 6);
        setSearching(false);
        if (response.ok) {
            setResults(response.data?.results || []);
        } else {
            setResults([]);
            flash('error', response.error || 'La búsqueda falló.');
        }
    };

    const saveNote = async (event) => {
        event?.preventDefault?.();
        const text = note.trim();
        if (!text || savingNote) return;
        setSavingNote(true);
        const response = await rememberMemory(text);
        setSavingNote(false);
        if (response.ok && response.data?.success) {
            const added = response.data?.result?.added || 0;
            flash('success', added ? 'Guardado en la memoria de Jarvis.' : 'Eso ya estaba en la memoria.');
            setNote('');
            refreshStats();
        } else {
            flash('error', response.data?.result?.error || response.error || 'No se pudo guardar la nota.');
        }
    };

    const ingestFiles = async (files) => {
        const list = Array.from(files || []);
        if (!list.length || uploading) return;
        setUploading(true);
        let added = 0;
        let failed = 0;
        for (const file of list) {
            const response = await ingestMemoryFile(file);
            if (response.ok && response.data?.success) {
                added += response.data?.result?.added || 0;
            } else {
                failed += 1;
            }
        }
        setUploading(false);
        if (failed && !added) {
            flash('error', `No se pudo indexar ${failed} documento(s).`);
        } else {
            flash('success', `Indexados ${added} fragmento(s) en la memoria${failed ? `, ${failed} fallaron` : ''}.`);
        }
        refreshStats();
    };

    const onDrop = (event) => {
        event.preventDefault();
        setDragActive(false);
        ingestFiles(event.dataTransfer?.files);
    };

    const wipeMemory = async () => {
        if (uploading) return;
        if (!window.confirm('¿Borrar TODA la memoria semántica de Jarvis? Esta acción no se puede deshacer.')) return;
        const response = await clearMemory();
        if (response.ok) {
            flash('success', 'Memoria borrada.');
            setResults(null);
            refreshStats();
        } else {
            flash('error', response.error || 'No se pudo borrar la memoria.');
        }
    };

    const sources = stats?.sources ? Object.entries(stats.sources) : [];
    const unavailable = stats && stats.available === false;

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Memoria semántica (RAG)</span>
                    <h2>Memoria de Jarvis</h2>
                </div>
                <button type="button" className="jarvis-module-button" onClick={refreshStats}>
                    <RefreshCw size={14} /> Actualizar
                </button>
            </div>

            {statsError && <div className="jarvis-soft-error">{statsError}</div>}
            {unavailable && (
                <div className="jarvis-soft-error">
                    La memoria semántica no está configurada. Define GEMINI_API_KEY para activarla.
                </div>
            )}
            {feedback && (
                <div className={feedback.type === 'error' ? 'jarvis-soft-error' : 'jarvis-soft-success'}>
                    {feedback.text}
                </div>
            )}

            <div className="jarvis-memory-stats">
                <div className="jarvis-memory-stat">
                    <BrainCircuit size={18} />
                    <div>
                        <strong>{stats?.chunks ?? '—'}</strong>
                        <span>Fragmentos en memoria</span>
                    </div>
                </div>
                <div className="jarvis-memory-stat">
                    <FileText size={18} />
                    <div>
                        <strong>{sources.length}</strong>
                        <span>Fuentes distintas</span>
                    </div>
                </div>
                <div className="jarvis-memory-stat">
                    <span className="jarvis-memory-model">{stats?.embedding_model || '—'}</span>
                    <div>
                        <strong>{stats?.embedding_dim ? `${stats.embedding_dim} dim` : '—'}</strong>
                        <span>Modelo de embeddings</span>
                    </div>
                </div>
                {stats?.chunks > 0 && (
                    <button type="button" className="jarvis-memory-wipe" onClick={wipeMemory} title="Borrar toda la memoria">
                        <Trash2 size={14} /> Vaciar
                    </button>
                )}
            </div>

            <div className="jarvis-memory-layout">
                <section className="jarvis-panel jarvis-memory-search-panel">
                    <div className="jarvis-panel-title">Buscar en la memoria</div>
                    <form className="jarvis-memory-search" onSubmit={runSearch}>
                        <Search size={16} />
                        <input
                            type="text"
                            value={query}
                            placeholder="¿Qué recuerda Jarvis sobre...?"
                            onChange={(e) => setQuery(e.target.value)}
                        />
                        <button type="submit" disabled={searching || !query.trim()}>
                            {searching ? 'Buscando…' : 'Buscar'}
                        </button>
                    </form>

                    {results === null && (
                        <div className="jarvis-empty-state compact">
                            Escribe una pregunta para recuperar lo que Jarvis sabe por significado, no por palabras exactas.
                        </div>
                    )}
                    {results !== null && results.length === 0 && (
                        <div className="jarvis-empty-state compact">Sin coincidencias relevantes.</div>
                    )}
                    {results !== null && results.length > 0 && (
                        <div className="jarvis-memory-results">
                            {results.map((hit, index) => (
                                <article key={index} className="jarvis-memory-result">
                                    <header>
                                        <span className="jarvis-memory-source">
                                            {sourceIcon(hit.source)} {hit.source || 'memoria'}
                                        </span>
                                        <span className="jarvis-memory-score" title={`Similitud ${hit.score}`}>
                                            {relevanceLabel(hit.score)} · {Math.round((hit.score || 0) * 100)}%
                                        </span>
                                    </header>
                                    <p>{hit.text}</p>
                                </article>
                            ))}
                        </div>
                    )}
                </section>

                <section className="jarvis-panel jarvis-memory-ingest-panel">
                    <div className="jarvis-panel-title">Añadir conocimiento</div>

                    <div
                        className={`jarvis-memory-dropzone ${dragActive ? 'is-active' : ''}`}
                        onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                        onDragLeave={() => setDragActive(false)}
                        onDrop={onDrop}
                        onClick={() => fileInputRef.current?.click()}
                        role="button"
                        tabIndex={0}
                    >
                        <UploadCloud size={26} />
                        <strong>{uploading ? 'Indexando…' : 'Arrastra documentos aquí'}</strong>
                        <span>o haz clic para elegir (txt, md, código, json, PDF)</span>
                        <input
                            ref={fileInputRef}
                            type="file"
                            multiple
                            accept=".txt,.md,.markdown,.rst,.py,.js,.jsx,.ts,.tsx,.json,.jsonl,.html,.css,.csv,.log,.yaml,.yml,.pdf"
                            style={{ display: 'none' }}
                            onChange={(e) => { ingestFiles(e.target.files); e.target.value = ''; }}
                        />
                    </div>

                    <form className="jarvis-memory-note" onSubmit={saveNote}>
                        <textarea
                            value={note}
                            placeholder="Escribe una nota para que Jarvis la recuerde…"
                            rows={3}
                            onChange={(e) => setNote(e.target.value)}
                        />
                        <button type="submit" className="jarvis-panel-action" disabled={savingNote || !note.trim()}>
                            <StickyNote size={14} /> {savingNote ? 'Guardando…' : 'Recordar nota'}
                        </button>
                    </form>

                    {sources.length > 0 && (
                        <div className="jarvis-memory-sources">
                            <div className="jarvis-panel-title compact">Fuentes indexadas</div>
                            {sources
                                .sort((a, b) => b[1] - a[1])
                                .slice(0, 8)
                                .map(([name, count]) => (
                                    <div key={name} className="jarvis-memory-source-row">
                                        {sourceIcon(name)}
                                        <span>{name}</span>
                                        <small>{count}</small>
                                    </div>
                                ))}
                        </div>
                    )}
                </section>
            </div>
        </section>
    );
};

export default MemoryModule;
