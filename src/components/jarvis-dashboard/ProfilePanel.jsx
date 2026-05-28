import React, { useEffect, useState } from 'react';
import { Grid3X3, Palette, Sparkles, Waves } from 'lucide-react';

const themes = {
    cyan: {
        label: 'Azul neón',
        colors: {
            '--jarvis-cyan': '#00E5FF',
            '--jarvis-blue': '#00A3FF',
            '--jarvis-purple': '#7B61FF',
        },
    },
    violet: {
        label: 'Morado',
        colors: {
            '--jarvis-cyan': '#A78BFA',
            '--jarvis-blue': '#7B61FF',
            '--jarvis-purple': '#C084FC',
        },
    },
    green: {
        label: 'Verde',
        colors: {
            '--jarvis-cyan': '#00FF93',
            '--jarvis-blue': '#00D4A6',
            '--jarvis-purple': '#00A3FF',
        },
    },
    amber: {
        label: 'Ámbar',
        colors: {
            '--jarvis-cyan': '#FBBF24',
            '--jarvis-blue': '#F59E0B',
            '--jarvis-purple': '#22D3EE',
        },
    },
    rose: {
        label: 'Rojo',
        colors: {
            '--jarvis-cyan': '#FB7185',
            '--jarvis-blue': '#F43F5E',
            '--jarvis-purple': '#A78BFA',
        },
    },
};

const readSetting = (key, fallback) => {
    if (typeof window === 'undefined') return fallback;
    return window.localStorage.getItem(key) || fallback;
};

const ProfilePanel = ({ expanded = false }) => {
    const [theme, setTheme] = useState(() => readSetting('jarvis-dashboard-theme', 'cyan'));
    const [glow, setGlow] = useState(() => readSetting('jarvis-dashboard-glow', 'normal'));
    const [motion, setMotion] = useState(() => readSetting('jarvis-dashboard-motion', 'normal'));
    const [grid, setGrid] = useState(() => readSetting('jarvis-dashboard-grid', 'visible'));

    useEffect(() => {
        const root = document.querySelector('.jarvis-dashboard-root');
        if (!root) return;

        const selected = themes[theme] || themes.cyan;
        Object.entries(selected.colors).forEach(([key, value]) => {
            root.style.setProperty(key, value);
        });

        root.classList.toggle('is-soft-glow', glow === 'soft');
        root.classList.toggle('is-calm-motion', motion === 'calm');
        root.classList.toggle('is-grid-muted', grid === 'muted');

        window.localStorage.setItem('jarvis-dashboard-theme', theme);
        window.localStorage.setItem('jarvis-dashboard-glow', glow);
        window.localStorage.setItem('jarvis-dashboard-motion', motion);
        window.localStorage.setItem('jarvis-dashboard-grid', grid);
    }, [theme, glow, motion, grid]);

    return (
        <section className={`jarvis-profile-panel ${expanded ? 'is-open' : ''}`}>
            <div className="jarvis-profile-section">
                <div className="jarvis-profile-section-title">
                    <Palette size={13} />
                    Preferencias visuales
                </div>
                <div className="jarvis-theme-options">
                    {Object.entries(themes).map(([key, item]) => (
                        <button
                            key={key}
                            type="button"
                            className={theme === key ? 'is-active' : ''}
                            onClick={() => setTheme(key)}
                        >
                            {item.label}
                        </button>
                    ))}
                </div>
            </div>

            <div className="jarvis-profile-section">
                <div className="jarvis-profile-section-title">
                    <Sparkles size={13} />
                    Brillo
                </div>
                <div className="jarvis-theme-options compact">
                    <button
                        type="button"
                        className={glow === 'normal' ? 'is-active' : ''}
                        onClick={() => setGlow('normal')}
                    >
                        Neón
                    </button>
                    <button
                        type="button"
                        className={glow === 'soft' ? 'is-active' : ''}
                        onClick={() => setGlow('soft')}
                    >
                        Suave
                    </button>
                </div>
            </div>

            <div className="jarvis-profile-section">
                <div className="jarvis-profile-section-title">
                    <Waves size={13} />
                    Movimiento
                </div>
                <div className="jarvis-theme-options compact">
                    <button
                        type="button"
                        className={motion === 'normal' ? 'is-active' : ''}
                        onClick={() => setMotion('normal')}
                    >
                        Dinámico
                    </button>
                    <button
                        type="button"
                        className={motion === 'calm' ? 'is-active' : ''}
                        onClick={() => setMotion('calm')}
                    >
                        Calma
                    </button>
                </div>
            </div>

            <div className="jarvis-profile-section">
                <div className="jarvis-profile-section-title">
                    <Grid3X3 size={13} />
                    Retícula
                </div>
                <div className="jarvis-theme-options compact">
                    <button
                        type="button"
                        className={grid === 'visible' ? 'is-active' : ''}
                        onClick={() => setGrid('visible')}
                    >
                        Visible
                    </button>
                    <button
                        type="button"
                        className={grid === 'muted' ? 'is-active' : ''}
                        onClick={() => setGrid('muted')}
                    >
                        Sutil
                    </button>
                </div>
            </div>
        </section>
    );
};

export default ProfilePanel;
