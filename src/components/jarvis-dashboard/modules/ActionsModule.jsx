import React from 'react';
import { Check, RefreshCw, X } from 'lucide-react';

const ActionsModule = ({ context, actions }) => {
    const { pendingActions, loading, errors } = context;

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Confirmaciones reales</span>
                    <h2>Acciones pendientes</h2>
                </div>
                <button type="button" className="jarvis-module-button" onClick={actions.onRefreshPending}>
                    <RefreshCw size={14} /> Actualizar
                </button>
            </div>

            {errors.pending && <div className="jarvis-soft-error">{errors.pending}</div>}
            {loading.pending && <div className="jarvis-empty-state compact">Cargando acciones pendientes...</div>}

            <div className="jarvis-module-grid two">
                {pendingActions.length === 0 && <div className="jarvis-empty-state">No hay acciones pendientes.</div>}
                {pendingActions.map(action => (
                    <article className="jarvis-module-card" key={action.id}>
                        <span>{action.action_type || 'Sin tipo'}</span>
                        <strong>{action.human_summary || 'Acción pendiente'}</strong>
                        <p>{action.created_at || 'Sin fecha'}</p>
                        <div className="jarvis-module-actions">
                            <button type="button" onClick={() => actions.onConfirmPending(action.id)}><Check size={14} /> Confirmar</button>
                            <button type="button" onClick={() => actions.onCancelPending(action.id)}><X size={14} /> Cancelar</button>
                        </div>
                    </article>
                ))}
            </div>
        </section>
    );
};

export default ActionsModule;
