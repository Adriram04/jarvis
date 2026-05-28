import React, { useEffect, useState } from 'react';
import { Palette } from 'lucide-react';

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
};

const readInitialTheme = () => {
    if (typeof window === 'undefined') return 'cyan';
    return window.localStorage.getItem('jarvis-dashboard-theme') || 'cyan';
};

const readInitialGlow = () => {
    if (typeof window === 'undefined') return 'normal';
    return window.localStorage.getItem('jarvis-dashboard-glow') || 'normal';
};

const ProfilePanel = ({ expanded = false }) => {
    const [theme, setTheme] = useState(readInitialTheme);
    const [glow, setGlow] = useState(readInitialGlow);

    useEffect(() => {
        const root = document.querySelector('.jarvis-dashboard-root');
        if (!root) return;

        const selected = themes[theme] || themes.cyan;
        Object.entries(selected.colors).forEach(([key, value]) => {
            root.style.setProperty(key, value);
        });
        root.classList.toggle('is-soft-glow', glow === 'soft');
        window.localStorage.setItem('jarvis-dashboard-theme', theme);
        window.localStorage.setItem('jarvis-dashboard-glow', glow);
    }, [theme, glow]);

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
        </section>
    );
};

export default ProfilePanel;
