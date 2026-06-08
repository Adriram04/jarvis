import React, { useState } from 'react';
import { ArrowLeft, Check, Pencil, Sparkles, Trash2 } from 'lucide-react';
import ProgressBar from './ProgressBar';
import SubtaskList from './SubtaskList';
import AddSubtaskForm from './AddSubtaskForm';

const TaskDetail = ({
    task,
    onBack,
    onRenameTask,
    onDeleteTask,
    onAddSubtask,
    onToggleSubtask,
    onRenameSubtask,
    onDeleteSubtask,
    onRecommend,
}) => {
    const [editingTitle, setEditingTitle] = useState(false);
    const [draftTitle, setDraftTitle] = useState(task.title);
    const [recommendation, setRecommendation] = useState(null);
    const [recommending, setRecommending] = useState(false);

    const commitTitle = () => {
        const value = draftTitle.trim();
        setEditingTitle(false);
        if (value && value !== task.title) onRenameTask?.(value);
        else setDraftTitle(task.title);
    };

    const runRecommend = async () => {
        if (recommending) return;
        setRecommending(true);
        const result = await onRecommend?.();
        setRecommending(false);
        setRecommendation(result || { order: [], message: 'Sin recomendación.' });
    };

    const pending = (task.subtasks || []).filter((s) => !s.completed).length;

    return (
        <section className="jarvis-task-detail">
            <div className="jarvis-task-detail-header">
                <button type="button" className="jarvis-task-back" onClick={onBack}>
                    <ArrowLeft size={16} /> Tareas
                </button>
                <div className="jarvis-task-detail-actions">
                    <button type="button" onClick={() => setEditingTitle(true)} title="Editar nombre"><Pencil size={15} /></button>
                    <button type="button" className="is-danger" onClick={() => onDeleteTask?.()} title="Eliminar tarea"><Trash2 size={15} /></button>
                </div>
            </div>

            <div className="jarvis-task-detail-titlebar">
                {editingTitle ? (
                    <input
                        className="jarvis-task-title-edit"
                        value={draftTitle}
                        autoFocus
                        onChange={(e) => setDraftTitle(e.target.value)}
                        onBlur={commitTitle}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') commitTitle();
                            if (e.key === 'Escape') { setDraftTitle(task.title); setEditingTitle(false); }
                        }}
                    />
                ) : (
                    <h2 onDoubleClick={() => setEditingTitle(true)}>{task.title}</h2>
                )}
                {editingTitle && <button type="button" className="jarvis-inline-save" onClick={commitTitle}><Check size={15} /></button>}
            </div>

            {task.description && <p className="jarvis-task-detail-desc">{task.description}</p>}

            <div className="jarvis-task-detail-progress">
                <ProgressBar value={task.progress} />
                <span>{task.completed_count}/{task.subtask_count} completadas</span>
            </div>

            <div className="jarvis-task-recommend">
                <button type="button" className="jarvis-task-recommend-btn" onClick={runRecommend} disabled={recommending || pending === 0}>
                    <Sparkles size={14} /> {recommending ? 'Pensando…' : '¿Por dónde empiezo?'}
                </button>
                {recommendation && (
                    <div className="jarvis-task-recommend-result">
                        {recommendation.message && <p className="jarvis-task-recommend-msg">{recommendation.message}</p>}
                        {(recommendation.order || []).length > 0 ? (
                            <ol>
                                {recommendation.order.map((item, i) => (
                                    <li key={i}>
                                        <strong>{item.title}</strong>
                                        {item.reason && <span> — {item.reason}</span>}
                                    </li>
                                ))}
                            </ol>
                        ) : (
                            <p className="jarvis-empty-state compact">No hay subtareas pendientes que ordenar.</p>
                        )}
                    </div>
                )}
            </div>

            <SubtaskList
                subtasks={task.subtasks}
                onToggle={onToggleSubtask}
                onRename={onRenameSubtask}
                onDelete={onDeleteSubtask}
            />

            <AddSubtaskForm onAdd={onAddSubtask} />
        </section>
    );
};

export default TaskDetail;
