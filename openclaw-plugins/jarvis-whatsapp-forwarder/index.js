import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const PLUGIN_ID = "jarvis-whatsapp-forwarder";
const DEFAULT_ENDPOINT = "http://127.0.0.1:8000/api/openclaw/inbound";

function asObject(value) {
  return value && typeof value === "object" ? value : {};
}

function clean(value) {
  return value == null ? "" : String(value).trim();
}

function readConfig(api) {
  const config = asObject(api.pluginConfig);
  return {
    endpoint: clean(config.endpoint) || DEFAULT_ENDPOINT,
    timeoutMs: Number(config.timeoutMs || 2000),
    blockOpenClawReplies: config.blockOpenClawReplies !== false,
    includeRaw: config.includeRaw === true,
  };
}

function isWhatsApp(ctx, event) {
  return clean(ctx?.channelId || event?.channel || event?.metadata?.provider).toLowerCase() === "whatsapp";
}

function isGroupTarget(value) {
  const text = clean(value).toLowerCase();
  return text.endsWith("@g.us") || text.endsWith("@newsletter");
}

function resolveKind(event, ctx) {
  const metadata = asObject(event?.metadata);
  if (metadata.groupId || isGroupTarget(ctx?.conversationId) || isGroupTarget(metadata.originatingTo) || isGroupTarget(event?.from)) {
    return "group";
  }
  return "user";
}

function resolveSender(event) {
  const metadata = asObject(event?.metadata);
  return clean(metadata.senderE164 || event?.senderId || event?.from);
}

function resolveTarget(event, ctx, kind) {
  const metadata = asObject(event?.metadata);
  if (kind === "group") {
    return clean(ctx?.conversationId || metadata.groupId || metadata.originatingTo || event?.from);
  }
  return clean(metadata.senderE164 || event?.senderId || event?.from || ctx?.conversationId);
}

function buildPayload(event, ctx, config) {
  const metadata = asObject(event?.metadata);
  const kind = resolveKind(event, ctx);
  const target = resolveTarget(event, ctx, kind);
  const sender = resolveSender(event);
  const text = clean(event?.content || event?.body || metadata.body || metadata.text);
  const payload = {
    channel: "whatsapp",
    kind,
    target,
    canonical_target: target,
    display_target: clean(metadata.channelName || metadata.topicName || metadata.senderName || target),
    sender,
    sender_id: sender,
    sender_name: clean(metadata.senderName || metadata.senderUsername || sender),
    text,
    body: text,
    message_id: clean(event?.messageId || metadata.messageId || ctx?.messageId),
    conversation_id: clean(ctx?.conversationId || metadata.originatingTo || metadata.groupId || target),
    timestamp: event?.timestamp || Date.now(),
    account_id: clean(ctx?.accountId),
    session_key: clean(ctx?.sessionKey || event?.sessionKey),
    metadata,
  };
  if (config.includeRaw) {
    payload.raw_event = event;
    payload.raw_context = ctx;
  }
  return payload;
}

async function postToJarvis(payload, config) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), Math.max(250, config.timeoutMs || 2000));
  const headers = { "Content-Type": "application/json" };

  try {
    const response = await fetch(config.endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`Jarvis inbound endpoint returned HTTP ${response.status}`);
    }
  } finally {
    clearTimeout(timeout);
  }
}

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "Jarvis WhatsApp Forwarder",
  description: "Forwards OpenClaw WhatsApp inbound hooks to Jarvis.",
  register(api) {
    api.on("message_received", async (event, ctx) => {
      if (!isWhatsApp(ctx, event)) return;
      const config = readConfig(api);
      const payload = buildPayload(event, ctx, config);
      if (!payload.target && !payload.sender && !payload.text) return;
      try {
        await postToJarvis(payload, config);
      } catch (err) {
        api.logger.warn?.(`jarvis-whatsapp-forwarder: failed to forward inbound WhatsApp event: ${String(err?.message || err)}`);
      }
    });

    api.on("before_dispatch", async (event, ctx) => {
      if (!isWhatsApp(ctx, event)) return;
      const config = readConfig(api);
      if (config.blockOpenClawReplies) {
        return { handled: true };
      }
    });
  },
});
