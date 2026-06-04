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
            return fail(body?.error || body?.message || body?.detail || response.statusText, {
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

export const reauthGoogleCalendar = () => requestJson('/api/calendar/reauth', { method: 'POST', body: '{}' });

export const getWhatsAppStatus = () => requestJson('/api/whatsapp/status');

export const getWhatsAppProvider = () => requestJson('/api/whatsapp/provider');

export const getWhatsAppMessages = (limit = 30, unreadOnly = false) =>
    requestJson(`/api/whatsapp/messages?limit=${limit}&unread_only=${unreadOnly}`);

export const markWhatsAppMessagesRead = (messageIds = null) =>
    requestJson('/api/whatsapp/messages/mark-read', {
        method: 'POST',
        body: JSON.stringify({ message_ids: messageIds }),
    });

export const getWhatsAppContacts = () => requestJson('/api/whatsapp/contacts');

export const syncWhatsAppContacts = () =>
    requestJson('/api/whatsapp/contacts/sync', { method: 'POST', body: JSON.stringify({}) });

export const getWhatsAppGroups = () => requestJson('/api/whatsapp/groups');

export const syncWhatsAppGroups = () =>
    requestJson('/api/whatsapp/groups/sync', { method: 'POST', body: JSON.stringify({}) });

export const sendWhatsAppImage = (target, imageUrl, caption = '', canonicalTarget = null) =>
    requestJson('/api/whatsapp/send-image', {
        method: 'POST',
        body: JSON.stringify({
            target,
            canonical_target: canonicalTarget || target,
            image_url: imageUrl,
            caption,
        }),
    });

export const getOpenClawEvents = (limit = 10) => requestJson(`/api/openclaw/events?limit=${encodeURIComponent(limit)}`);

export const getPendingActions = () => requestJson('/api/pending-actions');

export const getProjects = () => requestJson('/api/projects');

export const getProjectTree = (projectName) => requestJson(`/api/projects/${encodeURIComponent(projectName)}/tree`);

export const activateProject = (projectName) => requestJson(`/api/projects/${encodeURIComponent(projectName)}/activate`, {
    method: 'POST',
    body: JSON.stringify({}),
});

export const getMusicStatus = () => requestJson('/api/music/status');

export const searchMusic = (query, mode = 'search') => requestJson('/api/music/search', {
    method: 'POST',
    body: JSON.stringify({ query, mode }),
});

export const playMusic = (query, mode = 'search') => requestJson('/api/music/play', {
    method: 'POST',
    body: JSON.stringify({ query, mode }),
});

export const randomMusic = (payload = {}) => requestJson('/api/music/random', {
    method: 'POST',
    body: JSON.stringify(payload || {}),
});

export const sendMusicCommand = (command, payload = {}) => requestJson('/api/music/command', {
    method: 'POST',
    body: JSON.stringify({ command, ...(payload || {}) }),
});

export const getMusicPreferences = () => requestJson('/api/music/preferences');

export const updateMusicPreferences = (payload) => requestJson('/api/music/preferences', {
    method: 'POST',
    body: JSON.stringify(payload || {}),
});

export const getAutomations = () => requestJson('/api/automations');

export const getAutomationsHistory = (limit = 100) => requestJson(`/api/automations/history?limit=${encodeURIComponent(limit)}`);

export const getAutomationTemplates = () => requestJson('/api/automations/templates');

export const applyAutomationTemplate = (templateId, overrides = {}) => requestJson(`/api/automations/templates/${encodeURIComponent(templateId)}/apply`, {
    method: 'POST',
    body: JSON.stringify(overrides || {}),
});

export const confirmPendingAction = (id) => requestJson(`/api/pending-actions/${encodeURIComponent(id)}/confirm`, {
    method: 'POST',
});

export const cancelPendingAction = (id) => requestJson(`/api/pending-actions/${encodeURIComponent(id)}/cancel`, {
    method: 'POST',
});

export const createAutomation = (payload) => requestJson('/api/automations', {
    method: 'POST',
    body: JSON.stringify(payload || {}),
});

export const updateAutomation = (id, payload) => requestJson(`/api/automations/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(payload || {}),
});

export const deleteAutomation = (id) => requestJson(`/api/automations/${encodeURIComponent(id)}`, {
    method: 'DELETE',
});

export const runAutomation = (id) => requestJson(`/api/automations/${encodeURIComponent(id)}/run`, {
    method: 'POST',
});

export const dispatchAutomationEvent = (eventType, payload = {}) => requestJson('/api/automations/events/dispatch', {
    method: 'POST',
    body: JSON.stringify({ event_type: eventType, payload }),
});

export const runOpenClawAction = (action_type, payload = {}) => requestJson('/api/openclaw/action', {
    method: 'POST',
    body: JSON.stringify({ action_type, payload }),
});

export const listCalendarEvents = (options = 20) => {
    const config = typeof options === 'number' ? { max_results: options } : {
        max_results: options?.maxResults || options?.max_results || 20,
    };
    const timeMin = options?.timeMin || options?.time_min || options?.start;
    const timeMax = options?.timeMax || options?.time_max || options?.end;
    if (timeMin) config.time_min = timeMin;
    if (timeMax) config.time_max = timeMax;
    return runOpenClawAction('list_calendar_events', config);
};

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

const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/;

const padDatePart = (value) => String(value).padStart(2, '0');

export const isCalendarDateOnly = (value) => DATE_ONLY_RE.test(String(value || '').trim());

export const getCalendarDateKey = (value) => {
    if (value instanceof Date && !Number.isNaN(value.getTime())) {
        return [
            value.getFullYear(),
            padDatePart(value.getMonth() + 1),
            padDatePart(value.getDate()),
        ].join('-');
    }
    const text = String(value || '').trim();
    if (!text) return '';
    if (isCalendarDateOnly(text)) return text;
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return '';
    return [
        date.getFullYear(),
        padDatePart(date.getMonth() + 1),
        padDatePart(date.getDate()),
    ].join('-');
};

export const parseCalendarDate = (value) => {
    if (value instanceof Date) {
        return Number.isNaN(value.getTime()) ? null : value;
    }
    const text = String(value || '').trim();
    if (!text) return null;
    if (isCalendarDateOnly(text)) {
        const [year, month, day] = text.split('-').map(Number);
        return new Date(year, month - 1, day);
    }
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
};

export const getCalendarSortValue = (event) => {
    const date = parseCalendarDate(event?.start);
    return date ? date.getTime() : Number.MAX_SAFE_INTEGER;
};

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
    const startDate = parseCalendarDate(startValue);
    const endDate = parseCalendarDate(endValue);
    const allDay = isCalendarDateOnly(startValue) || Boolean(event?.allDay || event?.all_day);
    const validStart = startDate && !Number.isNaN(startDate.getTime());
    const validEnd = endDate && !Number.isNaN(endDate.getTime());

    return {
        id: event?.id || event?.event_id || `${startValue || 'event'}-${index}`,
        summary: event?.summary || event?.title || 'Sin título',
        start: startValue || null,
        end: endValue || null,
        startDateKey: getCalendarDateKey(startValue),
        endDateKey: getCalendarDateKey(endValue),
        allDay,
        startTime: allDay ? 'Todo el dia' : (validStart ? startDate.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }) : 'Todo el dia'),
        endTime: allDay ? '' : (validEnd ? endDate.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }) : ''),
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
