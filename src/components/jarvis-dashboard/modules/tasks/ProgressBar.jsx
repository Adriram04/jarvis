import React from 'react';

const ProgressBar = ({ value = 0, showLabel = true }) => {
    const pct = Math.max(0, Math.min(100, Math.round(value || 0)));
    const state = pct === 100 ? 'is-complete' : pct === 0 ? 'is-empty' : '';

    return (
        <div className="jarvis-task-progress">
            <div className={`jarvis-task-progress-track ${state}`}>
                <div className="jarvis-task-progress-fill" style={{ width: `${pct}%` }} />
            </div>
            {showLabel && <span className="jarvis-task-progress-label">{pct}%</span>}
        </div>
    );
};

export default ProgressBar;
