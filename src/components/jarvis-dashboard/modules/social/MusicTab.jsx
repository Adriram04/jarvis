import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ExternalLink, Music, Pause, Play, RefreshCw, Save, Shuffle, SkipBack, SkipForward, Square, Volume1, Volume2 } from 'lucide-react';

const MODES = [
    { id: 'artist', label: 'Artista' },
    { id: 'song', label: 'Canción' },
    { id: 'genre', label: 'Género' },
    { id: 'mood', label: 'Mood' },
    { id: 'random', label: 'Aleatorio' },
    { id: 'search', label: 'Búsqueda' },
];

const inputStyle = {
    fontSize: '0.85em', padding: '5px 8px', borderRadius: 4,
    background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'inherit',
};

const clamp = (v) => Math.max(0, Math.min(100, Math.round(v)));

const MusicTab = ({ context, actions }) => {
    const { musicStatus, musicPreferences, musicHistory = [], musicCommand, musicError, musicLoading } = context;

    const [query, setQuery] = useState('');
    const [mode, setMode] = useState('artist');
    const [notice, setNotice] = useState('');

    // Preferences form
    const [artists, setArtists] = useState('');
    const [genres, setGenres] = useState('');
    const [moodProgramar, setMoodProgramar] = useState('');
    const [moodEntrenar, setMoodEntrenar] = useState('');
    const [moodRelajarse, setMoodRelajarse] = useState('');
    const [defaultVolume, setDefaultVolume] = useState(50);

    const playerRef = useRef(null);
    const iframeRef = useRef(null);
    const [controlMode, setControlMode] = useState('basic'); // 'basic' | 'full'
    const lastCommandTs = useRef(0);

    const current = musicStatus?.current || musicStatus || {};
    const videoId = current.video_id || musicStatus?.video_id || null;
    const embedUrl = current.embed_url || musicStatus?.embed_url || null;
    const fallback = Boolean(current.fallback ?? musicStatus?.fallback);
    const searchUrl = current.url || musicStatus?.url || null;
    const volume = typeof musicStatus?.volume === 'number' ? musicStatus.volume : 50;

    const embedSrc = useMemo(() => {
        if (!videoId && !embedUrl) return '';
        const base = embedUrl || `https://www.youtube.com/embed/${videoId}`;
        const sep = base.includes('?') ? '&' : '?';
        return `${base}${sep}autoplay=1&enablejsapi=1`;
    }, [videoId, embedUrl]);

    // Load preferences into the form when they arrive.
    useEffect(() => {
        if (!musicPreferences) return;
        setArtists((musicPreferences.favorite_artists || []).join(', '));
        setGenres((musicPreferences.favorite_genres || []).join(', '));
        const moods = musicPreferences.moods || {};
        setMoodProgramar((moods.programar || []).join(', '));
        setMoodEntrenar((moods.entrenar || []).join(', '));
        setMoodRelajarse((moods.relajarse || []).join(', '));
        if (typeof musicPreferences.default_volume === 'number') setDefaultVolume(musicPreferences.default_volume);
    }, [musicPreferences]);

    // Progressive enhancement: try to load the YouTube IFrame Player API.
    useEffect(() => {
        let cancelled = false;
        if (window.YT && window.YT.Player) return undefined;
        if (!document.getElementById('youtube-iframe-api')) {
            const tag = document.createElement('script');
            tag.id = 'youtube-iframe-api';
            tag.src = 'https://www.youtube.com/iframe_api';
            tag.onerror = () => { if (!cancelled) setControlMode('basic'); };
            document.body.appendChild(tag);
        }
        const prev = window.onYouTubeIframeAPIReady;
        window.onYouTubeIframeAPIReady = () => { if (typeof prev === 'function') prev(); };
        const timeout = setTimeout(() => {
            if (!cancelled && !(window.YT && window.YT.Player)) setControlMode('basic');
        }, 4000);
        return () => { cancelled = true; clearTimeout(timeout); };
    }, []);

    // Wrap the existing iframe with a YT.Player when the API is available.
    useEffect(() => {
        if (!embedSrc || !iframeRef.current) return;
        if (!(window.YT && window.YT.Player)) return;
        if (playerRef.current) {
            if (videoId && playerRef.current.loadVideoById) {
                try { playerRef.current.loadVideoById(videoId); } catch { /* noop */ }
            }
            return;
        }
        try {
            playerRef.current = new window.YT.Player(iframeRef.current, {
                events: {
                    onReady: (event) => {
                        setControlMode('full');
                        try { event.target.setVolume(volume); } catch { /* noop */ }
                    },
                },
            });
        } catch {
            setControlMode('basic');
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [embedSrc, videoId]);

    // React to commands coming from voice/UI (music_command socket event).
    useEffect(() => {
        if (!musicCommand || musicCommand._ts === lastCommandTs.current) return;
        lastCommandTs.current = musicCommand._ts;
        applyCommand(musicCommand.command, musicCommand.volume);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [musicCommand]);

    const play = async () => {
        setNotice('');
        const res = await actions.onPlayMusic?.(query.trim(), mode);
        if (!res?.success) setNotice(res?.error || 'No se pudo reproducir.');
    };

    const playRandom = async () => {
        setNotice('');
        const res = await actions.onRandomMusic?.();
        if (!res?.success) setNotice(res?.error || 'No se pudo reproducir.');
    };

    // Applies a command to the embedded player (full mode) or degrades gracefully.
    const applyCommand = (command, vol) => {
        const player = playerRef.current;
        const full = controlMode === 'full' && player;
        if (command === 'next') { actions.onRandomMusic?.(); return; }
        if (command === 'previous') { actions.onRandomMusic?.(); return; }
        if (!full) {
            if (command === 'stop' && iframeRef.current) iframeRef.current.src = '';
            return; // pause/resume/volume need the IFrame API
        }
        try {
            if (command === 'pause') player.pauseVideo();
            else if (command === 'resume') player.playVideo();
            else if (command === 'stop') player.stopVideo();
            else if (command === 'volume_up') player.setVolume(clamp((player.getVolume?.() ?? volume) + 10));
            else if (command === 'volume_down') player.setVolume(clamp((player.getVolume?.() ?? volume) - 10));
            else if (command === 'set_volume' && typeof vol === 'number') player.setVolume(clamp(vol));
        } catch { /* noop */ }
    };

    // UI buttons send the command to the backend (which emits music_command back).
    const sendCommand = (command, payload = {}) => actions.onMusicCommand?.(command, payload);

    const savePreferences = async () => {
        setNotice('');
        const payload = {
            favorite_artists: artists,
            favorite_genres: genres,
            moods: {
                programar: moodProgramar,
                entrenar: moodEntrenar,
                relajarse: moodRelajarse,
            },
            default_volume: Number(defaultVolume) || 0,
        };
        const res = await actions.onUpdateMusicPreferences?.(payload);
        setNotice(res?.success ? 'Preferencias guardadas.' : (res?.error || 'No se pudieron guardar.'));
    };

    const controlsDisabled = controlMode !== 'full';
    const enabled = musicStatus?.enabled !== false;
    const hasApiKey = Boolean(musicStatus?.has_api_key);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {!enabled && (
                <div className="jarvis-soft-error">El módulo de música está deshabilitado (JARVIS_MUSIC_ENABLED=false).</div>
            )}
            {(notice || musicError) && (
                <div className={(notice && notice.includes('guardad')) ? 'jarvis-soft-success' : 'jarvis-soft-error'}>
                    {notice || musicError}
                </div>
            )}

            {/* Search + play */}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                <input
                    placeholder="Artista, canción, género o mood..."
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') play(); }}
                    style={{ ...inputStyle, flex: 1, minWidth: 180 }}
                />
                <select value={mode} onChange={(e) => setMode(e.target.value)} style={inputStyle}>
                    {MODES.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
                </select>
                <button type="button" className="jarvis-module-button" disabled={musicLoading} onClick={play}>
                    <Play size={13} /> Reproducir
                </button>
                <button type="button" className="jarvis-module-button" disabled={musicLoading} onClick={playRandom}>
                    <Shuffle size={13} /> Aleatorio de mis gustos
                </button>
            </div>

            {/* Player / fallback */}
            <div>
                {embedSrc ? (
                    <div style={{ position: 'relative', paddingTop: '56.25%', borderRadius: 8, overflow: 'hidden', background: '#000' }}>
                        <iframe
                            ref={iframeRef}
                            title="JARVIS Music"
                            src={embedSrc}
                            style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', border: 0 }}
                            allow="autoplay; encrypted-media"
                            allowFullScreen
                        />
                    </div>
                ) : (
                    <div className="jarvis-empty-state" style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-start' }}>
                        <span><Music size={14} /> {fallback ? 'Sin API key: no hay reproducción automática dentro de JARVIS.' : 'Nada reproduciéndose todavía.'}</span>
                        {searchUrl && (
                            <button type="button" className="jarvis-module-button" onClick={() => window.open(searchUrl, '_blank')}>
                                <ExternalLink size={13} /> Abrir búsqueda en YouTube
                            </button>
                        )}
                        {fallback && !hasApiKey && (
                            <small style={{ opacity: 0.6 }}>Configura JARVIS_YOUTUBE_API_KEY para reproducir automáticamente.</small>
                        )}
                    </div>
                )}
            </div>

            {/* Controls */}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                <button type="button" className="jarvis-module-button" disabled={controlsDisabled} title={controlsDisabled ? 'Requiere YouTube IFrame API' : 'Pausa'} onClick={() => sendCommand('pause')}>
                    <Pause size={13} /> Pausa
                </button>
                <button type="button" className="jarvis-module-button" disabled={controlsDisabled} title={controlsDisabled ? 'Requiere YouTube IFrame API' : 'Continuar'} onClick={() => sendCommand('resume')}>
                    <Play size={13} /> Continuar
                </button>
                <button type="button" className="jarvis-module-button" onClick={() => sendCommand('stop')}>
                    <Square size={13} /> Stop
                </button>
                <button type="button" className="jarvis-module-button" onClick={() => sendCommand('previous')}>
                    <SkipBack size={13} /> Anterior
                </button>
                <button type="button" className="jarvis-module-button" onClick={() => sendCommand('next')}>
                    <SkipForward size={13} /> Siguiente
                </button>
                <button type="button" className="jarvis-module-button" disabled={controlsDisabled} title={controlsDisabled ? 'Requiere YouTube IFrame API' : 'Bajar volumen'} onClick={() => sendCommand('volume_down')}>
                    <Volume1 size={13} /> Vol −
                </button>
                <button type="button" className="jarvis-module-button" disabled={controlsDisabled} title={controlsDisabled ? 'Requiere YouTube IFrame API' : 'Subir volumen'} onClick={() => sendCommand('volume_up')}>
                    <Volume2 size={13} /> Vol +
                </button>
            </div>

            {/* Current status */}
            <div style={{ fontSize: '0.8em', opacity: 0.75, display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                <span>Proveedor: YouTube</span>
                <span>Modo control: {controlMode === 'full' ? 'completo' : 'básico'}</span>
                <span>Volumen: {volume}</span>
                {current.query && <span>Query: {current.query}</span>}
                {current.title && <span>Título: {current.title}</span>}
                {fallback && <span style={{ color: '#fbbf24' }}>fallback (sin API key)</span>}
                <button type="button" onClick={actions.onRefreshMusicStatus} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', opacity: 0.6 }}>
                    <RefreshCw size={12} />
                </button>
            </div>

            {/* Preferences */}
            <details>
                <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Preferencias musicales</summary>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                    <label style={{ display: 'grid', gap: 3, fontSize: '0.8em' }}>
                        Artistas favoritos (separados por comas)
                        <input value={artists} onChange={(e) => setArtists(e.target.value)} style={inputStyle} placeholder="Estopa, Queen, ..." />
                    </label>
                    <label style={{ display: 'grid', gap: 3, fontSize: '0.8em' }}>
                        Géneros favoritos (separados por comas)
                        <input value={genres} onChange={(e) => setGenres(e.target.value)} style={inputStyle} placeholder="rock, lofi, ..." />
                    </label>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <label style={{ display: 'grid', gap: 3, fontSize: '0.8em', flex: 1, minWidth: 140 }}>
                            Mood: programar
                            <input value={moodProgramar} onChange={(e) => setMoodProgramar(e.target.value)} style={inputStyle} placeholder="lofi, concentración" />
                        </label>
                        <label style={{ display: 'grid', gap: 3, fontSize: '0.8em', flex: 1, minWidth: 140 }}>
                            Mood: entrenar
                            <input value={moodEntrenar} onChange={(e) => setMoodEntrenar(e.target.value)} style={inputStyle} placeholder="workout, gym" />
                        </label>
                        <label style={{ display: 'grid', gap: 3, fontSize: '0.8em', flex: 1, minWidth: 140 }}>
                            Mood: relajarse
                            <input value={moodRelajarse} onChange={(e) => setMoodRelajarse(e.target.value)} style={inputStyle} placeholder="chill, ambient" />
                        </label>
                    </div>
                    <label style={{ display: 'grid', gap: 3, fontSize: '0.8em', maxWidth: 160 }}>
                        Volumen por defecto
                        <input type="number" min="0" max="100" value={defaultVolume} onChange={(e) => setDefaultVolume(e.target.value)} style={inputStyle} />
                    </label>
                    <button type="button" className="jarvis-module-button" onClick={savePreferences} style={{ alignSelf: 'flex-start' }}>
                        <Save size={13} /> Guardar preferencias
                    </button>
                </div>
            </details>

            {/* History */}
            <details>
                <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Historial ({musicHistory.length})</summary>
                <div className="jarvis-social-scroll" style={{ maxHeight: 220, overflowY: 'auto', marginTop: 8 }}>
                    {musicHistory.length === 0 && <div className="jarvis-empty-state">Sin reproducciones todavía.</div>}
                    {musicHistory.map((item, index) => (
                        <article key={`${item.played_at}-${index}`} className="jarvis-activity-item">
                            <Music size={13} style={{ color: 'var(--jarvis-accent, #22d3ee)', flexShrink: 0 }} />
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <strong style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {item.title || item.query}
                                </strong>
                                <span style={{ fontSize: '0.78em', opacity: 0.6 }}>
                                    {item.query} · {item.provider || 'youtube'}{item.fallback ? ' · fallback' : ''}
                                </span>
                            </div>
                            <span style={{ fontSize: '0.7em', opacity: 0.5, flexShrink: 0 }}>
                                {item.played_at ? new Date(item.played_at).toLocaleString('es-ES') : ''}
                            </span>
                        </article>
                    ))}
                </div>
            </details>
        </div>
    );
};

export default MusicTab;
