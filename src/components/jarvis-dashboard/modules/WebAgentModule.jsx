import React, { useState } from 'react';
import { Globe, Send } from 'lucide-react';

const WebAgentModule = ({ context, actions }) => {
    const [prompt, setPrompt] = useState('');
    const { browserData, showBrowserWindow } = context;

    const runPrompt = () => {
        if (!prompt.trim()) return;
        actions.onRunWebAgent(prompt.trim());
        setPrompt('');
    };

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Automatización web visual</span>
                    <h2>Web Agent</h2>
                </div>
                <button type="button" className="jarvis-module-button" onClick={() => actions.onQuickAction('toggle-browser')}>
                    {showBrowserWindow ? 'Cerrar agente' : 'Abrir agente'}
                </button>
            </div>

            <section className="jarvis-panel jarvis-web-agent-panel">
                <Globe size={24} />
                <strong>{showBrowserWindow ? 'Browser activo' : 'Browser cerrado'}</strong>
                <p>{browserData?.logs?.slice(-1)[0] || 'Sin resultados web recientes.'}</p>
                <div className="jarvis-inline-form">
                    <input value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Busca..." />
                    <button type="button" onClick={runPrompt}><Send size={14} /> Ejecutar</button>
                </div>
            </section>
        </section>
    );
};

export default WebAgentModule;
