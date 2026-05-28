const API_BASE = 'http://localhost:8000';

const ok = (data, meta = {}) => ({
    ok: true,
    success: data?.success !== false,
    data,
    raw: data,
    error: null,
    ...meta,
});

const fail = (error, meta = {}) => ({
    ok: false,
    success: false,
    data: null,
    raw: null,
    error: error?.message || String(error || 'Error desconocido'),
    ...meta,
});

const requestJson = async (path, options = {}) => {
    try {
        const response = await fetch(`${API_BASE}${path}`, {
            headers: {
                'Content-Type': 'application/json',
                ...(options.headers || {}),
            },
            ...options,
        });

        const text = await response.text();
        const body = text ? JSON.parse(text) : {};
        if (!response.ok) {
            return fail(body?.error || body?.message || response.statusText, {
                status: response.status,
                raw: body,
                data: body,
            });
        }

        return ok(body, { status: response.status });
    } catch (error) {
        return fail(error);
    }
};

export const getBackendStatus = () => requestJson('/status');

export const getOpenClawStatus = () => requestJson('/api/openclaw/status');

export const getOpenClawEvents = (limit = 10) => requestJson(`/api/openclaw/events?limit=${encodeURIComponent(limit)}`);

export const getPendingActions = () => requestJson('/api/pending-actions');

export const getProjects = () => requestJson('/api/projects');

export const getProjectTree = (projectName) => requestJson(`/api/projects/${encodeURIComponent(projectName)}/tree`);

export const confirmPendingAction = (id) => requestJson(`/api/pending-actions/${encodeURIComponent(id)}/confirm`, {
    method: 'POST',
});

export const cancelPendingAction = (id) => requestJson(`/api/pending-actions/${encodeURIComponent(id)}/cancel`, {
    method: 'POST',
});

export const runOpenClawAction = (action_type, payload = {}) => requestJson('/api/openclaw/action', {
    method: 'POST',
    body: JSON.stringify({ action_type, payload }),
});

export const listCalendarEvents = (maxResults = 20) => runOpenClawAction('list_calendar_events', {
    max_results: maxResults,
});

export const createCalendarEvent = (payload) => runOpenClawAction('create_calendar_event', payload);

export const prepareLinkedInPost = (content) => runOpenClawAction('publish_social_post', {
    platform: 'linkedin',
    content,
    dry_run: true,
});

export const publishLinkedInPost = (content) => runOpenClawAction('publish_social_post', {
    platform: 'linkedin',
    content,
});

const unwrapData = (response) => response?.data ?? response?.raw ?? response;

const firstArray = (...values) => values.find(Array.isArray) || [];

export const extractCalendarItems = (response) => {
    const body = unwrapData(response);
    const data = body?.data ?? body;
    const raw = data?.raw;
    const json = raw?.json;

    return firstArray(
        response?.raw?.json?.raw?.items,
        response?.raw?.json?.items,
        response?.raw?.items,
        json?.raw?.items,
        json?.items,
        raw?.items,
        raw?.event ? [raw.event] : null,
        raw?.events,
        data?.items,
        data?.events,
        Array.isArray(raw) ? raw : null,
        Array.isArray(data) ? data : null,
    );
};

export const normalizeCalendarEvent = (event, index = 0) => {
    const startValue = event?.start?.dateTime || event?.start?.date || event?.start_time || event?.start;
    const endValue = event?.end?.dateTime || event?.end?.date || event?.end_time || event?.end;
    const startDate = startValue ? new Date(startValue) : null;
    const endDate = endValue ? new Date(endValue) : null;
    const validStart = startDate && !Number.isNaN(startDate.getTime());
    const validEnd = endDate && !Number.isNaN(endDate.getTime());

    return {
        id: event?.id || event?.event_id || `${startValue || 'event'}-${index}`,
        summary: event?.summary || event?.title || 'Sin título',
        start: startValue || null,
        end: endValue || null,
        startTime: validStart ? startDate.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }) : 'Todo el día',
        endTime: validEnd ? endDate.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }) : '',
        location: event?.location || '',
        description: event?.description || '',
        htmlLink: event?.htmlLink || event?.link || '',
        raw: event,
    };
};

export const normalizeOpenClawEvents = (response) => {
    const body = unwrapData(response);
    const events = body?.data || body?.events || body?.raw || [];
    return Array.isArray(events) ? events.map((event, index) => ({
        id: event?.id || `${event?.timestamp || 'event'}-${index}`,
        type: event?.type || 'evento',
        channel: event?.channel || '',
        message: event?.message || '',
        success: event?.success,
        error: event?.error || '',
        timestamp: event?.timestamp || event?.created_at || '',
        display_target: event?.display_target || event?.target || '',
        raw: event,
    })) : [];
};

export const normalizePendingActions = (response) => {
    const body = unwrapData(response);
    const actions = body?.actions || body?.data?.actions || body?.data || [];
    return Array.isArray(actions) ? actions : [];
};
