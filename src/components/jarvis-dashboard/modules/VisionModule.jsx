import React from 'react';
import { Camera, Eye, Hand, ShieldCheck } from 'lucide-react';

const VisionModule = ({ context, actions }) => {
    const { faceAuthEnabled, fps, isHandTrackingEnabled, isVideoOn } = context;

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Cámara, gestos y autenticación</span>
                    <h2>Visión</h2>
                </div>
            </div>

            <div className="jarvis-module-grid three">
                <article className="jarvis-module-card">
                    <Camera size={22} />
                    <span>Cámara</span>
                    <strong>{isVideoOn ? `Activa${fps ? ` · ${fps} FPS` : ''}` : 'Inactiva'}</strong>
                    <p>Feed flotante existente de Jarvis.</p>
                    <button type="button" onClick={() => actions.onQuickAction('toggle-video')}>
                        {isVideoOn ? 'Desactivar cámara' : 'Activar cámara'}
                    </button>
                </article>

                <article className="jarvis-module-card">
                    <Hand size={22} />
                    <span>Gestos</span>
                    <strong>{isHandTrackingEnabled ? 'Activos' : 'Inactivos'}</strong>
                    <p>Cursor por mano, pinch click, fist drag.</p>
                    <button type="button" onClick={() => actions.onQuickAction('toggle-hand')}>
                        {isHandTrackingEnabled ? 'Desactivar gestos' : 'Activar gestos'}
                    </button>
                </article>

                <article className="jarvis-module-card">
                    <ShieldCheck size={22} />
                    <span>Face Auth</span>
                    <strong>{faceAuthEnabled ? 'Activo' : 'Inactivo'}</strong>
                    <p>Autenticación facial configurada desde ajustes.</p>
                    <button type="button" onClick={actions.onOpenSettings}>Abrir ajustes</button>
                </article>
            </div>

            <section className="jarvis-panel jarvis-vision-guide">
                <div className="jarvis-panel-title"><Eye size={15} /> Guía de gestos</div>
                <div className="jarvis-guide-row">
                    <span>Mano abierta</span>
                    <strong>Cursor</strong>
                </div>
                <div className="jarvis-guide-row">
                    <span>Pinch</span>
                    <strong>Click</strong>
                </div>
                <div className="jarvis-guide-row">
                    <span>Puño</span>
                    <strong>Arrastre</strong>
                </div>
            </section>
        </section>
    );
};

export default VisionModule;
