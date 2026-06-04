import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ExternalLink, Music, Pause, Play, Shuffle, SkipBack, SkipForward, Square, Volume1, Volume2, X } from 'lucide-react';

const clamp = (v) => Math.max(0, Math.min(100, Math.round(v)));
const DUCK_FACTOR = 0.15;

// Single, always-mounted YouTube player. The audio lives here (not in the Social
// tab) so music keeps playing across modules and can be controlled from voice/UI
// anywhere. While the user talks to JARVIS (duckActive) the volume drops.
const GlobalMusicPlayer = ({ musicStatus, musicCommand, duckActive, onMusicCommand, onRandomMusic }) => {
    const iframeRef = useRef(null);
    const playerRef = useRef(null);
    const lastCommandTs = useRef(0);
    const [controlMode, setControlMode] = useState('basic'); // 'basic' | 'full'
    const [apiReady, setApiReady] = useState(Boolean(window.YT && window.YT.Player));
    const [minimized, setMinimized] = useState(false);
    const [hidden, setHidden] = useState(false);

    const current = musicStatus?.current || musicStatus || {};
    const videoId = current.video_id || musicStatus?.video_id || null;
    const embedUrl = current.embed_url || musicStatus?.embed_url || null;
    const fallback = Boolean(current.fallback ?? musicStatus?.fallback);
    const searchUrl = current.url || musicStatus?.url || null;
    const title = current.title || current.query || null;
    const targetVolume = typeof musicStatus?.volume === 'number' ? musicStatus.volume : 50;

    const embedSrc = useMemo(() => {
        if (!videoId && !embedUrl) return '';
        const base = embedUrl || `https://www.youtube.com/embed/${videoId}`;
        const sep = base.includes('?') ? '&' : '?';
        return `${base}${sep}autoplay=1&enablejsapi=1`;
    }, [videoId, embedUrl]);

    // A new track makes the widget reappear.
    useEffect(() => { if (embedSrc) setHidden(false); }, [embedSrc]);

    // Progressive enhancement: load the YouTube IFrame Player API once.
    useEffect(() => {
        let cancelled = false;
        if (window.YT && window.YT.Player) { setApiReady(true); return undefined; }
        if (!document.getElementById('youtube-iframe-api')) {
            const tag = document.createElement('script');
            tag.id = 'youtube-iframe-api';
            tag.src = 'https://www.youtube.com/iframe_api';
            tag.onerror = () => { if (!cancelled) setControlMode('basic'); };
            document.body.appendChild(tag);
        }
        const prev = window.onYouTubeIframeAPIReady;
        window.onYouTubeIframeAPIReady = () => {
            if (typeof prev === 'function') prev();
            if (!cancelled) setApiReady(true);
        };
        const timeout = setTimeout(() => {
            if (!cancelled && !(window.YT && window.YT.Player)) setControlMode('basic');
        }, 4000);
        return () => { cancelled = true; clearTimeout(timeout); };
    }, []);

    // Wrap the live iframe with a YT.Player when the API is available.
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
                        try { event.target.setVolume(duckActive ? clamp(targetVolume * DUCK_FACTOR) : targetVolume); } catch { /* noop */ }
                    },
                },
            });
        } catch {
            setControlMode('basic');
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [embedSrc, videoId, apiReady]);

    // Volume + ducking: single source of truth driven by target volume and duck state.
    useEffect(() => {
        const player = playerRef.current;
        if (controlMode !== 'full' || !player || !player.setVolume) return;
        try { player.setVolume(duckActive ? clamp(targetVolume * DUCK_FACTOR) : targetVolume); } catch { /* noop */ }
    }, [duckActive, targetVolume, controlMode]);

    // Apply transport commands coming from voice/UI (music_command socket event).
    useEffect(() => {
        if (!musicCommand || musicCommand._ts === lastCommandTs.current) return;
        lastCommandTs.current = musicCommand._ts;
        applyCommand(musicCommand.command);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [musicCommand]);

    const applyCommand = (command) => {
        const player = playerRef.current;
        const full = controlMode === 'full' && player;
        if (command === 'next' || command === 'previous') { onRandomMusic?.(); return; }
        if (!full) {
            if (command === 'stop' && iframeRef.current) iframeRef.current.src = '';
            return; // pause/resume/volume need the IFrame API
        }
        try {
            if (command === 'pause') player.pauseVideo();
            else if (command === 'resume') player.playVideo();
            else if (command === 'stop') player.stopVideo();
            // volume_up/down/set_volume are handled by the volume effect via musicStatus.volume
        } catch { /* noop */ }
    };

    // UI buttons go through the backend (which echoes music_command back here).
    const sendCommand = (command) => onMusicCommand?.(command);

    const controlsDisabled = controlMode !== 'full';
    const hasMedia = Boolean(embedSrc) || (fallback && searchUrl);

    if (!hasMedia || hidden) return null;

    if (minimized) {
        return (
            <button type="button" className="jarvis-mini-music collapsed" onClick={() => setMinimized(false)} title="Mostrar reproductor">
                <Music size={16} />
                <span>{title || 'Música'}</span>
            </button>
        );
    }

    return (
        <div className="jarvis-mini-music">
            <div className="jarvis-mini-music-head">
                <span className="jarvis-mini-music-title"><Music size={13} /> {title || 'Música'}</span>
                <div className="jarvis-mini-music-head-actions">
                    <button type="button" onClick={() => setMinimized(true)} title="Minimizar"><ChevronDown size={14} /></button>
                    <button type="button" onClick={() => { applyCommand('stop'); setHidden(true); }} title="Cerrar"><X size={14} /></button>
                </div>
            </div>

            {embedSrc ? (
                <div className="jarvis-mini-music-video">
                    <iframe
                        ref={iframeRef}
                        title="JARVIS Music"
                        src={embedSrc}
                        allow="autoplay; encrypted-media"
                        allowFullScreen
                    />
                </div>
            ) : (
                <div className="jarvis-mini-music-fallback">
                    <span>Sin API key: no hay reproducción automática.</span>
                    {searchUrl && (
                        <button type="button" onClick={() => window.open(searchUrl, '_blank')}>
                            <ExternalLink size={12} /> Abrir en YouTube
                        </button>
                    )}
                </div>
            )}

            <div className="jarvis-mini-music-controls">
                <button type="button" disabled={controlsDisabled} title={controlsDisabled ? 'Requiere YouTube IFrame API' : 'Pausa'} onClick={() => sendCommand('pause')}><Pause size={14} /></button>
                <button type="button" disabled={controlsDisabled} title={controlsDisabled ? 'Requiere YouTube IFrame API' : 'Continuar'} onClick={() => sendCommand('resume')}><Play size={14} /></button>
                <button type="button" title="Stop" onClick={() => sendCommand('stop')}><Square size={14} /></button>
                <button type="button" title="Anterior" onClick={() => sendCommand('previous')}><SkipBack size={14} /></button>
                <button type="button" title="Siguiente" onClick={() => sendCommand('next')}><SkipForward size={14} /></button>
                <button type="button" disabled={controlsDisabled} title={controlsDisabled ? 'Requiere YouTube IFrame API' : 'Bajar volumen'} onClick={() => sendCommand('volume_down')}><Volume1 size={14} /></button>
                <button type="button" disabled={controlsDisabled} title={controlsDisabled ? 'Requiere YouTube IFrame API' : 'Subir volumen'} onClick={() => sendCommand('volume_up')}><Volume2 size={14} /></button>
                <button type="button" title="Aleatorio de mis gustos" onClick={() => onRandomMusic?.()}><Shuffle size={14} /></button>
            </div>

            <div className="jarvis-mini-music-foot">
                <span>{controlMode === 'full' ? `Vol ${duckActive ? clamp(targetVolume * DUCK_FACTOR) : targetVolume}` : 'control básico'}</span>
                {duckActive && controlMode === 'full' && <span className="is-ducking">· bajada por voz</span>}
                {fallback && <span className="is-fallback">· fallback</span>}
            </div>
        </div>
    );
};

export default GlobalMusicPlayer;
