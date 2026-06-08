import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ListTodo, Plus, RefreshCw } from 'lucide-react';
import {
    addSubtask,
    createTask,
    deleteSubtask,
    deleteTask,
    getTasks,
    recommendTaskOrder,
    updateSubtask,
    updateTask,
} from '../../../services/jarvisDashboardApi';
import { socket } from '../../../services/socketClient';
import TaskCard from './tasks/TaskCard';
import TaskDetail from './tasks/TaskDetail';
import CreateTaskModal from './tasks/CreateTaskModal';

const TasksModule = () => {
    const [tasks, setTasks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [selectedId, setSelectedId] = useState(null);
    const [showCreate, setShowCreate] = useState(false);

    const refresh = useCallback(async () => {
        const response = await getTasks();
        if (response.ok) {
            setTasks(response.data?.tasks || []);
            setError('');
        } else {
            setError(response.error || 'No se pudieron cargar las tareas.');
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        refresh();
        // Live updates from any source (dashboard or voice commands).
        const handler = (payload) => {
            if (payload?.tasks) setTasks(payload.tasks);
            else refresh();
        };
        socket.on('tasks_update', handler);
        return () => socket.off('tasks_update', handler);
    }, [refresh]);

    const selectedTask = useMemo(
        () => tasks.find((t) => t.id === selectedId) || null,
        [tasks, selectedId],
    );

    // If the open task disappears (deleted elsewhere), fall back to the list.
    useEffect(() => {
        if (selectedId && !tasks.some((t) => t.id === selectedId)) {
            setSelectedId(null);
        }
    }, [tasks, selectedId]);

    // --- mutations (optimistic-ish: apply server response, socket also syncs) ---
    const applyTask = (response) => {
        if (response.ok && response.data?.task) {
            const updated = response.data.task;
            setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
            return updated;
        }
        refresh();
        return null;
    };

    const handleCreate = async (title, description) => {
        const response = await createTask(title, description);
        if (response.ok && response.data?.task) {
            await refresh();
            setSelectedId(response.data.task.id);
            return response.data.task;
        }
        setError(response.error || 'No se pudo crear la tarea.');
        return null;
    };

    const handleDeleteTask = async (taskId) => {
        if (!window.confirm('¿Eliminar esta tarea y todas sus subtareas?')) return;
        const response = await deleteTask(taskId);
        if (response.ok) {
            setTasks((prev) => prev.filter((t) => t.id !== taskId));
            if (selectedId === taskId) setSelectedId(null);
        } else {
            setError(response.error || 'No se pudo eliminar la tarea.');
        }
    };

    const handleRenameTask = (taskId, title) => updateTask(taskId, { title }).then(applyTask);
    const handleAddSubtask = (taskId, payload) => addSubtask(taskId, payload).then(applyTask);
    const handleToggleSubtask = (taskId, subId, completed) =>
        updateSubtask(taskId, subId, { completed }).then(applyTask);
    const handleRenameSubtask = (taskId, subId, title) =>
        updateSubtask(taskId, subId, { title }).then(applyTask);
    const handleDeleteSubtask = (taskId, subId) => deleteSubtask(taskId, subId).then(applyTask);

    const handleRecommend = async (taskId) => {
        const response = await recommendTaskOrder(taskId);
        return response.ok ? response.data?.recommendation : null;
    };

    const totalTasks = tasks.length;
    const avgProgress = totalTasks
        ? Math.round(tasks.reduce((sum, t) => sum + (t.progress || 0), 0) / totalTasks)
        : 0;

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Listas de tareas con progreso</span>
                    <h2>Tareas</h2>
                </div>
                <div className="jarvis-module-header-actions">
                    <button type="button" className="jarvis-module-button" onClick={refresh}>
                        <RefreshCw size={14} /> Actualizar
                    </button>
                    <button type="button" className="jarvis-module-button is-primary" onClick={() => setShowCreate(true)}>
                        <Plus size={14} /> Nueva tarea
                    </button>
                </div>
            </div>

            {error && <div className="jarvis-soft-error">{error}</div>}

            {selectedTask ? (
                <TaskDetail
                    task={selectedTask}
                    onBack={() => setSelectedId(null)}
                    onRenameTask={(title) => handleRenameTask(selectedTask.id, title)}
                    onDeleteTask={() => handleDeleteTask(selectedTask.id)}
                    onAddSubtask={(payload) => handleAddSubtask(selectedTask.id, payload)}
                    onToggleSubtask={(subId, completed) => handleToggleSubtask(selectedTask.id, subId, completed)}
                    onRenameSubtask={(subId, title) => handleRenameSubtask(selectedTask.id, subId, title)}
                    onDeleteSubtask={(subId) => handleDeleteSubtask(selectedTask.id, subId)}
                    onRecommend={() => handleRecommend(selectedTask.id)}
                />
            ) : (
                <>
                    {totalTasks > 0 && (
                        <div className="jarvis-tasks-summary">
                            <span><strong>{totalTasks}</strong> tarea(s)</span>
                            <span>Progreso medio <strong>{avgProgress}%</strong></span>
                        </div>
                    )}

                    {loading && <div className="jarvis-empty-state compact">Cargando tareas…</div>}
                    {!loading && totalTasks === 0 && (
                        <div className="jarvis-tasks-empty">
                            <ListTodo size={40} />
                            <strong>Aún no tienes tareas</strong>
                            <span>Crea tu primera lista o pídeselo a Jarvis: «crea una tarea llamada…».</span>
                            <button type="button" className="jarvis-module-button is-primary" onClick={() => setShowCreate(true)}>
                                <Plus size={14} /> Crear tarea
                            </button>
                        </div>
                    )}

                    <div className="jarvis-tasks-grid">
                        {tasks.map((task) => (
                            <TaskCard
                                key={task.id}
                                task={task}
                                onOpen={setSelectedId}
                                onDelete={handleDeleteTask}
                            />
                        ))}
                    </div>
                </>
            )}

            {showCreate && (
                <CreateTaskModal onClose={() => setShowCreate(false)} onCreate={handleCreate} />
            )}
        </section>
    );
};

export default TasksModule;
