import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const PLUGIN_ID = "jarvis-productivity";

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function clean(value) {
  return value == null ? "" : String(value).trim();
}

function bool(value) {
  return value === true || ["1", "true", "yes", "si", "on"].includes(clean(value).toLowerCase());
}

function readConfig(api) {
  const config = asObject(api.pluginConfig);
  const googleCalendar = asObject(config.googleCalendar);
  const linkedin = asObject(config.linkedin);
  return {
    googleCalendar: {
      accessToken: clean(googleCalendar.accessToken) || clean(process.env.JARVIS_GOOGLE_CALENDAR_ACCESS_TOKEN),
      refreshToken: clean(googleCalendar.refreshToken) || clean(process.env.JARVIS_GOOGLE_CALENDAR_REFRESH_TOKEN),
      clientId: clean(googleCalendar.clientId) || clean(process.env.JARVIS_GOOGLE_CALENDAR_CLIENT_ID),
      clientSecret: clean(googleCalendar.clientSecret) || clean(process.env.JARVIS_GOOGLE_CALENDAR_CLIENT_SECRET),
      calendarId: clean(googleCalendar.calendarId) || clean(process.env.JARVIS_GOOGLE_CALENDAR_ID) || "primary",
    },
    linkedin: {
      accessToken: clean(linkedin.accessToken) || clean(process.env.JARVIS_LINKEDIN_ACCESS_TOKEN),
      authorUrn: clean(linkedin.authorUrn) || clean(process.env.JARVIS_LINKEDIN_AUTHOR_URN),
      defaultVisibility: clean(linkedin.defaultVisibility) || clean(process.env.JARVIS_LINKEDIN_DEFAULT_VISIBILITY) || "PUBLIC",
      apiVersion: clean(linkedin.apiVersion) || clean(process.env.JARVIS_LINKEDIN_API_VERSION) || "202605",
    },
  };
}

function ok(actionType, summary, raw = undefined) {
  return {
    success: true,
    action_done: actionType,
    details: summary,
    summary,
    raw,
    warnings: [],
  };
}

function fail(actionType, summary, code, warnings = []) {
  return {
    success: false,
    action_done: actionType,
    details: summary,
    summary,
    code,
    warnings,
  };
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const text = await response.text();
  let parsed = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { text };
    }
  }
  if (!response.ok) {
    const message = parsed?.error?.message || parsed?.message || text || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.payload = parsed;
    throw error;
  }
  return parsed;
}

async function getGoogleCalendarAccessToken(config) {
  if (config.googleCalendar.accessToken) return config.googleCalendar.accessToken;
  if (!config.googleCalendar.refreshToken || !config.googleCalendar.clientId || !config.googleCalendar.clientSecret) {
    return "";
  }
  const body = new URLSearchParams({
    client_id: config.googleCalendar.clientId,
    client_secret: config.googleCalendar.clientSecret,
    refresh_token: config.googleCalendar.refreshToken,
    grant_type: "refresh_token",
  });
  const result = await fetchJson("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });
  return clean(result?.access_token);
}

function googleCalendarMissingAuth(actionType, purpose) {
  return fail(
    actionType,
    `Falta configurar credenciales de Google Calendar para ${purpose}.`,
    "GOOGLE_CALENDAR_SETUP_REQUIRED",
    ["missing_google_calendar_credentials"],
  );
}

function googleEventFromPayload(payload) {
  const title = clean(payload.title || payload.summary || payload.name || payload.text);
  const start = clean(payload.start || payload.start_time || payload.startTime);
  const end = clean(payload.end || payload.end_time || payload.endTime);
  const timeZone = clean(payload.time_zone || payload.timeZone || payload.timezone) || "Europe/Madrid";
  if (!title) throw new Error("Falta el titulo del evento.");
  if (!start) throw new Error("Falta la fecha/hora de inicio del evento.");

  const allDay = bool(payload.all_day || payload.allDay);
  const startDate = dateOnly(start);
  const endDate = dateOnly(end);
  const event = allDay && startDate
    ? {
        summary: title,
        start: { date: startDate },
        end: { date: endDate || addDays(startDate, 1) },
      }
    : {
        summary: title,
        start: { dateTime: start, timeZone },
        end: { dateTime: end || start, timeZone },
      };
  const description = clean(payload.description || payload.details || payload.notes || payload.natural_language);
  const location = clean(payload.location);
  if (description) event.description = description;
  if (location) event.location = location;
  return event;
}

function dateOnly(value) {
  const text = clean(value);
  if (!text) return "";
  const candidate = text.split("T")[0];
  return /^\d{4}-\d{2}-\d{2}$/.test(candidate) ? candidate : "";
}

function addDays(value, days) {
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

async function createGoogleCalendarEvent(actionType, payload, config) {
  if (bool(payload.dry_run)) {
    const event = googleEventFromPayload(payload);
    return ok(actionType, `Dry-run: evento preparado en Google Calendar: ${event.summary}.`, {
      configured: Boolean(config.googleCalendar.accessToken || (config.googleCalendar.refreshToken && config.googleCalendar.clientId && config.googleCalendar.clientSecret)),
      event,
    });
  }

  const accessToken = await getGoogleCalendarAccessToken(config);
  if (!accessToken) return googleCalendarMissingAuth(actionType, "crear eventos");

  const event = googleEventFromPayload(payload);
  const calendarId = encodeURIComponent(clean(payload.calendar_id || payload.calendarId) || config.googleCalendar.calendarId);
  const result = await fetchJson(`https://www.googleapis.com/calendar/v3/calendars/${calendarId}/events`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(event),
  });
  return ok(actionType, `Evento creado en Google Calendar: ${event.summary}.`, {
    id: result?.id,
    htmlLink: result?.htmlLink,
    event: result,
  });
}

async function listGoogleCalendarEvents(actionType, payload, config) {
  const accessToken = await getGoogleCalendarAccessToken(config);
  if (!accessToken) return googleCalendarMissingAuth(actionType, "leer eventos");

  const calendarId = encodeURIComponent(clean(payload.calendar_id || payload.calendarId) || config.googleCalendar.calendarId);
  const params = new URLSearchParams({
    singleEvents: "true",
    orderBy: "startTime",
    maxResults: String(Number(payload.max_results || payload.maxResults || 10)),
  });
  const timeMin = clean(payload.time_min || payload.timeMin || payload.start);
  const timeMax = clean(payload.time_max || payload.timeMax || payload.end);
  if (timeMin) params.set("timeMin", timeMin);
  if (timeMax) params.set("timeMax", timeMax);

  const result = await fetchJson(`https://www.googleapis.com/calendar/v3/calendars/${calendarId}/events?${params.toString()}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  });
  const items = Array.isArray(result?.items) ? result.items : [];
  return ok(actionType, `${items.length} evento(s) encontrados en Google Calendar.`, { items });
}

async function mutateGoogleCalendarEvent(actionType, payload, config, method) {
  const accessToken = await getGoogleCalendarAccessToken(config);
  if (!accessToken) return googleCalendarMissingAuth(actionType, "modificar eventos");
  const eventId = clean(payload.event_id || payload.eventId || payload.id);
  if (!eventId) return fail(actionType, "Falta el id del evento de calendario.", "MISSING_EVENT_ID", ["missing_event_id"]);

  const calendarId = encodeURIComponent(clean(payload.calendar_id || payload.calendarId) || config.googleCalendar.calendarId);
  const url = `https://www.googleapis.com/calendar/v3/calendars/${calendarId}/events/${encodeURIComponent(eventId)}`;
  if (method === "DELETE") {
    await fetchJson(url, {
      method,
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return ok(actionType, "Evento eliminado de Google Calendar.", { id: eventId });
  }

  const result = await fetchJson(url, {
    method,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(googleEventFromPayload(payload)),
  });
  return ok(actionType, "Evento actualizado en Google Calendar.", { id: result?.id, event: result });
}

function linkedinPostBody(payload, config) {
  const content = clean(payload.content || payload.text || payload.message || payload.body);
  if (!content) throw new Error("Falta el texto de la publicacion de LinkedIn.");
  if (!config.linkedin.authorUrn) throw new Error("Falta configurar JARVIS_LINKEDIN_AUTHOR_URN.");
  const visibility = clean(payload.visibility) || config.linkedin.defaultVisibility || "PUBLIC";
  return {
    author: config.linkedin.authorUrn,
    commentary: content,
    visibility,
    distribution: {
      feedDistribution: clean(payload.feed_distribution || payload.feedDistribution) || "MAIN_FEED",
      targetEntities: Array.isArray(payload.target_entities || payload.targetEntities)
        ? (payload.target_entities || payload.targetEntities)
        : [],
      thirdPartyDistributionChannels: Array.isArray(payload.third_party_distribution_channels || payload.thirdPartyDistributionChannels)
        ? (payload.third_party_distribution_channels || payload.thirdPartyDistributionChannels)
        : [],
    },
    lifecycleState: "PUBLISHED",
    isReshareDisabledByAuthor: bool(payload.is_reshare_disabled_by_author || payload.isReshareDisabledByAuthor),
  };
}

async function publishLinkedInPost(actionType, payload, config) {
  if (bool(payload.dry_run)) {
    const content = clean(payload.content || payload.text || payload.message || payload.body);
    if (!content) {
      return fail(
        actionType,
        "Falta el texto de la publicacion de LinkedIn.",
        "MISSING_LINKEDIN_CONTENT",
        ["missing_linkedin_content"],
      );
    }
    const visibility = clean(payload.visibility) || config.linkedin.defaultVisibility || "PUBLIC";
    return ok(actionType, "Dry-run: publicacion de LinkedIn preparada.", {
      configured: Boolean(config.linkedin.accessToken && config.linkedin.authorUrn),
      post: {
        author: config.linkedin.authorUrn || null,
        content,
        visibility,
        apiVersion: config.linkedin.apiVersion,
      },
    });
  }

  if (!config.linkedin.accessToken) {
    return fail(
      actionType,
      "Falta configurar JARVIS_LINKEDIN_ACCESS_TOKEN para publicar en LinkedIn.",
      "LINKEDIN_SETUP_REQUIRED",
      ["missing_linkedin_access_token"],
    );
  }

  const body = linkedinPostBody(payload, config);
  const response = await fetch("https://api.linkedin.com/rest/posts", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${config.linkedin.accessToken}`,
      "Content-Type": "application/json",
      "Linkedin-Version": config.linkedin.apiVersion,
      "X-Restli-Protocol-Version": "2.0.0",
    },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  let parsed = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { text };
    }
  }
  if (!response.ok) {
    const message = parsed?.error?.message || parsed?.message || text || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.payload = parsed;
    throw error;
  }
  return ok(actionType, "Publicacion enviada a LinkedIn.", {
    id: response.headers.get("x-restli-id"),
    post: parsed,
  });
}

async function executeAction(actionType, payload, config) {
  const action = clean(actionType);
  const data = asObject(payload);
  if (action === "list_calendar_events") return listGoogleCalendarEvents(action, data, config);
  if (action === "create_calendar_event") return createGoogleCalendarEvent(action, data, config);
  if (action === "update_calendar_event") return mutateGoogleCalendarEvent(action, data, config, "PATCH");
  if (action === "delete_calendar_event") return mutateGoogleCalendarEvent(action, data, config, "DELETE");
  if (action === "prepare_social_post") {
    const content = clean(data.content || data.text || data.message || data.body);
    return ok(action, content ? `Borrador preparado: ${content}` : "Borrador social preparado.", { content, platform: clean(data.platform) || "linkedin" });
  }
  if (action === "publish_social_post") {
    if (clean(data.platform || "linkedin").toLowerCase() !== "linkedin") {
      return fail(action, "Solo LinkedIn esta configurado en jarvis-productivity.", "UNSUPPORTED_SOCIAL_PLATFORM", ["unsupported_platform"]);
    }
    return publishLinkedInPost(action, data, config);
  }
  if (action === "schedule_social_post") {
    return fail(action, "La programacion de publicaciones todavia requiere un workflow/cron dedicado.", "SCHEDULING_NOT_CONFIGURED", ["scheduling_not_configured"]);
  }
  return fail(action, `Accion no soportada por jarvis-productivity: ${action}.`, "UNSUPPORTED_ACTION", ["unsupported_action"]);
}

function respondError(respond, actionType, error) {
  respond(true, fail(actionType, clean(error?.message) || String(error), "JARVIS_PRODUCTIVITY_ERROR", ["handler_error"]));
}

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "Jarvis Productivity",
  description: "Executes Jarvis calendar and LinkedIn actions through OpenClaw.",
  register(api) {
    api.registerGatewayMethod("jarvis.productivity.status", async ({ respond }) => {
      const config = readConfig(api);
      respond(true, ok("status", "Jarvis Productivity plugin loaded.", {
        googleCalendarConfigured: Boolean(config.googleCalendar.accessToken || (config.googleCalendar.refreshToken && config.googleCalendar.clientId && config.googleCalendar.clientSecret)),
        linkedinConfigured: Boolean(config.linkedin.accessToken && config.linkedin.authorUrn),
        linkedinApiVersion: config.linkedin.apiVersion,
      }));
    });

    api.registerGatewayMethod("jarvis.productivity.execute", async ({ params, respond }) => {
      const request = asObject(params);
      const actionType = clean(request.action_type || request.actionType);
      const payload = asObject(request.payload);
      try {
        const result = await executeAction(actionType, payload, readConfig(api));
        respond(true, result);
      } catch (error) {
        respondError(respond, actionType, error);
      }
    });
  },
});
