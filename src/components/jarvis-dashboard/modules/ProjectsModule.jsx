import React, { useEffect, useMemo, useState } from 'react';
import { File, Folder, FolderOpen, RefreshCw } from 'lucide-react';

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

    useEffect(() => {
        if (!projects.length) {
            actions.onRefreshProjects?.();
        }
    }, []);

    useEffect(() => {
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

    useEffect(() => {
        if (selectedProject) {
            actions.onLoadProjectTree?.(selectedProject);
        }
    }, [selectedProject, selectedSummary?.updated_at]);

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
                            className={`jarvis-project-card ${selectedProject === project.name ? 'is-active' : ''}`}
                            onClick={() => setSelectedProject(project.name)}
                        >
                            <FolderOpen size={17} />
                            <span>{project.name}</span>
                            <small>{project.files_count || 0} archivos - {project.folders_count || 0} carpetas</small>
                        </button>
                    ))}
                </section>

                <section className="jarvis-panel jarvis-project-detail">
                    <div className="jarvis-panel-header compact">
                        <div>
                            <div className="jarvis-panel-title">{selectedProject || 'Sin proyecto seleccionado'}</div>
                            {selectedSummary && <span className="jarvis-muted-line">{selectedSummary.path}</span>}
                        </div>
                    </div>

                    {projectTreeError && <div className="jarvis-soft-error">{projectTreeError}</div>}
                    {projectTreeLoading && <div className="jarvis-empty-state compact">Leyendo archivos del proyecto...</div>}
                    {!projectTreeLoading && !projectTree?.tree && <div className="jarvis-empty-state">Selecciona un proyecto para ver sus archivos.</div>}
                    {projectTree?.tree && <TreeNode node={projectTree.tree} />}
                </section>
            </div>
        </section>
    );
};

export default ProjectsModule;
