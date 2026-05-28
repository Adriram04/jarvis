import React from 'react';
import { Settings } from 'lucide-react';

const SettingsModule = ({ actions }) => {
    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Permisos y dispositivos</span>
                    <h2>Ajustes</h2>
                </div>
            </div>

            <article className="jarvis-panel jarvis-settings-card">
                <Settings size={24} />
                <strong>Abrir ajustes reales</strong>
                <p>Micrófono, altavoz, webcam, Face Auth, permisos de herramientas, memoria y gestos se configuran en la ventana existente.</p>
                <button type="button" onClick={actions.onOpenSettings}>Abrir ajustes</button>
            </article>
        </section>
    );
};

export default SettingsModule;
