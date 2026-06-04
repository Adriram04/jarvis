import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, File, Folder, FolderOpen, RefreshCw } from 'lucide-react';

const TreeNode = ({ node, depth = 0 }) => {
    const isFolder = node.type === 'folder';
    const children = node.children || [];

    return (
        <div className="jarvis-project-tree-node" style={{ '--tree-depth': depth }}>
            <div className="jarvis-project-tree-row">
                {isFolder ? <Folder size={15} /> : <File size={15} />}
                <span>{node.name}</span>
                <small>{isFolder ? `${children.length} elementos` : node.size ? `${node.size} B` : 'Archivo'}</small>
            </div>
            {isFolder && children.length > 0 && (
                <div className="jarvis-project-tree-children">
                    {children.map(child => (
                        <TreeNode key={`${child.path}-${child.name}`} node={child} depth={depth + 1} />
                    ))}
                </div>
            )}
        </div>
    );
};

const ProjectsModule = ({ context, actions }) => {
    const { currentProject, projects = [], projectTree, projectTreeError, projectTreeLoading, projectsError, projectsLoading } = context;
    const [selectedProject, setSelectedProject] = useState('');
    const [activatingProject, setActivatingProject] = useState('');
    const [activationFeedback, setActivationFeedback] = useState(null);

    useEffect(() => {
        if (!projects.length) {
            actions.onRefreshProjects?.();
        }
    }, []);

    useEffect(() => {
        if (!projects.length) {
            if (selectedProject) setSelectedProject('');
            return;
        }

        const selectedExists = selectedProject && projects.some(project => project.name === selectedProject);
        if (selectedExists) return;

        const currentExists = currentProject && projects.some(project => project.name === currentProject);
        const nextProject = currentExists ? currentProject : projects[0]?.name;
        if (nextProject && nextProject !== selectedProject) {
            setSelectedProject(nextProject);
        }
    }, [currentProject, projects, selectedProject]);

    const selectedSummary = useMemo(
        () => projects.find(project => project.name === selectedProject),
        [projects, selectedProject],
    );

    const loadedTreeProject = projectTree?.project?.name || projectTree?.tree?.name || '';
    const hasSelectedTree = Boolean(projectTree?.tree && loadedTreeProject === selectedProject);
    const selectedIsActive = Boolean(selectedProject && selectedProject === currentProject);

    useEffect(() => {
        if (selectedProject) {
            actions.onLoadProjectTree?.(selectedProject);
        }
    }, [selectedProject, selectedSummary?.updated_at]);

    const activateSelectedProject = async (projectName) => {
        const name = String(projectName || '').trim();
        if (!name || name === currentProject || activatingProject) return;

        setActivatingProject(name);
        setActivationFeedback(null);
        const response = await actions.onActivateProject?.(name);
        setActivatingProject('');

        if (response?.ok && response?.success) {
            const activeName = response.data?.current_project || name;
            setActivationFeedback({ type: 'success', text: `Proyecto activo: ${activeName}` });
        } else {
            setActivationFeedback({ type: 'error', text: response?.error || 'No se pudo activar el proyecto.' });
        }
    };

    const selectProject = (projectName) => {
        setSelectedProject(projectName);
        setActivationFeedback(null);
    };

    return (
        <section className="jarvis-module">
            <div className="jarvis-module-header">
                <div>
                    <span>Workspace real de Jarvis</span>
                    <h2>Proyectos</h2>
                </div>
                <button type="button" className="jarvis-module-button" onClick={actions.onRefreshProjects}>
                    <RefreshCw size={14} /> Actualizar
                </button>
            </div>

            {projectsError && <div className="jarvis-soft-error">{projectsError}</div>}
            {projectsLoading && <div className="jarvis-empty-state compact">Cargando proyectos...</div>}

            <div className="jarvis-projects-layout">
                <section className="jarvis-panel jarvis-project-list">
                    <div className="jarvis-panel-title">Proyectos creados</div>
                    {projects.length === 0 && !projectsLoading && <div className="jarvis-empty-state">Sin proyectos.</div>}
                    {projects.map(project => (
                        <button
                            key={project.name}
                            type="button"
                            className={`jarvis-project-card ${selectedProject === project.name ? 'is-active' : ''} ${currentProject === project.name ? 'is-current' : ''}`}
                            onClick={() => selectProject(project.name)}
                        >
                            <FolderOpen size={17} />
                            <span>{project.name}</span>
                            <small>{project.files_count || 0} archivos - {project.folders_count || 0} carpetas</small>
                            {currentProject === project.name && (
                                <small className="jarvis-project-card-status"><CheckCircle2 size={12} /> Activo</small>
                            )}
                        </button>
                    ))}
                </section>

                <section className="jarvis-panel jarvis-project-detail">
                    <div className="jarvis-panel-header compact">
                        <div>
                            <div className="jarvis-panel-title">{selectedProject || 'Sin proyecto seleccionado'}</div>
                            {selectedSummary && <span className="jarvis-muted-line">{selectedSummary.path}</span>}
                        </div>
                        {selectedProject && !selectedIsActive && (
                            <button
                                type="button"
                                className="jarvis-panel-action"
                                disabled={activatingProject === selectedProject}
                                onClick={() => activateSelectedProject(selectedProject)}
                            >
                                <CheckCircle2 size={14} /> {activatingProject === selectedProject ? 'Activando...' : 'Activar'}
                            </button>
                        )}
                    </div>

                    {activationFeedback && (
                        <div className={activationFeedback.type === 'error' ? 'jarvis-soft-error' : 'jarvis-soft-success'}>
                            {activationFeedback.text}
                        </div>
                    )}
                    {projectTreeError && <div className="jarvis-soft-error">{projectTreeError}</div>}
                    {projectTreeLoading && <div className="jarvis-empty-state compact">Leyendo archivos del proyecto...</div>}
                    {!projectTreeLoading && !hasSelectedTree && <div className="jarvis-empty-state">Selecciona un proyecto para ver sus archivos.</div>}
                    {hasSelectedTree && <TreeNode node={projectTree.tree} />}
                </section>
            </div>
        </section>
    );
};

export default ProjectsModule;
