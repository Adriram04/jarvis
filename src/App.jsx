import React, { useCallback, useEffect, useState, useRef } from 'react';
import io from 'socket.io-client';

import CadWindow from './components/CadWindow';
import BrowserWindow from './components/BrowserWindow';
import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision';
// MemoryPrompt removed - memory is now actively saved to project
import ConfirmationPopup from './components/ConfirmationPopup';
import AuthLock from './components/AuthLock';
import KasaWindow from './components/KasaWindow';
import PrinterWindow from './components/PrinterWindow';
import SettingsWindow from './components/SettingsWindow';
import SimulationDashboard from './components/SimulationDashboard';
import OpenClawDashboard from './components/OpenClawDashboard';
import CalendarEventModal from './components/jarvis-dashboard/CalendarEventModal';
import JarvisDashboard from './components/jarvis-dashboard/JarvisDashboard';
import LinkedInPostModal from './components/jarvis-dashboard/LinkedInPostModal';
import {
    cancelPendingAction,
    confirmPendingAction,
    createCalendarEvent,
    extractCalendarItems,
    getBackendStatus,
    getOpenClawEvents,
    getOpenClawStatus,
    getPendingActions,
    getProjects,
    getProjectTree,
    listCalendarEvents,
    normalizeCalendarEvent,
    normalizeOpenClawEvents,
    normalizePendingActions,
    prepareLinkedInPost,
    publishLinkedInPost,
} from './services/jarvisDashboardApi';



const socket = io('http://localhost:8000');
const { ipcRenderer } = window.require('electron');

function App() {
    const [status, setStatus] = useState('Disconnected');
    const [socketConnected, setSocketConnected] = useState(socket.connected); // Track socket connection reactively
    // Auth State
    const [isAuthenticated, setIsAuthenticated] = useState(() => {
        // Optimistically assume authenticated if face auth is NOT enabled
        return localStorage.getItem('face_auth_enabled') !== 'true';
    });

    // Initialize from LocalStorage to prevent flash of UI
    const [isLockScreenVisible, setIsLockScreenVisible] = useState(() => {
        const saved = localStorage.getItem('face_auth_enabled');
        // If saved is 'true', we MUST start locked.
        // If 'false' or null (default off), we start unlocked.
        return saved === 'true';
    });

    // Local state for tracking settings, also init from local storage
    const [faceAuthEnabled, setFaceAuthEnabled] = useState(() => {
        return localStorage.getItem('face_auth_enabled') === 'true';
    });


    const [isConnected, setIsConnected] = useState(true); // Power state DEFAULT ON
    const [isMuted, setIsMuted] = useState(true); // Mic state DEFAULT MUTED
    const [isVideoOn, setIsVideoOn] = useState(false); // Video state
    const [messages, setMessages] = useState([]);
    const [inputValue, setInputValue] = useState('');
    const [cadData, setCadData] = useState(null);
    const [cadThoughts, setCadThoughts] = useState(''); // Streaming AI thoughts
    const [cadRetryInfo, setCadRetryInfo] = useState({ attempt: 1, maxAttempts: 3, error: null }); // Retry status
    const [browserData, setBrowserData] = useState({ image: null, logs: [] });
    // showMemoryPrompt removed - memory is now actively saved to project
    const [confirmationRequest, setConfirmationRequest] = useState(null); // { id, tool, args }
    const [kasaDevices, setKasaDevices] = useState([]);
    const [showKasaWindow, setShowKasaWindow] = useState(false);
    const [showPrinterWindow, setShowPrinterWindow] = useState(false);
    const [showCadWindow, setShowCadWindow] = useState(false);
    const [showBrowserWindow, setShowBrowserWindow] = useState(false);
    const [showSimulationDashboard, setShowSimulationDashboard] = useState(false);
    const [showOpenClawDashboard, setShowOpenClawDashboard] = useState(false);
    const [simulationState, setSimulationState] = useState({ simulation_mode: false, kasa_simulation: false, printer_simulation: false });

    // Printing workflow status (for top toolbar display)
    const [slicingStatus, setSlicingStatus] = useState({ active: false, percent: 0, message: '' });
    const [activePrintStatus, setActivePrintStatus] = useState(null); // {printer, progress_percent, time_elapsed, state}
    const [printerCount, setPrinterCount] = useState(0); // Count of connected printers
    const [currentTime, setCurrentTime] = useState(new Date()); // Live clock
    const [backendStatus, setBackendStatus] = useState(null);
    const [openClawStatus, setOpenClawStatus] = useState(null);
    const [calendarEvents, setCalendarEvents] = useState([]);
    const [pendingActions, setPendingActions] = useState([]);
    const [openClawEvents, setOpenClawEvents] = useState([]);
    const [integrationStatuses, setIntegrationStatuses] = useState([]);
    const [dashboardLoading, setDashboardLoading] = useState({});
    const [dashboardError, setDashboardError] = useState({});
    const [showCalendarEventModal, setShowCalendarEventModal] = useState(false);
    const [showLinkedInPostModal, setShowLinkedInPostModal] = useState(false);
    const [activeModule, setActiveModule] = useState('home');
    const [projects, setProjects] = useState([]);
    const [projectTree, setProjectTree] = useState(null);
    const [projectTreeLoading, setProjectTreeLoading] = useState(false);
    const [projectTreeError, setProjectTreeError] = useState(null);


    // RESTORED STATE
    const [aiAudioData, setAiAudioData] = useState(new Array(64).fill(0));
    const [micAudioData, setMicAudioData] = useState(new Array(32).fill(0));
    const [fps, setFps] = useState(0);

    // Device states - microphones, speakers, webcams
    const [micDevices, setMicDevices] = useState([]);
    const [speakerDevices, setSpeakerDevices] = useState([]);
    const [webcamDevices, setWebcamDevices] = useState([]);

    // Selected device IDs - restored from localStorage
    const [selectedMicId, setSelectedMicId] = useState(() => localStorage.getItem('selectedMicId') || '');
    const [selectedSpeakerId, setSelectedSpeakerId] = useState(() => localStorage.getItem('selectedSpeakerId') || '');
    const [selectedWebcamId, setSelectedWebcamId] = useState(() => localStorage.getItem('selectedWebcamId') || '');
    const [showSettings, setShowSettings] = useState(false);
    const [currentProject, setCurrentProject] = useState('default');

    // Modular Mode State
    const [isModularMode, setIsModularMode] = useState(false);
    const [elementPositions, setElementPositions] = useState({
        video: { x: 40, y: 80 }, // Initial positions (approximate)
        visualizer: { x: window.innerWidth / 2, y: window.innerHeight / 2 - 150 },
        chat: { x: window.innerWidth / 2, y: window.innerHeight / 2 + 100 },
        cad: { x: window.innerWidth / 2 + 300, y: window.innerHeight / 2 },
        browser: { x: window.innerWidth / 2 - 300, y: window.innerHeight / 2 },
        kasa: { x: window.innerWidth / 2 + 350, y: window.innerHeight / 2 - 100 },
        printer: { x: window.innerWidth / 2 - 350, y: window.innerHeight / 2 - 100 },
        simulation: { x: window.innerWidth / 2, y: window.innerHeight / 2 },
        openclaw: { x: window.innerWidth / 2, y: window.innerHeight / 2 },
        tools: { x: window.innerWidth / 2, y: window.innerHeight - 100 } // Fixed bottom OFFSET
    });

    const [elementSizes, setElementSizes] = useState({
        visualizer: { w: 550, h: 350 },
        chat: { w: 550, h: 220 },
        tools: { w: 500, h: 80 }, // Approx
        cad: { w: 400, h: 400 },
        browser: { w: 550, h: 380 },
        video: { w: 320, h: 180 },
        kasa: { w: 300, h: 380 }, // Approx
        printer: { w: 380, h: 380 }, // Approx
        simulation: { w: 780, h: 620 },
        openclaw: { w: 920, h: 700 }
    });
    const [activeDragElement, setActiveDragElement] = useState(null);

    // Z-Index Stacking Order (last element = highest z-index)
    const [zIndexOrder, setZIndexOrder] = useState([
        'visualizer', 'chat', 'tools', 'video', 'cad', 'browser', 'kasa', 'printer', 'simulation', 'openclaw'
    ]);

    // Hand Control State
    const [cursorPos, setCursorPos] = useState({ x: 0, y: 0 });
    const [isPinching, setIsPinching] = useState(false);
    const [isHandTrackingEnabled, setIsHandTrackingEnabled] = useState(false); // DEFAULT OFF
    const [cursorSensitivity, setCursorSensitivity] = useState(2.0);
    const [isCameraFlipped, setIsCameraFlipped] = useState(false); // Gesture control camera flip

    // Refs for Loop Access (Avoiding Closure Staleness)
    const isHandTrackingEnabledRef = useRef(false); // DEFAULT OFF
    const cursorSensitivityRef = useRef(2.0);
    const isCameraFlippedRef = useRef(false);
    const faceAuthEnabledRef = useRef(faceAuthEnabled);
    const micDevicesRef = useRef([]);
    const selectedMicIdRef = useRef(selectedMicId);
    const pendingPowerOnRef = useRef(false);
    const handLandmarkerRef = useRef(null);
    const cursorTrailRef = useRef([]); // Stores last N positions for trail
    const [ripples, setRipples] = useState([]); // Visual ripples on click

    // Web Audio Context for Mic Visualization
    const audioContextRef = useRef(null);
    const analyserRef = useRef(null);
    const sourceRef = useRef(null);
    const micStreamRef = useRef(null);
    const animationFrameRef = useRef(null);

    // Video Refs
    const videoRef = useRef(null);
    const canvasRef = useRef(null);
    const transmissionCanvasRef = useRef(null); // Dedicated canvas for resizing payload
    const videoIntervalRef = useRef(null);
    const lastFrameTimeRef = useRef(0);
    const frameCountRef = useRef(0);
    const lastVideoTimeRef = useRef(-1);
    const sentVideoFramesRef = useRef(0);

    // Ref to track video state for the loop (avoids closure staleness)
    const isConnectedRef = useRef(isConnected);
    const socketConnectedRef = useRef(socketConnected);
    const isVideoOnRef = useRef(false);
    const isModularModeRef = useRef(false);
    const elementPositionsRef = useRef(elementPositions);
    const activeDragElementRef = useRef(null);
    const lastActiveDragElementRef = useRef(null);
    const lastCursorPosRef = useRef({ x: 0, y: 0 });
    const lastWristPosRef = useRef({ x: 0, y: 0 }); // For stable fist gesture tracking

    // Smoothing and Snapping Refs
    const smoothedCursorPosRef = useRef({ x: 0, y: 0 });
    const snapStateRef = useRef({ isSnapped: false, element: null, snapPos: { x: 0, y: 0 } });

    // Mouse Drag Refs
    const dragOffsetRef = useRef({ x: 0, y: 0 });
    const isDraggingRef = useRef(false);

    // Update refs when state changes
    useEffect(() => {
        isModularModeRef.current = isModularMode;
        elementPositionsRef.current = elementPositions;
        isHandTrackingEnabledRef.current = isHandTrackingEnabled;
        cursorSensitivityRef.current = cursorSensitivity;
        isCameraFlippedRef.current = isCameraFlipped;
        faceAuthEnabledRef.current = faceAuthEnabled;
        micDevicesRef.current = micDevices;
        selectedMicIdRef.current = selectedMicId;
        console.log("[Ref Sync] Camera flipped ref updated to:", isCameraFlipped);
    }, [isModularMode, elementPositions, isHandTrackingEnabled, cursorSensitivity, isCameraFlipped, faceAuthEnabled, micDevices, selectedMicId]);

    // Live Clock Update
    useEffect(() => {
        const timer = setInterval(() => {
            setCurrentTime(new Date());
        }, 1000);
        return () => clearInterval(timer);
    }, []);

    const setDashboardSectionLoading = useCallback((key, value) => {
        setDashboardLoading(prev => ({ ...prev, [key]: value }));
    }, []);

    const setDashboardSectionError = useCallback((key, value) => {
        setDashboardError(prev => ({ ...prev, [key]: value || null }));
    }, []);

    const responseError = (response, fallback) => response?.error || response?.data?.error || response?.data?.summary || fallback;

    const refreshBackendStatus = useCallback(async () => {
        setDashboardSectionLoading('backend', true);
        const response = await getBackendStatus();
        setBackendStatus(response);
        setDashboardSectionError('backend', response.ok ? null : response.error);
        setDashboardSectionLoading('backend', false);
        return response;
    }, [setDashboardSectionError, setDashboardSectionLoading]);

    const refreshOpenClawStatus = useCallback(async () => {
        setDashboardSectionLoading('openclaw', true);
        const response = await getOpenClawStatus();
        setOpenClawStatus(response);
        setDashboardSectionError('openclaw', response.success ? null : responseError(response, 'OpenClaw no disponible'));
        setDashboardSectionLoading('openclaw', false);
        return response;
    }, [setDashboardSectionError, setDashboardSectionLoading]);

    const refreshCalendarEvents = useCallback(async () => {
        setDashboardSectionLoading('calendar', true);
        const response = await listCalendarEvents(20);
        if (response.success) {
            const events = extractCalendarItems(response)
                .map(normalizeCalendarEvent)
                .sort((a, b) => String(a.start || '').localeCompare(String(b.start || '')));
            setCalendarEvents(events);
            setDashboardSectionError('calendar', null);
        } else {
            setCalendarEvents([]);
            setDashboardSectionError('calendar', responseError(response, 'Google Calendar no disponible'));
        }
        setDashboardSectionLoading('calendar', false);
        return response;
    }, [setDashboardSectionError, setDashboardSectionLoading]);

    const refreshPendingActions = useCallback(async () => {
        setDashboardSectionLoading('pending', true);
        const response = await getPendingActions();
        if (response.ok) {
            setPendingActions(normalizePendingActions(response));
            setDashboardSectionError('pending', null);
        } else {
            setPendingActions([]);
            setDashboardSectionError('pending', response.error);
        }
        setDashboardSectionLoading('pending', false);
        return response;
    }, [setDashboardSectionError, setDashboardSectionLoading]);

    const refreshOpenClawEvents = useCallback(async () => {
        setDashboardSectionLoading('activity', true);
        const response = await getOpenClawEvents(10);
        if (response.ok && response.success) {
            setOpenClawEvents(normalizeOpenClawEvents(response));
            setDashboardSectionError('activity', null);
        } else {
            setOpenClawEvents([]);
            setDashboardSectionError('activity', responseError(response, 'Actividad no disponible'));
        }
        setDashboardSectionLoading('activity', false);
        return response;
    }, [setDashboardSectionError, setDashboardSectionLoading]);

    const refreshProjects = useCallback(async () => {
        setDashboardSectionLoading('projects', true);
        const response = await getProjects();
        if (response.ok && response.success) {
            const body = response.data || {};
            setProjects(Array.isArray(body.projects) ? body.projects : []);
            if (body.current_project) {
                setCurrentProject(body.current_project);
            }
            setDashboardSectionError('projects', null);
        } else {
            setProjects([]);
            setDashboardSectionError('projects', responseError(response, 'Proyectos no disponibles'));
        }
        setDashboardSectionLoading('projects', false);
        return response;
    }, [setDashboardSectionError, setDashboardSectionLoading]);

    const loadProjectTree = useCallback(async (projectName) => {
        const name = String(projectName || '').trim();
        if (!name) {
            setProjectTree(null);
            setProjectTreeError(null);
            return null;
        }

        setProjectTreeLoading(true);
        setProjectTreeError(null);
        const response = await getProjectTree(name);
        if (response.ok && response.success) {
            setProjectTree(response.data || null);
        } else {
            setProjectTree(null);
            setProjectTreeError(responseError(response, 'No se pudo leer el proyecto'));
        }
        setProjectTreeLoading(false);
        return response;
    }, []);

    const refreshIntegrationStatuses = useCallback(async () => {
        setDashboardSectionLoading('integrations', true);
        const [backendRes, openClawRes, calendarRes, linkedinRes] = await Promise.all([
            getBackendStatus(),
            getOpenClawStatus(),
            listCalendarEvents(1),
            prepareLinkedInPost('Comprobación de estado de Jarvis. No publicar.'),
        ]);

        setBackendStatus(backendRes);
        setOpenClawStatus(openClawRes);

        const linkedinConfigured = Boolean(
            linkedinRes?.data?.data?.raw?.configured ||
            linkedinRes?.data?.data?.raw?.json?.configured ||
            linkedinRes?.data?.data?.raw?.json?.raw?.configured ||
            linkedinRes?.data?.raw?.configured ||
            linkedinRes?.data?.raw?.json?.configured ||
            linkedinRes?.data?.raw?.json?.raw?.configured ||
            linkedinRes?.data?.raw?.raw?.configured
        );

        setIntegrationStatuses([
            {
                name: 'OpenClaw',
                shortName: 'OC',
                state: openClawRes.success ? 'connected' : 'error',
                meta: openClawRes.success ? 'OK' : 'Offline',
                shortStatus: openClawRes.success ? 'OK' : 'Offline',
                tone: openClawRes.success ? 'cyan' : '',
            },
            {
                name: 'Google Calendar',
                shortName: '31',
                state: calendarRes.success ? 'connected' : 'error',
                meta: calendarRes.success ? 'Disponible' : 'No configurado',
                shortStatus: calendarRes.success ? 'OK' : 'No config.',
                tone: calendarRes.success ? 'green' : '',
            },
            {
                name: 'LinkedIn',
                shortName: 'in',
                state: linkedinRes.success && linkedinConfigured ? 'connected' : (linkedinRes.success ? 'unknown' : 'error'),
                meta: linkedinRes.success
                    ? (linkedinConfigured ? 'Configurado' : 'No confirmado')
                    : 'No configurado',
                shortStatus: linkedinRes.success && linkedinConfigured ? 'OK' : 'No config.',
                tone: linkedinRes.success && linkedinConfigured ? 'cyan' : '',
            },
            {
                name: 'WhatsApp',
                shortName: 'WA',
                state: openClawRes.success ? 'connected' : 'error',
                meta: openClawRes.success ? 'OK' : 'Offline',
                shortStatus: openClawRes.success ? 'OK' : 'Offline',
                tone: openClawRes.success ? 'green' : '',
            },
        ]);
        setDashboardSectionLoading('integrations', false);
    }, [setDashboardSectionLoading]);

    useEffect(() => {
        refreshBackendStatus();
        refreshOpenClawStatus();
        refreshCalendarEvents();
        refreshPendingActions();
        refreshOpenClawEvents();
        refreshIntegrationStatuses();
        refreshProjects();

        const backendTimer = setInterval(() => {
            refreshBackendStatus();
            refreshOpenClawStatus();
        }, 30000);
        const calendarTimer = setInterval(refreshCalendarEvents, 60000);
        const pendingTimer = setInterval(refreshPendingActions, 12000);
        const activityTimer = setInterval(refreshOpenClawEvents, 12000);
        const integrationsTimer = setInterval(refreshIntegrationStatuses, 60000);
        const projectsTimer = setInterval(refreshProjects, 30000);

        return () => {
            clearInterval(backendTimer);
            clearInterval(calendarTimer);
            clearInterval(pendingTimer);
            clearInterval(activityTimer);
            clearInterval(integrationsTimer);
            clearInterval(projectsTimer);
        };
    }, [
        refreshBackendStatus,
        refreshCalendarEvents,
        refreshIntegrationStatuses,
        refreshOpenClawEvents,
        refreshOpenClawStatus,
        refreshPendingActions,
        refreshProjects,
    ]);

    // Centering Logic (Startup & Resize)
    useEffect(() => {
        const centerElements = () => {
            const width = window.innerWidth;
            const height = window.innerHeight;

            // Calculate available vertical space
            // Tools is fixed at bottom ~100px space
            const toolsY = height - 100;
            // ToolsModule uses translate(-50%, -50%). So its Center Y.
            // Let's reserve bottom 140px for tools to be safe and float it nicely.
            const toolsCenterY = height - 100;

            const gap = 20;

            // Chat: Anchor is Top-Center (translate(-50%, 0)).
            // We want Chat Bottom to be above Tools Top.
            // Tools Top = toolsCenterY - (ToolsHeight/2) approx 40 = height - 140;
            const chatBottomLimit = height - 140;

            // Dynamic Height Calculation to fit screen
            // Standard Heights
            let vizH = 400;
            let chatH = 250;
            const topBarHeight = 60;

            // Total needed: TopBar + Viz + Gap + Chat + Gap + Tools (140 reserved)
            const totalNeeded = topBarHeight + vizH + gap + chatH + gap + 140;

            if (height < totalNeeded) {
                // Scale down
                const available = height - topBarHeight - 140 - (gap * 2);
                // Allocate 60% to Viz, 40% to Chat
                vizH = available * 0.6;
                chatH = available * 0.4;
            }

            // Positions
            // Visualizer (Center Anchored)
            // Top of Viz = TopBarHeight. Center = TopBarHeight + VizH/2
            const vizY = topBarHeight + (vizH / 2); // Removed buffer

            // Chat (Top Anchored)
            // Top of Chat = TopBarHeight + VizH + Gap
            const chatY = topBarHeight + vizH + gap;

            setElementSizes(prev => ({
                ...prev,
                visualizer: { w: Math.min(600, width * 0.8), h: vizH },
                chat: { w: Math.min(600, width * 0.9), h: chatH }
            }));

            setElementPositions(prev => ({
                ...prev,
                visualizer: {
                    x: width / 2,
                    y: vizY
                },
                chat: {
                    x: width / 2,
                    y: chatY
                },
                tools: {
                    x: width / 2,
                    y: toolsCenterY
                }
            }));
        };

        // Center on mount
        centerElements();

        // Center on resize
        window.addEventListener('resize', centerElements);
        return () => window.removeEventListener('resize', centerElements);
    }, []);

    // Utility: Clamp position to viewport so component stays fully visible
    const clampToViewport = (pos, size) => {
        const margin = 10;
        const topBarHeight = 60;
        const width = window.innerWidth;
        const height = window.innerHeight;

        return {
            x: Math.max(size.w / 2 + margin, Math.min(width - size.w / 2 - margin, pos.x)),
            y: Math.max(size.h / 2 + margin + topBarHeight, Math.min(height - size.h / 2 - margin, pos.y))
        };
    };

    // Utility: Get z-index for an element based on stacking order
    const getZIndex = (id) => {
        const baseZ = 30; // Above background elements
        const index = zIndexOrder.indexOf(id);
        return baseZ + (index >= 0 ? index : 0);
    };

    // Utility: Bring element to front (highest z-index)
    const bringToFront = (id) => {
        setZIndexOrder(prev => {
            const filtered = prev.filter(el => el !== id);
            return [...filtered, id]; // Move to end = highest z-index
        });
    };

    // Ref to track if model has been auto-connected (prevents duplicate connections)
    const hasAutoConnectedRef = useRef(false);

    useEffect(() => {
        isConnectedRef.current = isConnected;
    }, [isConnected]);

    useEffect(() => {
        socketConnectedRef.current = socketConnected;
    }, [socketConnected]);

    const requestStartAudio = (muted = isMuted) => {
        const devices = micDevicesRef.current;
        const selectedId = selectedMicIdRef.current;
        const index = devices.findIndex(d => d.deviceId === selectedId);
        const queryDevice = devices.find(d => d.deviceId === selectedId);
        const deviceName = queryDevice ? queryDevice.label : null;

        console.log("Starting model with device:", deviceName, "Index:", index);
        setStatus('Connecting...');
        socket.emit('start_audio', {
            device_index: index >= 0 ? index : null,
            device_name: deviceName,
            muted
        });
    };

    // Auto-Connect Model on Start (Only after Auth and devices loaded)
    useEffect(() => {
        // Only auto-connect once: when socket connected, authenticated, and devices loaded
        if (isConnected && isAuthenticated && socketConnected && micDevices.length > 0 && !hasAutoConnectedRef.current) {
            hasAutoConnectedRef.current = true;

            // Trigger Kasa and Printer Discovery
            socket.emit('discover_kasa');
            socket.emit('discover_printers');

            // Connect to model with small delay for socket stability
            const timer = setTimeout(() => {
                requestStartAudio(isMuted);
            }, 500);
        }
    }, [isConnected, isAuthenticated, socketConnected, micDevices, selectedMicId, isMuted]);

    useEffect(() => {
        // Socket IO Setup
        socket.on('connect', () => {
            setStatus('Connected');
            setSocketConnected(true);
            socket.emit('get_settings');
        });
        socket.on('disconnect', () => {
            setStatus('Disconnected');
            setSocketConnected(false);
        });
        socket.on('status', (data) => {
            addMessage('System', data.msg);
            // Update status bar based on backend messages
            if (data.msg === 'J.A.R.V.I.S Started') {
                setStatus('Model Connected');
            } else if (data.msg === 'J.A.R.V.I.S Stopped') {
                setStatus('Connected');
            }
        });
        socket.on('audio_data', (data) => {
            setAiAudioData(data.data);
        });
        socket.on('auth_status', (data) => {
            console.log("Auth Status:", data);
            setIsAuthenticated(data.authenticated);
            if (data.authenticated) {
                if (pendingPowerOnRef.current) {
                    pendingPowerOnRef.current = false;
                    hasAutoConnectedRef.current = true;
                    setIsConnected(true);
                    setIsMuted(false);
                    requestStartAudio(false);
                }
                if (!faceAuthEnabledRef.current) {
                    setIsLockScreenVisible(false);
                }
            } else {
                if (isVideoOnRef.current) {
                    stopVideo();
                }
                setIsLockScreenVisible(true);
            }
        });

        socket.on('settings', (settings) => {
            console.log("[Settings] Received:", settings);
            if (settings && typeof settings.face_auth_enabled !== 'undefined') {
                setFaceAuthEnabled(settings.face_auth_enabled);
                localStorage.setItem('face_auth_enabled', settings.face_auth_enabled);
            }
            if (typeof settings.camera_flipped !== 'undefined') {
                console.log("[Settings] Camera flip set to:", settings.camera_flipped);
                setIsCameraFlipped(settings.camera_flipped);
            }
        });
        socket.on('error', (data) => {
            console.error("Socket Error:", data);
            if (data.msg === 'Authentication Required') {
                setStatus('Authentication Required');
                return;
            }
            addMessage('System', `Error: ${data.msg}`);
        });
        socket.on('cad_data', (data) => {
            console.log("Received CAD Data:", data);
            setCadData(data);
            setCadThoughts(''); // Clear thoughts when generation complete
            setShowCadWindow(true); // Open window when data arrives
            // Auto-show the window if it's hidden, clamped to viewport
            if (!elementPositions.cad) {
                const size = { w: 400, h: 400 };
                const clamped = clampToViewport({ x: window.innerWidth / 2 + 150, y: window.innerHeight / 2 }, size);
                setElementPositions(prev => ({
                    ...prev,
                    cad: clamped
                }));
            }
        });
        socket.on('cad_status', (data) => {
            console.log("Received CAD Status:", data);
            // Extract retry info from extended payload
            if (data.attempt) {
                setCadRetryInfo({
                    attempt: data.attempt,
                    maxAttempts: data.max_attempts || 3,
                    error: data.error
                });
            }
            if (data.status === 'generating' || data.status === 'retrying') {
                setCadData({ format: 'loading' });
                setShowCadWindow(true);
                if (data.status === 'generating' && data.attempt === 1) {
                    setCadThoughts(''); // Clear previous thoughts for new generation
                }
                // Auto-show the window, clamped to viewport
                if (!elementPositions.cad) {
                    const size = { w: 400, h: 400 };
                    const clamped = clampToViewport({ x: window.innerWidth / 2 + 150, y: window.innerHeight / 2 }, size);
                    setElementPositions(prev => ({
                        ...prev,
                        cad: clamped
                    }));
                }
            } else if (data.status === 'failed') {
                // Keep loading state but show error
                setCadData({ format: 'loading' });
            }
        });
        socket.on('cad_thought', (data) => {
            // Append streaming thought text
            setCadThoughts(prev => prev + data.text);
        });
        socket.on('browser_frame', (data) => {
            setBrowserData(prev => ({
                image: data.image,
                logs: [...prev.logs, data.log].filter(l => l).slice(-50) // Keep last 50 logs
            }));
            setShowBrowserWindow(true);
            // Auto-show browser window if hidden, clamped to viewport
            if (!elementPositions.browser) {
                const size = { w: 550, h: 380 };
                const clamped = clampToViewport({ x: window.innerWidth / 2 - 200, y: window.innerHeight / 2 }, size);
                setElementPositions(prev => ({
                    ...prev,
                    browser: clamped
                }));
            }
        });

        // Handle streaming transcription
        socket.on('transcription', (data) => {
            setMessages(prev => {
                const lastMsg = prev[prev.length - 1];
                const shouldAppend = data.append !== false;

                // If the last message is from the same sender, append the chunk
                if (shouldAppend && lastMsg && lastMsg.sender === data.sender) {
                    // Create a NEW object instead of mutating (prevents React StrictMode duplication)
                    return [
                        ...prev.slice(0, -1),
                        {
                            ...lastMsg,
                            text: lastMsg.text + data.text
                        }
                    ];
                } else {
                    // New message block
                    return [...prev, {
                        sender: data.sender,
                        text: data.text,
                        time: new Date().toLocaleTimeString()
                    }];
                }
            });
        });

        // Handle tool confirmation requests
        socket.on('tool_confirmation_request', (data) => {
            console.log("Received Confirmation Request:", data);
            setConfirmationRequest(data);
        });

        // Kasa Devices
        socket.on('kasa_devices', (devices) => {
            console.log("Kasa Devices:", devices);
            setKasaDevices(devices);
        });

        socket.on('kasa_update', (data) => {
            setKasaDevices(prev => prev.map(d => {
                if (d.ip === data.ip) {
                    // Update only fields that are not null/undefined
                    return {
                        ...d,
                        is_on: data.is_on !== null ? data.is_on : d.is_on,
                        brightness: data.brightness !== null ? data.brightness : d.brightness
                    };
                }
                return d;
            }));
        });

        socket.on('project_update', (data) => {
            console.log("Project Update:", data.project);
            setCurrentProject(data.project);
            setProjectTree(null);
            refreshProjects();
            addMessage('System', `Switched to project: ${data.project}`);
        });

        // Track printer count for toolbar display
        socket.on('printer_list', (list) => {
            console.log('[PRINTERS] Count:', list.length);
            setPrinterCount(list.length);
        });

        socket.on('simulation_status', (state) => {
            setSimulationState(state || { simulation_mode: false, kasa_simulation: false, printer_simulation: false });
            if (state?.simulation_mode) {
                setShowSimulationDashboard(true);
            }
        });

        // Slicing progress for top toolbar
        socket.on('slicing_progress', (data) => {
            console.log('[SLICING] Progress:', data);
            setSlicingStatus({
                active: data.percent < 100,
                percent: data.percent,
                message: data.message
            });
        });

        // Print status for top toolbar - track active prints
        socket.on('print_status_update', (data) => {
            console.log('[PRINT STATUS]', data);
            // Only show in toolbar if actively printing
            if (data.state && data.state.toLowerCase().includes('print')) {
                setActivePrintStatus({
                    printer: data.printer,
                    progress_percent: data.progress_percent,
                    time_elapsed: data.time_elapsed,
                    state: data.state
                });
            } else if (data.state && (data.state.toLowerCase() === 'idle' || data.state.toLowerCase() === 'standby' || data.state.toLowerCase() === 'complete')) {
                // Clear if print finished or idle
                setActivePrintStatus(null);
            }
        });



        // Get All Media Devices (Microphones, Speakers, Webcams)
        navigator.mediaDevices.enumerateDevices().then(devs => {
            const audioInputs = devs.filter(d => d.kind === 'audioinput');
            const audioOutputs = devs.filter(d => d.kind === 'audiooutput');
            const videoInputs = devs.filter(d => d.kind === 'videoinput');

            setMicDevices(audioInputs);
            setSpeakerDevices(audioOutputs);
            setWebcamDevices(videoInputs);

            // Restore saved microphone or use first available
            const savedMicId = localStorage.getItem('selectedMicId');
            if (savedMicId && audioInputs.some(d => d.deviceId === savedMicId)) {
                setSelectedMicId(savedMicId);
            } else if (audioInputs.length > 0) {
                setSelectedMicId(audioInputs[0].deviceId);
            }

            // Restore saved speaker or use first available
            const savedSpeakerId = localStorage.getItem('selectedSpeakerId');
            if (savedSpeakerId && audioOutputs.some(d => d.deviceId === savedSpeakerId)) {
                setSelectedSpeakerId(savedSpeakerId);
            } else if (audioOutputs.length > 0) {
                setSelectedSpeakerId(audioOutputs[0].deviceId);
            }

            // Restore saved webcam or use first available
            const savedWebcamId = localStorage.getItem('selectedWebcamId');
            if (savedWebcamId && videoInputs.some(d => d.deviceId === savedWebcamId)) {
                setSelectedWebcamId(savedWebcamId);
            } else if (videoInputs.length > 0) {
                setSelectedWebcamId(videoInputs[0].deviceId);
            }
        });

        // Initialize Hand Landmarker
        const initHandLandmarker = async () => {
            try {
                console.log("Initializing HandLandmarker...");

                // 1. Verify Model File
                console.log("Fetching model file...");
                const response = await fetch('/hand_landmarker.task');
                if (!response.ok) {
                    throw new Error(`Failed to fetch model: ${response.status} ${response.statusText}`);
                }
                console.log("Model file found:", response.headers.get('content-type'), response.headers.get('content-length'));

                // 2. Initialize Vision
                console.log("Initializing FilesetResolver...");
                const vision = await FilesetResolver.forVisionTasks(
                    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0/wasm"
                );
                console.log("FilesetResolver initialized.");

                // 3. Create Landmarker
                console.log("Creating HandLandmarker (GPU)...");
                handLandmarkerRef.current = await HandLandmarker.createFromOptions(vision, {
                    baseOptions: {
                        modelAssetPath: `/hand_landmarker.task`,
                        delegate: "GPU" // Enable GPU acceleration
                    },
                    runningMode: "VIDEO",
                    numHands: 1
                });
                console.log("HandLandmarker initialized successfully!");
                addMessage('System', 'Hand Tracking Ready');

            } catch (error) {
                console.error("Failed to initialize HandLandmarker:", error);
                addMessage('System', `Hand Tracking Error: ${error.message}`);
            }
        };
        initHandLandmarker();

        return () => {
            socket.off('connect');
            socket.off('disconnect');
            socket.off('status');
            socket.off('audio_data');
            socket.off('cad_data');
            socket.off('cad_thought');
            socket.off('cad_status');
            socket.off('browser_frame');
            socket.off('transcription');
            socket.off('tool_confirmation_request');
            socket.off('kasa_devices');
            socket.off('project_update');
            socket.off('printer_list');
            socket.off('simulation_status');
            socket.off('slicing_progress');
            socket.off('print_status_update');
            socket.off('error');

            stopMicVisualizer();
            stopVideo();
        };
    }, []);

    // Initial check in case we are already connected (fix race condition)
    useEffect(() => {
        if (socket.connected) {
            setStatus('Connected');
            socket.emit('get_settings');
        }
    }, []);

    // Persist device selections to localStorage when they change
    useEffect(() => {
        if (selectedMicId) {
            localStorage.setItem('selectedMicId', selectedMicId);
            console.log('[Settings] Saved microphone:', selectedMicId);
        }
    }, [selectedMicId]);

    useEffect(() => {
        if (selectedSpeakerId) {
            localStorage.setItem('selectedSpeakerId', selectedSpeakerId);
            console.log('[Settings] Saved speaker:', selectedSpeakerId);
        }
    }, [selectedSpeakerId]);

    useEffect(() => {
        if (selectedWebcamId) {
            localStorage.setItem('selectedWebcamId', selectedWebcamId);
            console.log('[Settings] Saved webcam:', selectedWebcamId);
        }
    }, [selectedWebcamId]);

    // Start/Stop Mic Visualizer
    useEffect(() => {
        if (selectedMicId && isConnected && !isMuted) {
            startMicVisualizer(selectedMicId);
        } else {
            stopMicVisualizer();
            setMicAudioData(new Array(32).fill(0));
        }
    }, [selectedMicId, isConnected, isMuted]);

    const startMicVisualizer = async (deviceId) => {
        stopMicVisualizer();
        let stream = null;
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: { deviceId: { exact: deviceId } }
            });
            micStreamRef.current = stream;

            audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)();
            analyserRef.current = audioContextRef.current.createAnalyser();
            analyserRef.current.fftSize = 64;

            sourceRef.current = audioContextRef.current.createMediaStreamSource(stream);
            sourceRef.current.connect(analyserRef.current);

            const updateMicData = () => {
                if (!analyserRef.current) return;
                const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
                analyserRef.current.getByteFrequencyData(dataArray);
                setMicAudioData(Array.from(dataArray));
                animationFrameRef.current = requestAnimationFrame(updateMicData);
            };

            updateMicData();
        } catch (err) {
            if (stream) {
                stream.getTracks().forEach(track => track.stop());
                if (micStreamRef.current === stream) {
                    micStreamRef.current = null;
                }
            }
            console.error("Error accessing microphone:", err);
        }
    };

    const stopMicVisualizer = () => {
        if (animationFrameRef.current) {
            cancelAnimationFrame(animationFrameRef.current);
            animationFrameRef.current = null;
        }

        if (sourceRef.current) {
            try {
                sourceRef.current.disconnect();
            } catch (err) {
                console.warn("Error disconnecting microphone visualizer source:", err);
            }
            sourceRef.current = null;
        }

        analyserRef.current = null;

        if (audioContextRef.current) {
            const context = audioContextRef.current;
            audioContextRef.current = null;
            if (context.state !== 'closed') {
                context.close().catch(err => {
                    console.warn("Error closing microphone audio context:", err);
                });
            }
        }

        if (micStreamRef.current) {
            micStreamRef.current.getTracks().forEach(track => track.stop());
            micStreamRef.current = null;
        }
    };

    const startVideo = async () => {
        try {
            // Request 1080p resolution with selected webcam
            const constraints = {
                video: {
                    width: { ideal: 1920 },
                    height: { ideal: 1080 },
                    aspectRatio: 16 / 9
                }
            };

            // Use selected webcam if available
            if (selectedWebcamId) {
                constraints.video.deviceId = { exact: selectedWebcamId };
            }

            const stream = await navigator.mediaDevices.getUserMedia(constraints);
            if (videoRef.current) {
                videoRef.current.srcObject = stream;
                videoRef.current.play();
            }

            // Initialize the transmission canvas
            if (!transmissionCanvasRef.current) {
                transmissionCanvasRef.current = document.createElement('canvas');
                transmissionCanvasRef.current.width = 640;
                transmissionCanvasRef.current.height = 360;
                console.log("Initialized transmission canvas (640x360)");
            }

            setIsVideoOn(true);
            isVideoOnRef.current = true; // Update ref for loop

            console.log("Starting video loop with webcam:", selectedWebcamId || "default");
            requestAnimationFrame(predictWebcam);

        } catch (err) {
            console.error("Error accessing camera:", err);
            addMessage('System', 'Error accessing camera');
        }
    };

    const predictWebcam = () => {
        // Use ref for checking state to avoid closure staleness
        if (!videoRef.current || !canvasRef.current || !isVideoOnRef.current) {
            return;
        }

        // Check if video has valid dimensions to prevent MediaPipe crash
        if (videoRef.current.readyState < 2 || videoRef.current.videoWidth === 0 || videoRef.current.videoHeight === 0) {
            requestAnimationFrame(predictWebcam);
            return;
        }

        // 1. Draw Video to Local Display Canvas (Native Resolution)
        const ctx = canvasRef.current.getContext('2d');

        // Ensure canvas matches video dimensions
        if (canvasRef.current.width !== videoRef.current.videoWidth || canvasRef.current.height !== videoRef.current.videoHeight) {
            canvasRef.current.width = videoRef.current.videoWidth;
            canvasRef.current.height = videoRef.current.videoHeight;
        }

        ctx.drawImage(videoRef.current, 0, 0, canvasRef.current.width, canvasRef.current.height);

        // 2. Send Frame to Backend (Throttled & Resized)
        // Only send if the app power and socket are both connected. Use refs so
        // the long-running camera loop does not keep a stale React state value.
        if (isConnectedRef.current && socketConnectedRef.current) {
            // Simple throttle: every 5th frame roughly
            if (frameCountRef.current % 5 === 0) {

                // Use dedicated transmission canvas for resizing
                const transCanvas = transmissionCanvasRef.current;
                if (transCanvas) {
                    const transCtx = transCanvas.getContext('2d');
                    // Draw resized image
                    transCtx.drawImage(videoRef.current, 0, 0, transCanvas.width, transCanvas.height);

                    // Convert resized image to blob
                    transCanvas.toBlob((blob) => {
                        if (blob) {
                            socket.emit('video_frame', { image: blob });
                            sentVideoFramesRef.current++;
                            if (sentVideoFramesRef.current === 1 || sentVideoFramesRef.current % 60 === 0) {
                                console.log(`[Vision] Sent webcam frame #${sentVideoFramesRef.current} (${blob.size} bytes)`);
                            }
                        }
                    }, 'image/jpeg', 0.6); // Slightly higher compression for speed
                }
            }
        }


        // 3. Hand Tracking
        let startTimeMs = performance.now();
        // Use Ref for toggle check
        if (isHandTrackingEnabledRef.current && handLandmarkerRef.current && videoRef.current.currentTime !== lastVideoTimeRef.current) {
            lastVideoTimeRef.current = videoRef.current.currentTime;
            const results = handLandmarkerRef.current.detectForVideo(videoRef.current, startTimeMs);

            // Log every 100 frames to confirm loop is running
            if (frameCountRef.current % 100 === 0) {
                console.log("Tracking loop running... Last result:", results.landmarks.length > 0 ? "Hand Found" : "No Hand");
            }

            if (results.landmarks && results.landmarks.length > 0) {
                const landmarks = results.landmarks[0];

                // Log on first detection
                if (cursorPos.x === 0 && cursorPos.y === 0) {
                    console.log("First hand detection!", landmarks);
                }

                // Index Finger Tip (8)
                const indexTip = landmarks[8];
                // Thumb Tip (4)
                const thumbTip = landmarks[4];

                // Map to Screen Coords with Sensitivity Scaling
                // Sensitivity: Map center 50% of camera to 100% of screen.
                const SENSITIVITY = cursorSensitivityRef.current;

                // Apply camera flip if enabled (horizontal mirror)
                const rawX = isCameraFlippedRef.current ? (1 - indexTip.x) : indexTip.x;

                // 1. Normalize and Scale X
                let normX = (rawX - 0.5) * SENSITIVITY + 0.5;
                // Clamp to [0, 1]
                normX = Math.max(0, Math.min(1, normX));

                // 2. Normalize and Scale Y
                let normY = (indexTip.y - 0.5) * SENSITIVITY + 0.5;
                normY = Math.max(0, Math.min(1, normY));

                const targetX = normX * window.innerWidth;
                const targetY = normY * window.innerHeight;

                // 1. Smoothing (Lerp)
                // Factor 0.2 = smooth but responsive. Lower = smoother/slower.
                const lerpFactor = 0.2;
                smoothedCursorPosRef.current.x = smoothedCursorPosRef.current.x + (targetX - smoothedCursorPosRef.current.x) * lerpFactor;
                smoothedCursorPosRef.current.y = smoothedCursorPosRef.current.y + (targetY - smoothedCursorPosRef.current.y) * lerpFactor;

                let finalX = smoothedCursorPosRef.current.x;
                let finalY = smoothedCursorPosRef.current.y;

                // 2. Snap-to-Button Logic
                const SNAP_THRESHOLD = 50; // Pixels to snap
                const UNSNAP_THRESHOLD = 100; // Pixels to unsnap (Hysteresis)

                if (snapStateRef.current.isSnapped) {
                    // Check if we should unsnap
                    const dist = Math.sqrt(
                        Math.pow(finalX - snapStateRef.current.snapPos.x, 2) +
                        Math.pow(finalY - snapStateRef.current.snapPos.y, 2)
                    );

                    if (dist > UNSNAP_THRESHOLD) {
                        // REMOVE HIGHLIGHT
                        if (snapStateRef.current.element) {
                            snapStateRef.current.element.classList.remove('snap-highlight');
                            snapStateRef.current.element.style.boxShadow = '';
                            snapStateRef.current.element.style.backgroundColor = '';
                            snapStateRef.current.element.style.borderColor = '';
                        }

                        snapStateRef.current = { isSnapped: false, element: null, snapPos: { x: 0, y: 0 } };
                    } else {
                        // Stay snapped
                        finalX = snapStateRef.current.snapPos.x;
                        finalY = snapStateRef.current.snapPos.y;
                    }
                } else {
                    // Check if we should snap
                    // Find all interactive elements
                    const targets = Array.from(document.querySelectorAll('button, input, select, .draggable'));
                    let closest = null;
                    let minDist = Infinity;

                    for (const el of targets) {
                        const rect = el.getBoundingClientRect();
                        const centerX = rect.left + rect.width / 2;
                        const centerY = rect.top + rect.height / 2;
                        const dist = Math.sqrt(Math.pow(finalX - centerX, 2) + Math.pow(finalY - centerY, 2));

                        if (dist < minDist) {
                            minDist = dist;
                            closest = { el, centerX, centerY };
                        }
                    }

                    if (closest && minDist < SNAP_THRESHOLD) {
                        snapStateRef.current = {
                            isSnapped: true,
                            element: closest.el,
                            snapPos: { x: closest.centerX, y: closest.centerY }
                        };
                        finalX = closest.centerX;
                        finalY = closest.centerY;

                        // SNAP HIGHLIGHT Logic
                        closest.el.classList.add('snap-highlight');
                        // Add some inline style for the glow if class isn't enough (using imperative for speed)
                        closest.el.style.boxShadow = '0 0 20px rgba(34, 211, 238, 0.6)';
                        closest.el.style.backgroundColor = 'rgba(6, 182, 212, 0.2)';
                        closest.el.style.borderColor = 'rgba(34, 211, 238, 1)';
                    }
                }

                // Update Cursor Loop
                setCursorPos({ x: finalX, y: finalY });

                // Trail Logic: Removed per user request

                // Pinch Detection (Distance between Index and Thumb)
                const distance = Math.sqrt(
                    Math.pow(indexTip.x - thumbTip.x, 2) + Math.pow(indexTip.y - thumbTip.y, 2)
                );

                const isPinchNow = distance < 0.05; // Threshold
                if (isPinchNow && !isPinching) {
                    // Click Triggered
                    console.log("Click triggered at", finalX, finalY);

                    // Ripple Effect: Removed per user request

                    const el = document.elementFromPoint(finalX, finalY);
                    if (el) {
                        // Find closest clickable element (button, input, etc.)
                        const clickable = el.closest('button, input, a, [role="button"]');
                        if (clickable && typeof clickable.click === 'function') {
                            clickable.click();
                        } else if (typeof el.click === 'function') {
                            el.click();
                        }
                    }
                }
                setIsPinching(isPinchNow);

                // Fist Detection for Gesture-Based Dragging (Popup Windows Only)
                // Detects if all fingers are folded (tips closer to wrist than MCPs)
                const isFingerFolded = (tipIdx, mcpIdx) => {
                    const tip = landmarks[tipIdx];
                    const mcp = landmarks[mcpIdx];
                    const wrist = landmarks[0];
                    const distTip = Math.sqrt(Math.pow(tip.x - wrist.x, 2) + Math.pow(tip.y - wrist.y, 2));
                    const distMcp = Math.sqrt(Math.pow(mcp.x - wrist.x, 2) + Math.pow(mcp.y - wrist.y, 2));
                    return distTip < distMcp; // Folded if tip is closer
                };

                const isFist = isFingerFolded(8, 5) && isFingerFolded(12, 9) && isFingerFolded(16, 13) && isFingerFolded(20, 17);

                // Get wrist position in screen coordinates (stable reference for fist gesture)
                const wrist = landmarks[0];
                const wristRawX = isCameraFlippedRef.current ? (1 - wrist.x) : wrist.x;
                const wristNormX = Math.max(0, Math.min(1, (wristRawX - 0.5) * SENSITIVITY + 0.5));
                const wristNormY = Math.max(0, Math.min(1, (wrist.y - 0.5) * SENSITIVITY + 0.5));
                const wristScreenX = wristNormX * window.innerWidth;
                const wristScreenY = wristNormY * window.innerHeight;

                if (isFist) {
                    if (!activeDragElementRef.current) {
                        // Only check popup windows (draggable elements)
                        const draggableElements = ['cad', 'browser', 'kasa', 'printer'];

                        for (const id of draggableElements) {
                            const el = document.getElementById(id);
                            if (el) {
                                const rect = el.getBoundingClientRect();
                                // Use the cursor position from before fist was made for hit detection
                                if (finalX >= rect.left && finalX <= rect.right && finalY >= rect.top && finalY <= rect.bottom) {
                                    activeDragElementRef.current = id;
                                    bringToFront(id);
                                    // Lock the initial wrist position when starting drag
                                    lastWristPosRef.current = { x: wristScreenX, y: wristScreenY };
                                    break;
                                }
                            }
                        }
                    }

                    if (activeDragElementRef.current) {
                        // Use WRIST movement (not index finger) for stable dragging
                        // The wrist doesn't move when making a fist
                        const dx = wristScreenX - lastWristPosRef.current.x;
                        const dy = wristScreenY - lastWristPosRef.current.y;

                        // Update position only if there's actual movement
                        if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
                            updateElementPosition(activeDragElementRef.current, dx, dy);
                        }

                        // Update last wrist position
                        lastWristPosRef.current = { x: wristScreenX, y: wristScreenY };
                    }
                } else {
                    activeDragElementRef.current = null;
                }

                // Sync state for visual feedback (only on change)
                if (activeDragElementRef.current !== lastActiveDragElementRef.current) {
                    setActiveDragElement(activeDragElementRef.current);
                    lastActiveDragElementRef.current = activeDragElementRef.current;
                }

                lastCursorPosRef.current = { x: finalX, y: finalY };

                // Draw Skeleton
                drawSkeleton(ctx, landmarks);
            }

        }

        // 4. FPS Calculation
        const now = performance.now();
        frameCountRef.current++;
        if (now - lastFrameTimeRef.current >= 1000) {
            setFps(frameCountRef.current);
            frameCountRef.current = 0;
            lastFrameTimeRef.current = now;
        }

        if (isVideoOnRef.current) {
            requestAnimationFrame(predictWebcam);
        }
    };

    const drawSkeleton = (ctx, landmarks) => {
        ctx.strokeStyle = '#00FFFF';
        ctx.lineWidth = 2;

        // Connections
        const connections = HandLandmarker.HAND_CONNECTIONS;
        for (const connection of connections) {
            const start = landmarks[connection.start];
            const end = landmarks[connection.end];
            ctx.beginPath();
            ctx.moveTo(start.x * canvasRef.current.width, start.y * canvasRef.current.height);
            ctx.lineTo(end.x * canvasRef.current.width, end.y * canvasRef.current.height);
            ctx.stroke();
        }
    };

    const stopVideo = () => {
        if (videoRef.current && videoRef.current.srcObject) {
            videoRef.current.srcObject.getTracks().forEach(track => track.stop());
            videoRef.current.srcObject = null;
        }
        if (socket.connected) {
            socket.emit('video_stopped');
        }
        sentVideoFramesRef.current = 0;
        setIsVideoOn(false);
        isVideoOnRef.current = false; // Update ref
        setFps(0);
    };

    const captureCurrentVideoFrame = () => {
        return new Promise((resolve) => {
            if (!isVideoOnRef.current || !videoRef.current || videoRef.current.readyState < 2) {
                resolve(null);
                return;
            }

            let transCanvas = transmissionCanvasRef.current;
            if (!transCanvas) {
                transCanvas = document.createElement('canvas');
                transCanvas.width = 640;
                transCanvas.height = 360;
                transmissionCanvasRef.current = transCanvas;
            }

            const transCtx = transCanvas.getContext('2d');
            transCtx.drawImage(videoRef.current, 0, 0, transCanvas.width, transCanvas.height);
            transCanvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.72);
        });
    };

    const toggleVideo = () => {
        if (isVideoOn) {
            stopVideo();
        } else {
            startVideo();
        }
    };

    const addMessage = (sender, text) => {
        setMessages(prev => [...prev, { sender, text, time: new Date().toLocaleTimeString() }]);
    };

    const togglePower = () => {
        if (isConnected) {
            pendingPowerOnRef.current = false;
            socket.emit('stop_audio');
            stopMicVisualizer();
            setMicAudioData(new Array(32).fill(0));
            setIsConnected(false);
            setIsMuted(true);
            if (faceAuthEnabledRef.current) {
                setIsAuthenticated(false);
                setIsLockScreenVisible(false);
            }
        } else {
            if (faceAuthEnabledRef.current && !isAuthenticated) {
                pendingPowerOnRef.current = true;
                requestStartAudio(false);
                return;
            }

            hasAutoConnectedRef.current = true;
            requestStartAudio(false);
            setIsConnected(true);
            setIsMuted(false); // Start unmuted
        }
    };

    const toggleMute = () => {
        if (!isConnected) return; // Can't mute if not connected

        if (isMuted) {
            socket.emit('resume_audio');
            setIsMuted(false);
        } else {
            socket.emit('pause_audio');
            stopMicVisualizer();
            setMicAudioData(new Array(32).fill(0));
            setIsMuted(true);
        }
    };

    const submitCommand = async (overrideText) => {
        const text = (typeof overrideText === 'string' ? overrideText : inputValue).trim();
        if (!text) return;

        if (typeof overrideText !== 'string') {
            setInputValue('');
        }
        addMessage('You', text);

        const payload = { text };
        const freshFrame = await captureCurrentVideoFrame();
        if (freshFrame) {
            payload.image = freshFrame;
            console.log(`[Vision] Attached fresh frame to text input (${freshFrame.size} bytes)`);
        }

        socket.emit('user_input', payload);
    };

    const handleSend = async (e) => {
        if (e.key === 'Enter') {
            await submitCommand();
        }
    };

    const handleMinimize = () => ipcRenderer.send('window-minimize');
    const handleMaximize = () => ipcRenderer.send('window-maximize');

    // Close Application - memory is now actively saved to project, no prompt needed
    const handleCloseRequest = () => {
        // Emit shutdown signal to backend for graceful shutdown
        // Use volatile emit with timeout fallback to ensure window closes even if server is unresponsive
        const closeWindow = () => ipcRenderer.send('window-close');

        if (socket.connected) {
            console.log('[APP] Sending shutdown signal to backend...');
            socket.emit('shutdown', {}, (ack) => {
                // This callback may not be called if server uses os._exit
                console.log('[APP] Shutdown acknowledged');
                closeWindow();
            });
            // Fallback: close after 500ms if ack doesn't come back
            setTimeout(closeWindow, 500);
        } else {
            // Socket not connected, just close
            closeWindow();
        }
    };

    const handleFileUpload = (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (event) => {
            try {
                const textContent = event.target.result;
                // Just send the text content directly
                if (typeof textContent === 'string' && textContent.length > 0) {
                    socket.emit('upload_memory', { memory: textContent });
                    addMessage('System', 'Uploading memory...');
                } else {
                    addMessage('System', 'Empty or invalid memory file');
                }
            } catch (err) {
                console.error("Error reading file:", err);
                addMessage('System', 'Error reading memory file');
            }
        };
        reader.readAsText(file);
    };

    // handleCancelClose removed - no longer using memory prompt

    const handleConfirmTool = () => {
        if (confirmationRequest) {
            socket.emit('confirm_tool', { id: confirmationRequest.id, confirmed: true });
            setConfirmationRequest(null);
        }
    };

    const handleDenyTool = () => {
        if (confirmationRequest) {
            socket.emit('confirm_tool', { id: confirmationRequest.id, confirmed: false });
            setConfirmationRequest(null);
        }
    };

    // Updated Bounds Checking Logic
    const updateElementPosition = (id, dx, dy) => {
        setElementPositions(prev => {
            const currentPos = prev[id];
            const size = elementSizes[id] || { w: 100, h: 100 }; // Fallback
            let newX = currentPos.x + dx;
            let newY = currentPos.y + dy;

            // Bounds Logic
            // Depends on anchor point.
            // Visualizer, Tools, Cad, Browser, Kasa: translate(-50%, -50%) -> Center Anchor
            // Chat: translate(-50%, 0) -> Top-Center Anchor
            // Video: Top-Left Anchor (default div)

            const width = window.innerWidth;
            const height = window.innerHeight;
            const margin = 0; // Strict bounds

            if (id === 'chat') {
                // Anchor: Top-Center (x is center, y is top)
                // X Bounds: size.w/2 <= x <= width - size.w/2
                newX = Math.max(size.w / 2 + margin, Math.min(width - size.w / 2 - margin, newX));
                // Y Bounds: 0 <= y <= height - size.h
                newY = Math.max(margin, Math.min(height - size.h - margin, newY));

            } else if (id === 'video') {
                // Anchor: Top-Left
                newX = Math.max(margin, Math.min(width - size.w - margin, newX));
                newY = Math.max(margin, Math.min(height - size.h - margin, newY));

            } else {
                // Anchor: Center
                newX = Math.max(size.w / 2 + margin, Math.min(width - size.w / 2 - margin, newX));
                newY = Math.max(size.h / 2 + margin, Math.min(height - size.h / 2 - margin, newY));
            }

            return {
                ...prev,
                [id]: {
                    x: newX,
                    y: newY
                }
            };
        });
    };

    // --- MOUSE DRAG HANDLERS ---
    const handleMouseDown = (e, id) => {
        console.log(`[MouseDrag] MouseDown on ${id}`, { target: e.target.tagName });

        // Fixed elements that should never be draggable (even in modular mode)
        const fixedElements = ['visualizer', 'chat', 'video', 'tools'];
        if (fixedElements.includes(id)) {
            console.log(`[MouseDrag] ${id} is a fixed element, not draggable`);
            return;
        }

        // Bring clicked element to front (z-index)
        bringToFront(id);

        // Prevent dragging if interacting with inputs, buttons, or canvas (for 3D controls)
        const tagName = e.target.tagName.toLowerCase();
        if (tagName === 'input' || tagName === 'button' || tagName === 'textarea' || tagName === 'canvas' || e.target.closest('button')) {
            console.log("[MouseDrag] Interaction blocked by interactive element");
            return;
        }

        // Check if clicking on a drag handle section (data-drag-handle attribute)
        const isDragHandle = e.target.closest('[data-drag-handle]');
        if (!isDragHandle && !isModularModeRef.current) {
            // If not clicking a drag handle and modular mode is off, don't drag
            // This allows popup windows to have dedicated drag areas
            console.log("[MouseDrag] Not a drag handle and modular mode off");
            return;
        }

        const elPos = elementPositions[id];
        if (!elPos) return;

        // Calculate offset based on anchor point
        // Most are Center Anchored (x, y is center)
        // Chat is Top-Center Anchored (x is center, y is top)
        // Video is Top-Left Anchored (x is left, y is top)

        // We want: MousePos = ElementPos + Offset
        // So: Offset = MousePos - ElementPos
        dragOffsetRef.current = {
            x: e.clientX - elPos.x,
            y: e.clientY - elPos.y
        };

        setActiveDragElement(id);
        activeDragElementRef.current = id;
        isDraggingRef.current = true;

        window.addEventListener('mousemove', handleMouseDrag);
        window.addEventListener('mouseup', handleMouseUp);
    };

    const handleMouseDrag = (e) => {
        if (!isDraggingRef.current || !activeDragElementRef.current) return;

        const id = activeDragElementRef.current;
        const currentPos = elementPositionsRef.current[id];
        if (!currentPos) return;

        // Target Position = MousePos - Offset
        // But we want delta for updateElementPosition??
        // actually updateElementPosition takes dx, dy.
        // Let's just set the position directly or calculate delta.
        // Since updateElementPosition has bounds logic, let's use it, but we need delta from PREVIOUS position?
        // OR we can refactor updateElementPosition to take absolute.
        // Let's stick to calculating new position and manually updating state with bounds logic inside a setter.

        // Actually, updateElementPosition uses setElementPositions(prev => ...).
        // Let's duplicate bounds logic for mouse drag to be precise or reuse.
        // reusing updateElementPosition requires calculating dx/dy from *current state* which might be lagging in the closure?
        // No, functional update is fine.

        // But for smooth mouse drag, absolute position is better.
        const rawNewX = e.clientX - dragOffsetRef.current.x;
        const rawNewY = e.clientY - dragOffsetRef.current.y;

        setElementPositions(prev => {
            const size = elementSizes[id] || { w: 100, h: 100 }; // Fallback
            let newX = rawNewX;
            let newY = rawNewY;

            const width = window.innerWidth;
            const height = window.innerHeight;
            const margin = 0;

            if (id === 'chat') {
                newX = Math.max(size.w / 2 + margin, Math.min(width - size.w / 2 - margin, newX));
                newY = Math.max(margin, Math.min(height - size.h - margin, newY));
            } else if (id === 'video') {
                newX = Math.max(margin, Math.min(width - size.w - margin, newX));
                newY = Math.max(margin, Math.min(height - size.h - margin, newY));
            } else {
                newX = Math.max(size.w / 2 + margin, Math.min(width - size.w / 2 - margin, newX));
                newY = Math.max(size.h / 2 + margin, Math.min(height - size.h / 2 - margin, newY));
            }

            return {
                ...prev,
                [id]: { x: newX, y: newY }
            };
        });
    };

    const handleMouseUp = () => {
        isDraggingRef.current = false;
        setActiveDragElement(null);
        activeDragElementRef.current = null;
        window.removeEventListener('mousemove', handleMouseDrag);
        window.removeEventListener('mouseup', handleMouseUp);
    };

    // Calculate Average Audio Amplitude for Background Pulse
    const audioAmp = aiAudioData.reduce((a, b) => a + b, 0) / aiAudioData.length / 255;

    const toggleKasaWindow = () => {
        if (!showKasaWindow) {
            // Maybe trigger discover instantly?
            if (kasaDevices.length === 0) socket.emit('discover_kasa');
        }
        setShowKasaWindow(!showKasaWindow);
    };

    const togglePrinterWindow = () => {
        setShowPrinterWindow(!showPrinterWindow);
    };

    const toggleSimulationDashboard = () => {
        setShowSimulationDashboard(!showSimulationDashboard);
        if (!showSimulationDashboard) {
            bringToFront('simulation');
        }
    };

    const toggleOpenClawDashboard = () => {
        setShowOpenClawDashboard(!showOpenClawDashboard);
        if (!showOpenClawDashboard) {
            bringToFront('openclaw');
        }
    };

    const openPrinterWindow = () => {
        setShowPrinterWindow(true);
        const size = elementSizes.printer || { w: 380, h: 380 };
        const clamped = clampToViewport({ x: window.innerWidth / 2, y: window.innerHeight / 2 }, size);
        setElementPositions(prev => ({
            ...prev,
            printer: clamped
        }));
        bringToFront('printer');
    };

    const isDashboardListening = isConnected && !isMuted;

    const toggleDashboardListening = () => {
        if (!isConnected) {
            togglePower();
            return;
        }
        toggleMute();
    };

    const discoverKasaDevices = () => {
        socket.emit('discover_kasa');
    };

    const controlKasaDevice = (ip, action, value) => {
        if (!ip || !action) return;
        socket.emit('control_kasa', { ip, action, value });
    };

    const runWebAgentPrompt = (prompt) => {
        const text = String(prompt || '').trim();
        if (!text) return;
        setShowBrowserWindow(true);
        bringToFront('browser');
        socket.emit('prompt_web_agent', { prompt: text });
        addMessage('System', `Web Agent ejecutando: ${text}`);
    };

    const handleDashboardQuickAction = async (actionId) => {
        switch (actionId) {
            case 'create-event':
                setShowCalendarEventModal(true);
                break;
            case 'view-calendar':
                refreshCalendarEvents();
                break;
            case 'linkedin-post':
                setShowLinkedInPostModal(true);
                break;
            case 'manage-integrations':
                setShowOpenClawDashboard(true);
                bringToFront('openclaw');
                break;
            case 'settings':
                setShowSettings(true);
                break;
            case 'new-task':
                // TODO: connect to a real task manager endpoint when it exists.
                setInputValue('Crea una tarea para ... mañana a las ...');
                addMessage('System', 'Plantilla de tarea preparada. Completa el comando y envíalo a Jarvis.');
                break;
            case 'toggle-video':
                toggleVideo();
                break;
            case 'toggle-hand':
                if (isHandTrackingEnabled) {
                    setIsHandTrackingEnabled(false);
                    break;
                }
                if (!isVideoOn) {
                    await startVideo();
                }
                setIsHandTrackingEnabled(true);
                break;
            case 'toggle-cad': {
                const next = !showCadWindow;
                setShowCadWindow(next);
                if (next) bringToFront('cad');
                break;
            }
            case 'cad-command':
                setInputValue('Genera un modelo 3D de ');
                break;
            case 'toggle-browser': {
                const next = !showBrowserWindow;
                setShowBrowserWindow(next);
                if (next) bringToFront('browser');
                break;
            }
            case 'browser-command':
                setInputValue('Abre el agente web y busca ');
                break;
            case 'toggle-kasa':
                toggleKasaWindow();
                break;
            case 'toggle-printer':
                togglePrinterWindow();
                break;
            case 'toggle-simulation':
                toggleSimulationDashboard();
                break;
            case 'toggle-openclaw':
                toggleOpenClawDashboard();
                break;
            case 'toggle-power':
                togglePower();
                break;
            case 'toggle-mic':
                toggleMute();
                break;
            case 'open-notes':
                // TODO: connect to project notes once the notes surface exists.
                setInputValue('Abre las notas del proyecto ');
                addMessage('System', 'Acción de notas preparada. Completa el comando y envíalo a Jarvis.');
                break;
            default:
                console.warn('[Dashboard] Unhandled quick action:', actionId);
        }
    };

    const handleConfirmDashboardPending = async (id) => {
        const response = await confirmPendingAction(id);
        if (!response.ok && !response.success) {
            addMessage('System', response.error || 'No se pudo confirmar la acción pendiente.');
        }
        await Promise.all([refreshPendingActions(), refreshOpenClawEvents(), refreshCalendarEvents()]);
    };

    const handleCancelDashboardPending = async (id) => {
        const response = await cancelPendingAction(id);
        if (!response.ok && !response.success) {
            addMessage('System', response.error || 'No se pudo cancelar la acción pendiente.');
        }
        await Promise.all([refreshPendingActions(), refreshOpenClawEvents()]);
    };

    const handleCreateCalendarEvent = async (payload) => {
        const response = await createCalendarEvent(payload);
        await Promise.all([refreshPendingActions(), refreshOpenClawEvents(), refreshCalendarEvents()]);
        return response;
    };

    const handleDryRunCalendarEvent = async (payload) => {
        const response = await createCalendarEvent({ ...payload, dry_run: true });
        await refreshOpenClawEvents();
        return response;
    };

    const handlePrepareLinkedInPost = async (content) => {
        const response = await prepareLinkedInPost(content);
        await refreshOpenClawEvents();
        return response;
    };

    const handlePublishLinkedInPost = async (content) => {
        const response = await publishLinkedInPost(content);
        await Promise.all([refreshPendingActions(), refreshOpenClawEvents()]);
        return response;
    };

    const statusValue = (enabled, yes, no) => enabled ? yes : no;
    const openClawOnline = Boolean(openClawStatus?.success);
    const backendOnline = Boolean(backendStatus?.ok);
    const backendSystem = backendStatus?.data?.system || backendStatus?.raw?.system || {};
    const cpuInfo = backendSystem?.cpu || {};
    const memoryInfo = backendSystem?.memory || {};
    const cpuPercent = Number.isFinite(Number(cpuInfo.percent)) ? Number(cpuInfo.percent) : null;
    const memoryPercent = Number.isFinite(Number(memoryInfo.percent)) ? Number(memoryInfo.percent) : null;

    const formatBytes = (bytes) => {
        const value = Number(bytes);
        if (!Number.isFinite(value) || value <= 0) return null;
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
        return `${(value / (1024 ** index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
    };

    const memoryDetail = memoryInfo.used_bytes && memoryInfo.total_bytes
        ? `${formatBytes(memoryInfo.used_bytes)} / ${formatBytes(memoryInfo.total_bytes)}`
        : memoryInfo.error || 'No disponible';
    const processorDetail = [
        cpuInfo.processor,
        cpuInfo.cores ? `${cpuInfo.cores} cores` : null,
    ].filter(Boolean).join(' · ') || 'No disponible';
    const integrationByName = new Map(integrationStatuses.map(item => [item.name, item]));
    const connectionNames = [
        ['OpenClaw', 'OpenClaw'],
        ['WhatsApp', 'WhatsApp'],
        ['Google Calendar', 'Calendar'],
        ['LinkedIn', 'LinkedIn'],
    ];

    const dashboardData = {
        systemItems: [
            { label: 'Backend', value: backendStatus ? statusValue(backendOnline, 'Online', 'Offline') : 'Sin datos', connected: backendOnline, detail: dashboardError.backend || 'GET /status' },
            { label: 'Socket', value: statusValue(socketConnected, 'Online', 'Offline'), connected: socketConnected, detail: 'Socket.IO' },
            {
                label: 'RAM',
                value: memoryPercent !== null ? `${memoryPercent}%` : 'No disponible',
                connected: memoryPercent !== null,
                detail: memoryDetail,
                percent: memoryPercent,
            },
            {
                label: 'Procesador',
                value: cpuPercent !== null ? `${cpuPercent}%` : 'No disponible',
                connected: cpuPercent !== null,
                detail: processorDetail,
                percent: cpuPercent,
            },
        ],
        connections: connectionNames.map(([sourceName, label]) => {
            const item = integrationByName.get(sourceName);
            return {
                label,
                value: item?.shortStatus || item?.meta || 'Sin datos',
                connected: item?.state === 'connected',
                tone: item?.tone || '',
            };
        }),
        agenda: calendarEvents,
        pendingActions,
        integrations: integrationStatuses,
        recentActivity: openClawEvents,
        capabilities: [
            {
                id: 'voice',
                icon: 'voice',
                title: 'Voz / Modelo',
                state: isConnected ? (isMuted ? 'Pausado' : 'Escuchando') : 'Apagado',
                stateTone: isConnected && !isMuted ? 'green' : '',
                description: 'Control del modelo y entrada de micrófono.',
                primaryAction: 'toggle-power',
                primaryLabel: isConnected ? 'Apagar' : 'Encender',
                secondaryAction: 'toggle-mic',
                secondaryLabel: isMuted ? 'Reanudar mic' : 'Pausar mic',
            },
            {
                id: 'camera',
                icon: 'camera',
                title: 'Cámara',
                state: isVideoOn ? `Activa${fps ? ` · ${fps} FPS` : ''}` : 'Inactiva',
                stateTone: isVideoOn ? 'green' : '',
                description: 'Visión para contexto visual y captura de frames.',
                primaryAction: 'toggle-video',
                primaryLabel: isVideoOn ? 'Desactivar' : 'Activar',
            },
            {
                id: 'gestures',
                icon: 'gestures',
                title: 'Gestos',
                state: isHandTrackingEnabled ? 'Activos' : 'Inactivos',
                stateTone: isHandTrackingEnabled ? 'green' : '',
                description: 'Cursor por mano, pinch click, fist drag.',
                primaryAction: 'toggle-hand',
                primaryLabel: isHandTrackingEnabled ? 'Desactivar' : 'Activar',
            },
            {
                id: 'auth',
                icon: 'auth',
                title: 'Face Auth',
                state: faceAuthEnabled ? 'Activo' : 'Inactivo',
                stateTone: faceAuthEnabled ? 'green' : '',
                description: 'Autenticación facial configurable desde el perfil.',
            },
            {
                id: 'cad',
                icon: 'cad',
                title: 'CAD',
                state: showCadWindow ? 'Abierto' : 'Cerrado',
                stateTone: showCadWindow ? 'green' : '',
                description: 'Generación, iteración y vista 3D de modelos.',
                primaryAction: 'toggle-cad',
                primaryLabel: showCadWindow ? 'Cerrar' : 'Abrir',
                secondaryAction: 'cad-command',
                secondaryLabel: 'Preparar prompt',
            },
            {
                id: 'browser',
                icon: 'browser',
                title: 'Web Agent',
                state: showBrowserWindow ? 'Abierto' : 'Cerrado',
                stateTone: showBrowserWindow ? 'green' : '',
                description: 'Automatización web visual controlada por Jarvis.',
                primaryAction: 'toggle-browser',
                primaryLabel: showBrowserWindow ? 'Cerrar' : 'Abrir',
                secondaryAction: 'browser-command',
                secondaryLabel: 'Preparar búsqueda',
            },
            {
                id: 'kasa',
                icon: 'kasa',
                title: 'Kasa',
                state: kasaDevices.length ? `${kasaDevices.length} detectado(s)` : 'Sin dispositivos',
                stateTone: kasaDevices.length ? 'green' : '',
                description: 'Control de dispositivos inteligentes Kasa.',
                primaryAction: 'toggle-kasa',
                primaryLabel: showKasaWindow ? 'Cerrar' : 'Abrir',
            },
            {
                id: 'printer',
                icon: 'printer',
                title: 'Impresión 3D',
                state: activePrintStatus?.state || (slicingStatus.active ? `${slicingStatus.percent}% slicing` : (printerCount ? `${printerCount} impresora(s)` : 'Sin impresoras detectadas')),
                stateTone: printerCount || activePrintStatus || slicingStatus.active ? 'green' : '',
                description: activePrintStatus?.printer || slicingStatus.message || 'Slicing, estado y control de impresión.',
                primaryAction: 'toggle-printer',
                primaryLabel: showPrinterWindow ? 'Cerrar' : 'Abrir',
            },
            {
                id: 'simulation',
                icon: 'simulation',
                title: 'Simulación',
                state: simulationState.simulation_mode ? 'Activa' : 'Inactiva',
                stateTone: simulationState.simulation_mode ? 'green' : '',
                description: 'Panel de simulación para Kasa e impresión.',
                primaryAction: 'toggle-simulation',
                primaryLabel: showSimulationDashboard ? 'Cerrar' : 'Abrir',
            },
            {
                id: 'openclaw',
                icon: 'openclaw',
                title: 'WhatsApp',
                state: openClawOnline ? 'Online' : (openClawStatus ? 'Error' : 'Sin datos'),
                stateTone: openClawOnline ? 'green' : '',
                description: 'Mensajería y automatizaciones mediante Gateway.',
                primaryAction: 'toggle-openclaw',
                primaryLabel: showOpenClawDashboard ? 'Cerrar' : 'Abrir',
            },
        ],
        loading: dashboardLoading,
        errors: dashboardError,
        runtime: {
            activePrintStatus,
            backendStatus,
            browserData,
            currentProject,
            faceAuthEnabled,
            fps,
            isConnected,
            isHandTrackingEnabled,
            isMuted,
            isVideoOn,
            kasaDevices,
            openClawStatus,
            printerCount,
            projectTree,
            projectTreeError,
            projectTreeLoading,
            projects,
            projectsError: dashboardError.projects,
            projectsLoading: Boolean(dashboardLoading.projects),
            showBrowserWindow,
            showCadWindow,
            showKasaWindow,
            showPrinterWindow,
            showSimulationDashboard,
            simulationState,
            slicingStatus,
            socketConnected,
            status,
        },
    };



    return (
        <div className="jarvis-runtime-shell">
            <JarvisDashboard
                activeModule={activeModule}
                currentTime={currentTime}
                status={status}
                socketConnected={socketConnected}
                isConnected={isConnected}
                isMuted={isMuted}
                isListening={isDashboardListening}
                isVideoOn={isVideoOn}
                isHandTrackingEnabled={isHandTrackingEnabled}
                faceAuthEnabled={faceAuthEnabled}
                inputValue={inputValue}
                setInputValue={setInputValue}
                messages={messages}
                onCommandSubmit={submitCommand}
                onToggleListening={toggleDashboardListening}
                onQuickAction={handleDashboardQuickAction}
                onModuleChange={setActiveModule}
                onOpenSettings={() => setShowSettings(true)}
                onMinimize={handleMinimize}
                onMaximize={handleMaximize}
                onClose={handleCloseRequest}
                dashboardData={dashboardData}
                audioLevel={audioAmp}
                onRefreshCalendar={refreshCalendarEvents}
                onRefreshPending={refreshPendingActions}
                onRefreshActivity={refreshOpenClawEvents}
                onRefreshIntegrations={refreshIntegrationStatuses}
                onRefreshProjects={refreshProjects}
                onLoadProjectTree={loadProjectTree}
                onConfirmPending={handleConfirmDashboardPending}
                onCancelPending={handleCancelDashboardPending}
                onPrepareLinkedInPost={handlePrepareLinkedInPost}
                onPublishLinkedInPost={handlePublishLinkedInPost}
                onDiscoverKasa={discoverKasaDevices}
                onControlKasa={controlKasaDevice}
                onRunWebAgent={runWebAgentPrompt}
            />

            <CalendarEventModal
                open={showCalendarEventModal}
                onClose={() => setShowCalendarEventModal(false)}
                onCreate={handleCreateCalendarEvent}
                onDryRun={handleDryRunCalendarEvent}
            />

            <LinkedInPostModal
                open={showLinkedInPostModal}
                onClose={() => setShowLinkedInPostModal(false)}
                onPrepare={handlePrepareLinkedInPost}
                onPublish={handlePublishLinkedInPost}
            />

            {isLockScreenVisible && (
                <AuthLock
                    socket={socket}
                    onAuthenticated={() => setIsAuthenticated(true)}
                    onAnimationComplete={() => setIsLockScreenVisible(false)}
                />
            )}

            {isHandTrackingEnabled && (
                <div
                    className={`jarvis-hand-cursor ${isPinching ? 'is-pinching' : ''}`}
                    style={{ left: cursorPos.x, top: cursorPos.y }}
                >
                    <span />
                </div>
            )}

            <div className={`jarvis-video-feed ${isVideoOn ? 'is-visible' : ''}`}>
                <video ref={videoRef} autoPlay muted className="jarvis-video-source" />
                <div className="jarvis-video-frame">
                    <div className="jarvis-video-label">CAM_01 {fps > 0 ? `| ${fps} FPS` : ''}</div>
                    <canvas
                        ref={canvasRef}
                        className="jarvis-video-canvas"
                        style={{ transform: isCameraFlipped ? 'scaleX(-1)' : 'none' }}
                    />
                </div>
            </div>

            {showSettings && (
                <SettingsWindow
                    socket={socket}
                    micDevices={micDevices}
                    speakerDevices={speakerDevices}
                    webcamDevices={webcamDevices}
                    selectedMicId={selectedMicId}
                    setSelectedMicId={setSelectedMicId}
                    selectedSpeakerId={selectedSpeakerId}
                    setSelectedSpeakerId={setSelectedSpeakerId}
                    selectedWebcamId={selectedWebcamId}
                    setSelectedWebcamId={setSelectedWebcamId}
                    cursorSensitivity={cursorSensitivity}
                    setCursorSensitivity={setCursorSensitivity}
                    isCameraFlipped={isCameraFlipped}
                    setIsCameraFlipped={setIsCameraFlipped}
                    handleFileUpload={handleFileUpload}
                    onClose={() => setShowSettings(false)}
                />
            )}

            {showCadWindow && (
                <div
                    id="cad"
                    className={`jarvis-floating-window ${activeDragElement === 'cad' ? 'is-dragging' : ''}`}
                    style={{
                        left: elementPositions.cad?.x || window.innerWidth / 2,
                        top: elementPositions.cad?.y || window.innerHeight / 2,
                        width: `${elementSizes.cad.w}px`,
                        height: `${elementSizes.cad.h}px`,
                        zIndex: getZIndex('cad')
                    }}
                    onMouseDown={(e) => handleMouseDown(e, 'cad')}
                >
                    <div data-drag-handle className="jarvis-floating-window-header">
                        <span>CAD PROTOTYPE</span>
                        <button type="button" onClick={() => setShowCadWindow(false)}>X</button>
                    </div>
                    <div className="jarvis-floating-window-body">
                        <CadWindow
                            data={cadData}
                            thoughts={cadThoughts}
                            retryInfo={cadRetryInfo}
                            onClose={() => setShowCadWindow(false)}
                            onRequestPrint={openPrinterWindow}
                            socket={socket}
                        />
                    </div>
                </div>
            )}

            {showBrowserWindow && (
                <div
                    id="browser"
                    className={`jarvis-floating-window browser ${activeDragElement === 'browser' ? 'is-dragging' : ''}`}
                    style={{
                        left: elementPositions.browser?.x || window.innerWidth / 2 - 200,
                        top: elementPositions.browser?.y || window.innerHeight / 2,
                        width: `${elementSizes.browser.w}px`,
                        height: `${elementSizes.browser.h}px`,
                        zIndex: getZIndex('browser')
                    }}
                    onMouseDown={(e) => handleMouseDown(e, 'browser')}
                >
                    <BrowserWindow
                        imageSrc={browserData.image}
                        logs={browserData.logs}
                        onClose={() => setShowBrowserWindow(false)}
                        socket={socket}
                    />
                </div>
            )}

            {showKasaWindow && (
                <KasaWindow
                    socket={socket}
                    position={elementPositions.kasa}
                    activeDragElement={activeDragElement}
                    setActiveDragElement={setActiveDragElement}
                    devices={kasaDevices}
                    onClose={() => setShowKasaWindow(false)}
                    onMouseDown={(e) => handleMouseDown(e, 'kasa')}
                    zIndex={getZIndex('kasa')}
                />
            )}

            {showPrinterWindow && (
                <PrinterWindow
                    socket={socket}
                    onClose={() => setShowPrinterWindow(false)}
                    position={elementPositions.printer}
                    onMouseDown={(e) => handleMouseDown(e, 'printer')}
                    activeDragElement={activeDragElement}
                    setActiveDragElement={setActiveDragElement}
                    zIndex={getZIndex('printer')}
                />
            )}

            {showSimulationDashboard && (
                <SimulationDashboard
                    socket={socket}
                    onClose={() => setShowSimulationDashboard(false)}
                    position={elementPositions.simulation}
                    onMouseDown={(e) => handleMouseDown(e, 'simulation')}
                    zIndex={getZIndex('simulation')}
                />
            )}

            {showOpenClawDashboard && (
                <OpenClawDashboard
                    onClose={() => setShowOpenClawDashboard(false)}
                    position={elementPositions.openclaw}
                    onMouseDown={(e) => handleMouseDown(e, 'openclaw')}
                    zIndex={getZIndex('openclaw')}
                />
            )}

            <ConfirmationPopup
                request={confirmationRequest}
                onConfirm={handleConfirmTool}
                onDeny={handleDenyTool}
            />
        </div>
    );
}

export default App;
