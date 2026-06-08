import React from 'react';
import SubtaskItem from './SubtaskItem';

const SubtaskList = ({ subtasks = [], onToggle, onRename, onDelete }) => {
    if (!subtasks.length) {
        return <div className="jarvis-empty-state compact">Sin subtareas todavía. Añade la primera abajo.</div>;
    }

    // Pending first, completed (struck through) at the bottom.
    const ordered = [...subtasks].sort((a, b) => Number(a.completed) - Number(b.completed));

    return (
        <div className="jarvis-subtask-list">
            {ordered.map((subtask) => (
                <SubtaskItem
                    key={subtask.id}
                    subtask={subtask}
                    onToggle={onToggle}
                    onRename={onRename}
                    onDelete={onDelete}
                />
            ))}
        </div>
    );
};

export default SubtaskList;
