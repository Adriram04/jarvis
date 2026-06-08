import React from 'react';
import { ChevronRight, ListChecks, Trash2 } from 'lucide-react';
import ProgressBar from './ProgressBar';

const TaskCard = ({ task, onOpen, onDelete }) => {
    const completed = task.completed_count ?? 0;
    const total = task.subtask_count ?? (task.subtasks?.length || 0);

    return (
        <article className="jarvis-task-card" onClick={() => onOpen?.(task.id)}>
            <div className="jarvis-task-card-top">
                <div className="jarvis-task-card-title">
                    <ListChecks size={16} />
                    <strong>{task.title}</strong>
                </div>
                <button
                    type="button"
                    className="jarvis-task-card-delete"
                    title="Eliminar tarea"
                    onClick={(e) => { e.stopPropagation(); onDelete?.(task.id); }}
                >
                    <Trash2 size={15} />
                </button>
            </div>

            {task.description && <p className="jarvis-task-card-desc">{task.description}</p>}

            <ProgressBar value={task.progress} />

            <div className="jarvis-task-card-foot">
                <span>{completed}/{total} subtareas</span>
                <span className="jarvis-task-card-open">Ver detalle <ChevronRight size={13} /></span>
            </div>
        </article>
    );
};

export default TaskCard;
