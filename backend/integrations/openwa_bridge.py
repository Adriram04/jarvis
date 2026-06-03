import asyncio
import os
import re
import json


OPENWA_MESSAGE_ACTIONS = {
    "send_message",
    "send_whatsapp_message",
    "autopilot_reply",
}

OPENWA_IMAGE_ACTIONS = {
    "send_image",
    "send_whatsapp_image",
}


class OpenWABridge:
    """Bridge from JARVIS to an external OpenWA REST service.

    Handles WhatsApp session management and message sending via OpenWA's
    HTTP API. Only used for WhatsApp — Calendar, LinkedIn, email and other
    productivity actions continue to go through OpenClawBridge.

    IMPORTANT: OpenWA identifies sessions by UUID in its internal engine Map.
    The :sessionId URL parameter in /sessions/{id}/messages/... must be the
    UUID, not the friendly name. We resolve the UUID once and cache it.
    """

    def __init__(self):
        self.enabled = self._env_bool("JARVIS_OPENWA_ENABLED", False)
        self.base_url = os.getenv("JARVIS_OPENWA_BASE_URL", "http://127.0.0.1:2785/api").rstrip("/")
        self.api_key = os.getenv("JARVIS_OPENWA_API_KEY", "").strip()
        self.session_id = os.getenv("JARVIS_OPENWA_SESSION_ID", "jarvis-main").strip() or "jarvis-main"
        self.timeout_seconds = float(os.getenv("JARVIS_OPENWA_TIMEOUT_SECONDS", "30") or 30)
        self.send_style = os.getenv("JARVIS_OPENWA_SEND_STYLE", "send-text").strip() or "send-text"
        # Resolved UUID for the configured session name (lazy, cached after first call)
        self._cached_session_uuid = None

    def is_enabled(self):
        return self.enabled

    def _has_api_key(self):
        return bool(self.api_key)

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    # ------------------------------------------------------------------
    # Session UUID resolution
    # The OpenWA engine Map stores engines by session UUID, not by name.
    # /sessions/{id}/messages/send-text → {id} must be the UUID.
    # We resolve once and cache for the lifetime of this bridge instance.
    # ------------------------------------------------------------------

    async def _get_session_uuid(self):
        """Return the UUID for the configured session name, resolving if needed."""
        if self._cached_session_uuid:
            return self._cached_session_uuid

        raw = await self._http_get("/sessions")
        sessions = raw.get("json") if isinstance(raw, dict) else None
        if isinstance(sessions, list):
            for s in sessions:
                if not isinstance(s, dict):
                    continue
                if s.get("name") == self.session_id:
                    uuid = s.get("id")
                    if uuid:
                        self._cached_session_uuid = uuid
                        return uuid
                # Also match if the configured value IS already a UUID
                if s.get("id") == self.session_id:
                    self._cached_session_uuid = self.session_id
                    return self.session_id

        # Fallback: use as-is (works when session_id is already a UUID)
        return self.session_id

    def _invalidate_session_cache(self):
        self._cached_session_uuid = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_status(self):
        if not self.enabled:
            return {
                "available": False,
                "provider": "openwa",
                "service": "openwa",
                "base_url": self.base_url,
                "session_id": self.session_id,
                "message": "OpenWA no está habilitado (JARVIS_OPENWA_ENABLED=false).",
                "raw": None,
            }
        if not self._has_api_key():
            return {
                "available": False,
                "provider": "openwa",
                "service": "openwa",
                "base_url": self.base_url,
                "session_id": self.session_id,
                "message": "Falta JARVIS_OPENWA_API_KEY.",
                "raw": None,
            }
        raw = await self._http_get("/health")
        available = bool(raw.get("success")) if isinstance(raw, dict) else False
        status_text = None
        if isinstance(raw, dict):
            data = raw.get("json") or {}
            status_text = (
                data.get("status")
                or data.get("message")
                or raw.get("text", "")
            )
        return {
            "available": available,
            "provider": "openwa",
            "service": "openwa",
            "base_url": self.base_url,
            "session_id": self.session_id,
            "message": status_text or ("OpenWA activo." if available else "OpenWA no responde."),
            "raw": raw,
        }

    async def create_session(self, name=None):
        session_name = name or self.session_id
        raw = await self._http_post("/sessions", {"name": session_name})
        result = self._normalize_session_result("create_session", raw, session_name)
        # Invalidate UUID cache after creating (new session = new UUID)
        if result.get("success"):
            self._invalidate_session_cache()
        return result

    async def start_session(self, session_id=None):
        sid = await self._get_session_uuid() if not session_id else session_id
        raw = await self._http_post(f"/sessions/{sid}/start", {})
        return self._normalize_session_result("start_session", raw, sid)

    async def get_qr(self, session_id=None):
        sid = await self._get_session_uuid() if not session_id else session_id
        raw = await self._http_get(f"/sessions/{sid}/qr")
        success = bool(isinstance(raw, dict) and raw.get("success"))
        data = raw.get("json") if isinstance(raw, dict) else None
        # OpenWA returns {qrCode: "..."} (camelCase)
        qr_value = None
        if isinstance(data, dict):
            qr_value = data.get("qrCode") or data.get("qr") or data.get("value")
        return {
            "success": success,
            "provider": "openwa",
            "service": "openwa",
            "action_type": "get_qr",
            "session_id": sid,
            "qr": qr_value,
            "raw": raw,
        }

    async def get_contacts(self):
        """Return all contacts from the active OpenWA session."""
        if not self.enabled:
            return {"success": False, "contacts": [], "summary": "OpenWA no está habilitado."}
        sid = await self._get_session_uuid()
        raw = await self._http_get(f"/sessions/{sid}/contacts")
        success = bool(isinstance(raw, dict) and raw.get("success"))
        contacts = []
        data = raw.get("json") if isinstance(raw, dict) else None
        if isinstance(data, list):
            contacts = data
        elif isinstance(data, dict):
            contacts = data.get("contacts") or data.get("data") or []
        return {
            "success": success,
            "provider": "openwa",
            "contacts": contacts,
            "count": len(contacts),
            "summary": f"{len(contacts)} contacto(s) obtenidos." if success else self._extract_error_message(raw),
        }

    async def get_groups(self):
        """Return all groups the active session belongs to."""
        if not self.enabled:
            return {"success": False, "groups": [], "summary": "OpenWA no está habilitado."}
        sid = await self._get_session_uuid()
        raw = await self._http_get(f"/sessions/{sid}/groups")
        success = bool(isinstance(raw, dict) and raw.get("success"))
        groups = []
        data = raw.get("json") if isinstance(raw, dict) else None
        if isinstance(data, list):
            groups = data
        elif isinstance(data, dict):
            groups = data.get("groups") or data.get("data") or []
        return {
            "success": success,
            "provider": "openwa",
            "groups": groups,
            "count": len(groups),
            "summary": f"{len(groups)} grupo(s) obtenidos." if success else self._extract_error_message(raw),
        }

    async def send_image(
        self,
        target,
        image_url=None,
        base64_data=None,
        caption=None,
        canonical_target=None,
        mimetype="image/jpeg",
        metadata=None,
    ):
        """Send an image to a WhatsApp target. Provide either image_url or base64_data."""
        if not self.enabled:
            return self._disabled_result("send_image")
        if not self._has_api_key():
            return self._no_key_result("send_image")
        if not image_url and not base64_data:
            return {
                "success": False, "service": "openwa", "provider": "openwa",
                "action_type": "send_image", "target": target,
                "summary": "Falta image_url o base64 para enviar la imagen.",
            }

        chat_id = self._normalize_target(target, canonical_target)
        if not chat_id:
            return {
                "success": False, "service": "openwa", "provider": "openwa",
                "action_type": "send_image", "target": target,
                "summary": "No se pudo determinar el destinatario.",
            }

        sid = await self._get_session_uuid()
        body = {"chatId": chat_id}
        if image_url:
            body["url"] = image_url
        if base64_data:
            body["base64"] = base64_data
            body["mimetype"] = mimetype
        if caption:
            body["caption"] = str(caption).strip()

        raw = await self._http_post(f"/sessions/{sid}/messages/send-image", body)

        # Retry once if UUID is stale
        if not isinstance(raw, dict) or not raw.get("success"):
            err = self._raw_error_text(raw).lower()
            if "not active" in err or "not found" in err or "session" in err:
                self._invalidate_session_cache()
                sid2 = await self._get_session_uuid()
                if sid2 != sid:
                    raw = await self._http_post(f"/sessions/{sid2}/messages/send-image", body)

        success = bool(isinstance(raw, dict) and raw.get("success"))
        return {
            "success": success,
            "service": "openwa",
            "provider": "openwa",
            "action_type": "send_image",
            "target": target,
            "canonical_target": chat_id,
            "summary": f"Imagen enviada a {chat_id}." if success else self._extract_error_message(raw),
            "raw": raw,
        }

    async def send_message(self, target, message, canonical_target=None, metadata=None):
        if not self.enabled:
            return self._disabled_result("send_message")
        if not self._has_api_key():
            return self._no_key_result("send_message")

        chat_id = self._normalize_target(target, canonical_target)
        if not chat_id:
            return {
                "success": False,
                "service": "openwa",
                "provider": "openwa",
                "action_type": "send_message",
                "target": target,
                "canonical_target": canonical_target,
                "summary": "No se pudo determinar el destinatario (target inválido o sin número de teléfono válido).",
                "raw": None,
            }
        if not message or not str(message).strip():
            return {
                "success": False,
                "service": "openwa",
                "provider": "openwa",
                "action_type": "send_message",
                "target": target,
                "canonical_target": canonical_target,
                "summary": "Falta el contenido del mensaje.",
                "raw": None,
            }

        # Resolve the session UUID (critical: OpenWA engine Map uses UUID keys)
        sid = await self._get_session_uuid()
        raw = await self._try_send_message(sid, chat_id, str(message))
        success = bool(isinstance(raw, dict) and raw.get("success"))

        # If "not active" error, maybe the cached UUID is stale — invalidate and retry once
        if not success and isinstance(raw, dict):
            err_text = self._raw_error_text(raw).lower()
            if "not active" in err_text or "not found" in err_text or "session" in err_text:
                self._invalidate_session_cache()
                sid2 = await self._get_session_uuid()
                if sid2 != sid:
                    raw = await self._try_send_message(sid2, chat_id, str(message))
                    success = bool(isinstance(raw, dict) and raw.get("success"))
                    sid = sid2

        summary = f"Mensaje enviado a {chat_id}." if success else self._extract_error_message(raw)
        return {
            "success": success,
            "service": "openwa",
            "provider": "openwa",
            "action_type": "send_message",
            "target": target,
            "canonical_target": chat_id,
            "summary": summary,
            "raw": raw,
        }

    async def ensure_webhook_configured(self, webhook_url, session_id=None):
        """
        Ensure a webhook pointing to JARVIS exists on OpenWA for message.received events.
        Creates it if missing; does nothing if the URL is already registered.
        """
        if not self.enabled or not self._has_api_key():
            return {"success": False, "action": "skipped", "message": "OpenWA no habilitado o sin API key."}

        uuid = session_id or await self._get_session_uuid()

        raw_list = await self._http_get(f"/sessions/{uuid}/webhooks")
        existing_webhooks = []
        if isinstance(raw_list, dict):
            data = raw_list.get("json")
            if isinstance(data, list):
                existing_webhooks = data

        for wh in existing_webhooks:
            if isinstance(wh, dict) and wh.get("url") == webhook_url:
                return {
                    "success": True,
                    "action": "already_configured",
                    "webhook_id": wh.get("id"),
                    "message": f"Webhook ya configurado -> {webhook_url}",
                }

        create_raw = await self._http_post(f"/sessions/{uuid}/webhooks", {
            "url": webhook_url,
            "events": ["message.received", "session.connected", "session.disconnected"],
        })
        success = bool(isinstance(create_raw, dict) and create_raw.get("success"))
        wh_data = create_raw.get("json") if isinstance(create_raw, dict) else {}
        return {
            "success": success,
            "action": "created" if success else "failed",
            "webhook_id": (wh_data or {}).get("id") if isinstance(wh_data, dict) else None,
            "message": (
                f"Webhook registrado -> {webhook_url}" if success
                else f"No se pudo crear el webhook: {self._extract_error_message(create_raw)}"
            ),
        }

    async def get_session_info(self, session_id=None):
        """Return the OpenWA session object (with status field) or {} if not found."""
        uuid = session_id or await self._get_session_uuid()
        raw = await self._http_get(f"/sessions/{uuid}")
        if not isinstance(raw, dict) or raw.get("status") == 404:
            return {}
        data = raw.get("json")
        return data if isinstance(data, dict) else {}

    async def ensure_session_active(self, session_id=None):
        """
        Ensure the OpenWA session exists and is started.

        - Creates the session if it doesn't exist.
        - Starts it if it's disconnected/idle/created.
        - Does nothing if it's already initializing/connecting/qr_ready/ready.

        Returns a summary dict with keys: success, message, action, session_status.
        """
        if not self.enabled:
            return {"success": False, "message": "OpenWA no está habilitado.", "action": "skipped"}
        if not self._has_api_key():
            return {"success": False, "message": "Falta JARVIS_OPENWA_API_KEY.", "action": "skipped"}

        target_name = session_id or self.session_id

        # List all sessions to find ours by name
        raw_list = await self._http_get("/sessions")
        sessions = raw_list.get("json") if isinstance(raw_list, dict) else None

        existing = None
        if isinstance(sessions, list):
            for s in sessions:
                if not isinstance(s, dict):
                    continue
                if s.get("name") == target_name:
                    existing = s
                    uuid = s.get("id")
                    if uuid:
                        self._cached_session_uuid = uuid
                    break

        ACTIVE = {"ready"}
        IN_PROGRESS = {"initializing", "connecting", "qr_ready", "authenticating"}

        if existing is None:
            # Session doesn't exist — create it
            create_raw = await self._http_post("/sessions", {"name": target_name})
            if not isinstance(create_raw, dict) or not create_raw.get("success"):
                return {
                    "success": False,
                    "message": f"No se pudo crear la sesión '{target_name}': {self._extract_error_message(create_raw)}",
                    "action": "create_failed",
                }
            create_data = create_raw.get("json") or {}
            uuid = create_data.get("id") if isinstance(create_data, dict) else None
            if uuid:
                self._cached_session_uuid = uuid
            else:
                self._invalidate_session_cache()
                uuid = await self._get_session_uuid()

            start_raw = await self._http_post(f"/sessions/{uuid}/start", {})
            new_status = ((start_raw.get("json") or {}).get("status") or "starting") if isinstance(start_raw, dict) else "starting"
            return {
                "success": True,
                "message": f"Sesión '{target_name}' creada e iniciada. Estado: {new_status}.",
                "action": "created_and_started",
                "session_status": new_status,
            }

        current_status = str(existing.get("status") or "").lower()

        if current_status in ACTIVE:
            return {
                "success": True,
                "message": f"Sesión '{target_name}' ya está activa.",
                "action": "already_active",
                "session_status": current_status,
            }

        if current_status in IN_PROGRESS:
            return {
                "success": True,
                "message": f"Sesión '{target_name}' en proceso ({current_status}).",
                "action": "in_progress",
                "session_status": current_status,
            }

        # disconnected / idle / created → start it
        uuid = existing.get("id") or await self._get_session_uuid()
        start_raw = await self._http_post(f"/sessions/{uuid}/start", {})
        if isinstance(start_raw, dict) and not start_raw.get("success"):
            err_text = self._raw_error_text(start_raw).lower()
            if "already started" in err_text or "already running" in err_text:
                return {
                    "success": True,
                    "message": f"Sesión '{target_name}' ya estaba iniciada.",
                    "action": "already_started",
                    "session_status": current_status,
                }
            return {
                "success": False,
                "message": f"No se pudo reiniciar '{target_name}': {self._extract_error_message(start_raw)}",
                "action": "start_failed",
                "session_status": current_status,
            }
        new_status = ((start_raw.get("json") or {}).get("status") or "starting") if isinstance(start_raw, dict) else "starting"
        return {
            "success": True,
            "message": f"Sesión '{target_name}' iniciada desde estado '{current_status}'. Nuevo: {new_status}.",
            "action": "started",
            "session_status": new_status,
        }

    async def execute_action(self, action_type, payload):
        action_type = str(action_type or "").strip()
        payload = dict(payload or {}) if isinstance(payload, dict) else {}

        if action_type in OPENWA_MESSAGE_ACTIONS:
            return await self._dispatch_send(action_type, payload)

        if action_type in OPENWA_IMAGE_ACTIONS:
            return await self._dispatch_send_image(action_type, payload)

        if action_type == "openclaw_send_message":
            channel = str(payload.get("channel") or "").strip().lower()
            if channel == "whatsapp":
                return await self._dispatch_send(action_type, payload)

        if action_type == "openclaw_send_image":
            return await self._dispatch_send_image(action_type, payload)

        return {
            "success": False,
            "service": "openwa",
            "provider": "openwa",
            "action_type": action_type,
            "summary": f"Acción '{action_type}' no soportada por OpenWABridge. Usa OpenClawBridge para acciones no-WhatsApp.",
            "raw": None,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _dispatch_send(self, action_type, payload):
        target = payload.get("target") or payload.get("contact")
        canonical_target = payload.get("canonical_target") or payload.get("canonicalTarget")
        message = payload.get("message") or payload.get("text")
        result = await self.send_message(target, message, canonical_target=canonical_target, metadata=payload)
        result["action_type"] = action_type
        return result

    async def _dispatch_send_image(self, action_type, payload):
        target = payload.get("target") or payload.get("contact")
        canonical_target = payload.get("canonical_target") or payload.get("canonicalTarget")
        image_url = payload.get("image_url") or payload.get("url") or payload.get("imageUrl")
        base64_data = payload.get("base64") or payload.get("image_base64")
        caption = payload.get("caption") or payload.get("message") or payload.get("text") or ""
        mimetype = payload.get("mimetype", "image/jpeg")
        result = await self.send_image(
            target,
            image_url=image_url,
            base64_data=base64_data,
            caption=caption,
            canonical_target=canonical_target,
            mimetype=mimetype,
            metadata=payload,
        )
        result["action_type"] = action_type
        return result

    async def _try_send_message(self, session_uuid, chat_id, text):
        """Attempt to send using the primary endpoint, with fallback if 404."""
        if self.send_style == "send-text":
            raw = await self._http_post(
                f"/sessions/{session_uuid}/messages/send-text",
                {"chatId": chat_id, "text": text},
            )
            # Fallback to /messages only if 404 (endpoint not found)
            if isinstance(raw, dict) and raw.get("status") == 404:
                raw = await self._http_post(
                    f"/sessions/{session_uuid}/messages",
                    {"phone": chat_id, "type": "text", "body": text},
                )
            return raw
        # Direct /messages endpoint
        return await self._http_post(
            f"/sessions/{session_uuid}/messages",
            {"phone": chat_id, "type": "text", "body": text},
        )

    def _normalize_target(self, target, canonical_target=None):
        """Normalise a phone number / chat ID to WhatsApp format (e.g. 34600111222@c.us)."""
        for candidate in (canonical_target, target):
            if not candidate:
                continue
            candidate = str(candidate).strip()
            if candidate.endswith("@c.us") or candidate.endswith("@g.us"):
                return candidate

        for candidate in (canonical_target, target):
            if not candidate:
                continue
            digits = re.sub(r"[^\d]", "", str(candidate))
            if len(digits) >= 7:
                return f"{digits}@c.us"

        return None

    async def _http_get(self, path, timeout=None):
        url = self.base_url + (path if path.startswith("/") else f"/{path}")
        try:
            import aiohttp
            client_timeout = aiohttp.ClientTimeout(total=timeout or self.timeout_seconds)
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.get(url, headers=self._headers()) as resp:
                    return await self._parse_response(resp)
        except asyncio.TimeoutError:
            return self._unavailable_raw("OpenWA GET timed out.", status=None)
        except Exception as exc:
            return self._unavailable_raw(f"OpenWA GET failed: {self._safe_str(exc)}", status=None)

    async def _http_post(self, path, data, timeout=None):
        url = self.base_url + (path if path.startswith("/") else f"/{path}")
        try:
            import aiohttp
            client_timeout = aiohttp.ClientTimeout(total=timeout or self.timeout_seconds)
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.post(url, json=data, headers=self._headers()) as resp:
                    return await self._parse_response(resp)
        except asyncio.TimeoutError:
            return self._unavailable_raw("OpenWA POST timed out.", status=None)
        except Exception as exc:
            return self._unavailable_raw(f"OpenWA POST failed: {self._safe_str(exc)}", status=None)

    @staticmethod
    async def _parse_response(resp):
        status = resp.status
        try:
            text = await resp.text()
        except Exception:
            text = ""
        raw = {"success": 200 <= status < 300, "status": status, "text": text}
        try:
            raw["json"] = json.loads(text) if text else None
        except Exception:
            raw["json"] = None
        return raw

    def _normalize_session_result(self, action_type, raw, session_id):
        success = bool(isinstance(raw, dict) and raw.get("success"))
        data = raw.get("json") if isinstance(raw, dict) else None
        return {
            "success": success,
            "provider": "openwa",
            "service": "openwa",
            "action_type": action_type,
            "session_id": session_id,
            "summary": "OK" if success else self._extract_error_message(raw),
            "raw": raw,
            "data": data,
        }

    def _raw_error_text(self, raw):
        """Extract a flat error string from a raw response for quick checks."""
        if not isinstance(raw, dict):
            return ""
        data = raw.get("json") or {}
        if isinstance(data, dict):
            return str(data.get("message") or data.get("error") or "")
        return str(raw.get("text", ""))

    def _extract_error_message(self, raw):
        if not isinstance(raw, dict):
            return "OpenWA no disponible."
        data = raw.get("json") or {}
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error") or data.get("detail")
            if msg:
                return str(msg)[:300]
        status = raw.get("status")
        if status == 401:
            return "OpenWA: API key inválida o no autorizada (401)."
        if status == 403:
            return "OpenWA: Acceso denegado (403)."
        if status == 404:
            return "OpenWA: Recurso no encontrado (404). Comprueba session_id."
        if status == 400:
            return f"OpenWA: Solicitud inválida (400). {raw.get('text', '')[:200]}"
        if status == 500:
            return "OpenWA: Error interno del servidor (500)."
        if isinstance(raw, dict) and raw.get("unavailable"):
            return raw.get("summary", "OpenWA no disponible.")
        return raw.get("text", "OpenWA no respondió correctamente.")[:200]

    def _disabled_result(self, action_type):
        return {
            "success": False,
            "service": "openwa",
            "provider": "openwa",
            "action_type": action_type,
            "summary": "OpenWA no está habilitado (JARVIS_OPENWA_ENABLED=false).",
            "raw": None,
        }

    def _no_key_result(self, action_type):
        return {
            "success": False,
            "service": "openwa",
            "provider": "openwa",
            "action_type": action_type,
            "summary": "Falta JARVIS_OPENWA_API_KEY. Configura la clave API en .env.",
            "raw": None,
        }

    @staticmethod
    def _unavailable_raw(summary, status=None):
        return {"success": False, "status": status, "unavailable": True, "summary": summary, "text": "", "json": None}

    @staticmethod
    def _safe_str(value, max_length=300):
        return str(value or "")[:max_length]

    @staticmethod
    def _env_bool(name, default=False):
        raw = os.getenv(name)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}


openwa_bridge = OpenWABridge()
