import React, { useState } from 'react';
import { Box, Printer } from 'lucide-react';
import { formatPrinterState } from '../../../utils/printerStatus';

const Cad3DModule = ({ context, actions }) => {
    const [prompt, setPrompt] = useState('');
    const { activePrintStatus, printerCount, showCadWindow, showPrinterWindow, slicingStatus } = context;
    const printStateLabel = activePrintStatus?.state ? formatPrinterState(activePrintStatus.state) : null;

    const preparePrompt = () => {
        actions.setInputValue(`Genera un modelo 3D de ${prompt}`.trim());
    };

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Modelado y fabricación</span>
                    <h2>CAD / 3D</h2>
                </div>
            </div>

            <div className="jarvis-module-grid two">
                <article className="jarvis-module-card">
                    <Box size={22} />
                    <span>CAD</span>
                    <strong>{showCadWindow ? 'Ventana abierta' : 'Ventana cerrada'}</strong>
                    <p>Generación, iteración y vista 3D de modelos.</p>
                    <div className="jarvis-module-actions">
                        <button type="button" onClick={() => actions.onQuickAction('toggle-cad')}>{showCadWindow ? 'Cerrar CAD' : 'Abrir CAD'}</button>
                    </div>
                    <div className="jarvis-inline-form">
                        <input value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Genera un modelo 3D de..." />
                        <button type="button" onClick={preparePrompt}>Preparar</button>
                    </div>
                </article>

                <article className="jarvis-module-card">
                    <Printer size={22} />
                    <span>Impresión 3D</span>
                    <strong>{printerCount > 0 ? `${printerCount} impresora(s)` : 'Sin impresoras detectadas'}</strong>
                    <p>{printStateLabel || slicingStatus?.message || 'Slicing, estado y control de impresión.'}</p>
                    {slicingStatus?.active && <div className="jarvis-meter-line"><span style={{ width: `${slicingStatus.percent || 0}%` }} /></div>}
                    <button type="button" onClick={() => actions.onQuickAction('toggle-printer')}>{showPrinterWindow ? 'Cerrar impresión' : 'Abrir impresión'}</button>
                </article>
            </div>
        </section>
    );
};

export default Cad3DModule;
