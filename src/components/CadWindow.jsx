import React, { useMemo, useState, useEffect, useRef } from 'react';
import { Canvas, useLoader, useFrame } from '@react-three/fiber';
import { OrbitControls, Center, Bounds, Environment } from '@react-three/drei';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader';
import { Printer, Library } from 'lucide-react';

const API_BASE = 'http://localhost:8000';

const GeometryModel = ({ geometry }) => {
    return (
        <mesh geometry={geometry} castShadow receiveShadow>
            <meshStandardMaterial color="#06b6d4" roughness={0.3} metalness={0.8} />
        </mesh>
    );
};

const LoadingCube = () => {
    const meshRef = React.useRef();
    useFrame((state, delta) => {
        meshRef.current.rotation.x += delta;
        meshRef.current.rotation.y += delta;
    });
    return (
        <mesh ref={meshRef}>
            <boxGeometry args={[10, 10, 10]} />
            <meshStandardMaterial wireframe color="cyan" transparent opacity={0.5} />
        </mesh>
    );
};

const CadWindow = ({ data, thoughts, retryInfo = {}, onClose, onRequestPrint, socket }) => {
    // data format: { format: "stl", data: "base64..." }
    const [isIterating, setIsIterating] = useState(false);
    const [prompt, setPrompt] = useState("");
    const [isSending, setIsSending] = useState(false);
    const thoughtsEndRef = useRef(null);

    // Library: previously generated STLs that can be reopened.
    const [showLibrary, setShowLibrary] = useState(false);
    const [models, setModels] = useState([]);
    const [libraryError, setLibraryError] = useState(null);
    const [localModel, setLocalModel] = useState(null); // a model loaded from the library
    const [loadingModelId, setLoadingModelId] = useState(null);

    // A library model overrides the live `data` until a new generation arrives.
    const effectiveData = localModel || data;

    // Debug log
    useEffect(() => {
        if (data) console.log("CadWindow Data:", data.format);
        // A fresh generation/iteration result should take over the viewport.
        if (data && (data.format === 'loading' || (data.format === 'stl' && data.data))) {
            setLocalModel(null);
        }
    }, [data]);

    // Auto-scroll thoughts panel
    useEffect(() => {
        if (thoughtsEndRef.current) {
            thoughtsEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [thoughts]);

    const fetchModels = async () => {
        setLibraryError(null);
        try {
            const res = await fetch(`${API_BASE}/api/cad/models`);
            const json = await res.json();
            setModels(json.models || []);
        } catch (e) {
            console.error("Failed to load model library:", e);
            setLibraryError("No se pudo cargar la biblioteca.");
        }
    };

    const toggleLibrary = () => {
        const next = !showLibrary;
        setShowLibrary(next);
        if (next) fetchModels();
    };

    const openModel = async (id) => {
        setLoadingModelId(id);
        try {
            const res = await fetch(`${API_BASE}/api/cad/models/${encodeURIComponent(id)}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const json = await res.json();
            setLocalModel({ format: 'stl', data: json.data, name: json.name });
            setShowLibrary(false);
            setIsIterating(false);
        } catch (e) {
            console.error("Failed to open model:", e);
            setLibraryError("No se pudo abrir el modelo.");
        } finally {
            setLoadingModelId(null);
        }
    };

    const geometry = useMemo(() => {
        if (!effectiveData || effectiveData.format !== 'stl' || !effectiveData.data) return null;

        try {
            // Convert Base64 to ArrayBuffer
            const byteCharacters = atob(effectiveData.data);
            const byteNumbers = new Array(byteCharacters.length);
            for (let i = 0; i < byteCharacters.length; i++) {
                byteNumbers[i] = byteCharacters.charCodeAt(i);
            }
            const byteArray = new Uint8Array(byteNumbers);

            // Parse directly using THREE.STLLoader
            const loader = new STLLoader();
            const geom = loader.parse(byteArray.buffer);
            geom.center(); // Optional: Center the geometry
            return geom;
        } catch (e) {
            console.error("Failed to decode/parse STL:", e);
            return null;
        }
    }, [effectiveData]);

    const handleGenerate = () => {
        if (!prompt.trim()) return;
        setIsSending(true);
        if (socket) {
            socket.emit('generate_cad', { prompt });
        } else {
            console.error("Socket not available in CadWindow");
        }
        setPrompt("");
        // NOTE: We don't clear isSending immediately here if we want to show loading state until data arrives.
        // But for UI responsiveness we might want to just show global loading or similar.
        // For now, let's timeout or rely on parent updates.
        // Actually, let's just keep isSending true until we get an update? 
        // But we don't listen to socket here.
        // Let's reset it after a short delay so user knows it was sent.
        setTimeout(() => setIsSending(false), 2000);
    };

    const handleIterate = () => {
        if (!prompt.trim()) return;
        setIsSending(true);
        // Assuming socket is passed as prop or available globally. 
        // If not, we might need to emit via window event or refactor App.jsx to pass it.
        // For now, looking at App.jsx structure, socket might not be prop. 
        // If socket is missing, we can use window.socket if available or emit a custom event.

        if (socket) {
            socket.emit('iterate_cad', { prompt });
        } else {
            console.error("Socket not available in CadWindow");
        }

        setIsIterating(false);
        setPrompt("");
        setIsSending(false);
    };

    return (
        <div className="w-full h-full relative group bg-gray-900 rounded-lg overflow-hidden border border-cyan-500/30">
            {/* Close Button */}
            <div className="absolute top-2 right-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={onClose} className="bg-red-500/20 hover:bg-red-500/50 text-red-500 p-1 rounded">X</button>
            </div>

            {/* Top Toolbar */}
            <div className="absolute top-2 left-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity flex gap-2">
                <button
                    onClick={() => setIsIterating(true)}
                    className="bg-cyan-500/20 hover:bg-cyan-500/50 text-cyan-400 text-xs px-2 py-1 rounded border border-cyan-500/30 backdrop-blur-sm"
                >
                    ITERATE
                </button>
                <button
                    onClick={() => {
                        if (onRequestPrint) onRequestPrint();
                    }}
                    className="bg-green-500/20 hover:bg-green-500/50 text-green-400 text-xs px-2 py-1 rounded border border-green-500/30 backdrop-blur-sm flex items-center gap-1"
                >
                    <Printer size={12} /> PRINT
                </button>
                <button
                    onClick={toggleLibrary}
                    className={`text-xs px-2 py-1 rounded border backdrop-blur-sm flex items-center gap-1 ${showLibrary ? 'bg-purple-500/50 text-white border-purple-400' : 'bg-purple-500/20 hover:bg-purple-500/50 text-purple-300 border-purple-500/30'}`}
                >
                    <Library size={12} /> MODELS
                </button>
            </div>

            {/* Iteration / Generation Overlay */}
            {/* Show if iterating OR if nothing is displayed (and not loading) */}
            {(isIterating || (!effectiveData && data?.format !== 'loading')) && (
                <div className={`absolute inset-0 z-20 ${!effectiveData ? 'bg-gray-900' : 'bg-black/80'} flex items-center justify-center p-4`}>
                    <div className="bg-gray-800 border border-cyan-500/50 rounded p-4 w-full max-w-sm pointer-events-auto shadow-[0_0_20px_rgba(6,182,212,0.2)]">
                        <h4 className="text-cyan-400 text-sm mb-2 font-mono">
                            {!effectiveData ? "New Design" : "Refine Design"}
                        </h4>
                        <textarea
                            value={prompt}
                            onChange={(e) => setPrompt(e.target.value)}
                            placeholder={!effectiveData ? "Describe what you want to create..." : "e.g., Make the wheels bigger..."}
                            className="w-full bg-gray-900 border border-gray-700 rounded p-2 text-white text-sm mb-3 focus:outline-none focus:border-cyan-500 h-24 resize-none"
                            autoFocus
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    !effectiveData ? handleGenerate() : handleIterate();
                                }
                            }}
                        />
                        <div className="flex justify-end gap-2">
                            {/* Only show cancel if we have something to go back to */}
                            {effectiveData && (
                                <button
                                    onClick={() => setIsIterating(false)}
                                    className="text-gray-400 text-xs hover:text-white px-2 py-1"
                                >
                                    Cancel
                                </button>
                            )}
                            <button
                                onClick={!effectiveData ? handleGenerate : handleIterate}
                                disabled={isSending}
                                className="bg-cyan-600 hover:bg-cyan-500 text-white text-xs px-3 py-1 rounded"
                            >
                                {isSending ? "Generating..." : (!effectiveData ? "Generate" : "Update")}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Model Library Panel */}
            {showLibrary && (
                <div className="absolute inset-y-0 left-0 w-2/3 max-w-xs z-30 bg-gray-900/95 backdrop-blur-sm border-r border-purple-500/30 flex flex-col pointer-events-auto">
                    <div className="flex items-center justify-between p-3 border-b border-purple-500/20">
                        <h4 className="text-purple-300 text-xs font-mono tracking-widest uppercase flex items-center gap-2">
                            <Library size={13} /> Modelos guardados
                        </h4>
                        <button onClick={() => setShowLibrary(false)} className="text-gray-400 hover:text-white text-xs">X</button>
                    </div>
                    {libraryError && (
                        <div className="m-2 p-2 bg-red-500/10 border border-red-500/30 rounded text-red-400 text-xs">{libraryError}</div>
                    )}
                    <div className="flex-1 overflow-y-auto p-2 space-y-1 scrollbar-thin scrollbar-thumb-purple-500/30">
                        {models.length === 0 && !libraryError && (
                            <p className="text-gray-500 text-xs p-2">Todavía no hay modelos generados.</p>
                        )}
                        {models.map((m) => (
                            <button
                                key={m.id}
                                onClick={() => openModel(m.id)}
                                disabled={loadingModelId === m.id}
                                className="w-full text-left p-2 rounded bg-gray-800/60 hover:bg-purple-500/20 border border-transparent hover:border-purple-500/40 transition-colors"
                            >
                                <div className="text-cyan-300 text-xs font-mono truncate">{m.name}</div>
                                <div className="text-gray-500 text-[10px] font-mono">
                                    {(m.size / 1024).toFixed(0)} KB · {new Date(m.modified * 1000).toLocaleString()}
                                    {loadingModelId === m.id ? " · cargando…" : ""}
                                </div>
                            </button>
                        ))}
                    </div>
                </div>
            )}

            <Canvas shadows dpr={[1, 1.5]} camera={{ position: [4, 4, 4], fov: 45, near: 0.01, far: 100000 }}>
                <color attach="background" args={['#101010']} />
                <ambientLight intensity={0.4} />
                <directionalLight position={[10, 10, 5]} intensity={1.2} castShadow />
                <Environment preset="city" />

                {data?.format === 'loading' ? (
                    <LoadingCube />
                ) : (
                    geometry && (
                        // Bounds auto-frames the model to the viewport (fit) and refits
                        // whenever a new geometry arrives (key) — works for tiny CAD parts
                        // and the full robot alike. `clip` adjusts near/far to the model.
                        <Bounds key={geometry.uuid} fit clip observe margin={1.2}>
                            <Center>
                                <GeometryModel geometry={geometry} />
                            </Center>
                        </Bounds>
                    )
                )}

                <OrbitControls
                    autoRotate={!isIterating}
                    autoRotateSpeed={1}
                    makeDefault
                    minDistance={0.01}
                    maxDistance={100000}
                />
            </Canvas>

            {/* Streaming Thoughts Panel */}
            {data?.format === 'loading' && (
                <div className="absolute inset-y-0 right-0 w-2/5 p-4 bg-black/70 backdrop-blur-sm border-l border-green-500/30 overflow-hidden flex flex-col">
                    <div className="flex items-center justify-between mb-2">
                        <h4 className="text-green-400 text-xs font-mono tracking-widest uppercase flex items-center gap-2">
                            <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
                            Designer Thinking...
                        </h4>
                        {retryInfo.attempt && (
                            <span className={`text-xs font-mono px-2 py-0.5 rounded ${retryInfo.error ? 'bg-yellow-500/20 text-yellow-400' : 'bg-cyan-500/20 text-cyan-400'}`}>
                                Attempt {retryInfo.attempt}/{retryInfo.maxAttempts || 3}
                            </span>
                        )}
                    </div>
                    {retryInfo.error && (
                        <div className="mb-2 p-2 bg-red-500/10 border border-red-500/30 rounded text-red-400 text-xs font-mono">
                            <span className="text-red-500 font-bold">⚠ Error:</span> {retryInfo.error}
                        </div>
                    )}
                    <div className="flex-1 overflow-y-auto text-green-400/80 text-xs font-mono whitespace-pre-wrap leading-relaxed scrollbar-thin scrollbar-thumb-green-500/30">
                        {thoughts}
                        <div ref={thoughtsEndRef} />
                    </div>
                </div>
            )}

            <div className="absolute bottom-2 left-2 text-[10px] text-cyan-500/50 font-mono tracking-widest pointer-events-none">
                {localModel ? `LIBRARY: ${localModel.name}` : `CAD_ENGINE_V2: ${effectiveData?.format?.toUpperCase() || "READY"}`}
            </div>
        </div>
    );
};

export default CadWindow;
