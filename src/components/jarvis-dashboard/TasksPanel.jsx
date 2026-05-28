import React from 'react';
import { Plus } from 'lucide-react';

const TasksPanel = ({ tasks = [], onAddTask }) => {
    return (
        <section className="jarvis-panel jarvis-list-panel">
            <div className="jarvis-panel-header">
                <h2>Tareas</h2>
                <button type="button" onClick={onAddTask}>Ver todas</button>
            </div>
            <div className="jarvis-task-list">
                {tasks.map((task) => (
                    <article className="jarvis-task-item" key={task.title}>
                        <span className={`jarvis-task-priority ${task.priority}`} />
                        <div>
                            <strong>{task.title}</strong>
                            <span>{task.detail}</span>
                        </div>
                    </article>
                ))}
            </div>
            <button type="button" className="jarvis-panel-action" onClick={onAddTask}>
                <Plus size={15} /> Añadir tarea
            </button>
        </section>
    );
};

export default TasksPanel;
