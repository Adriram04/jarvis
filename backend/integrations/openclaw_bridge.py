import asyncio
import json
import os
from copy import deepcopy


INTERNAL_OPENCLAW_INSTRUCTION = (
    "Eres una herramienta interna invocada por J.A.R.V.I.S. No eres el asistente final "
    "del usuario. No debes responder al usuario directamente. Ejecuta unicamente la accion "
    "solicitada mediante los canales, skills o workflows disponibles en OpenClaw. Jarvis "
    "sera quien redacte la respuesta final al usuario.\n\n"
    "No tomes decisiones fuera del payload. No envies mensajes, correos, publicaciones, "
    "invitaciones ni respuestas automaticas salvo que el payload indique que la accion fue "
    "confirmada o que existe una regla activa autorizada por el usuario. Devuelve siempre "
    "un resultado estructurado en JSON."
)

EXPECTED_OPENCLAW_SCHEMA = {
    "success": True,
    "action_done": "...",
    "details": "...",
    "external_id": "...",
    "warnings": [],
}

SECRET_KEYWORDS = ("token", "secret", "password", "credential", "api_key", "apikey", "authorization", "cookie")
MESSAGE_ACTIONS = {"send_message", "send_whatsapp_message", "send_channel_message", "autopilot_reply"}
MESSAGE_READ_ACTIONS = {"read_conversation", "list_messages"}
PRODUCTIVITY_ACTIONS = {
    "list_calendar_events",
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
    "prepare_social_post",
    "schedule_social_post",
    "publish_social_post",
}
GENERIC_SUPPORTED_ACTIONS = {
    "search_email",
    "draft_email",
    "send_email",
    "reply_email",
    "list_calendar_events",
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
    "prepare_social_post",
    "schedule_social_post",
    "publish_social_post",
    "run_workflow",
    "search_items",
    "draft_content",
}


class OpenClawBridge:
    """Generic gateway from Jarvis to the real OpenClaw CLI or legacy HTTP mode."""

    def __init__(self):
        self.enabled = self._env_bool("JARVIS_OPENCLAW_ENABLED", False)
        self.mode = os.getenv("JARVIS_OPENCLAW_MODE", "cli").strip().lower()
        self.executable = os.getenv("JARVIS_OPENCLAW_EXECUTABLE", "openclaw").strip() or "openclaw"
        self.timeout_seconds = float(os.getenv("JARVIS_OPENCLAW_TIMEOUT_SECONDS", "60") or 60)

        self.status_method = os.getenv("JARVIS_OPENCLAW_STATUS_METHOD", "health").strip() or "health"
        self.status_fallback_method = os.getenv("JARVIS_OPENCLAW_STATUS_FALLBACK_METHOD", "status").strip() or "status"
        self.gateway_url = os.getenv("JARVIS_OPENCLAW_GATEWAY_URL", "").strip()
        self.gateway_token = os.getenv("JARVIS_OPENCLAW_GATEWAY_TOKEN", "").strip()
        self.message_command = self._csv_env("JARVIS_OPENCLAW_MESSAGE_COMMAND", ["message", "send"])
        self.resolve_command = self._csv_env("JARVIS_OPENCLAW_RESOLVE_COMMAND", ["channels", "resolve"])
        self.generic_call_method = os.getenv("JARVIS_OPENCLAW_GENERIC_CALL_METHOD", "").strip()
        self.productivity_call_method = os.getenv(
            "JARVIS_OPENCLAW_PRODUCTIVITY_CALL_METHOD",
            "jarvis.productivity.execute",
        ).strip()
        self.require_resolve = self._env_bool("JARVIS_OPENCLAW_REQUIRE_RESOLVE", False)

        # Legacy HTTP compatibility.
        self.base_url = os.getenv("JARVIS_OPENCLAW_BASE_URL", "http://localhost:18789").rstrip("/")
        self.action_path = os.getenv("JARVIS_OPENCLAW_ACTION_PATH", "/run")
        self.status_path = os.getenv("JARVIS_OPENCLAW_STATUS_PATH", "/status")

    def is_enabled(self):
        return self.enabled

    async def check_status(self):
        if not self.is_enabled():
            return self._disabled_result("check_status")

        if self.mode == "http":
            raw = await self._post_http(self.status_path, {"ping": True}, min(self.timeout_seconds, 20))
            return self._normalize_result(raw, "check_status")

        timeout = min(self.timeout_seconds, 20)
        raw = await self._run_cli(self._build_gateway_call_args(self.status_method), timeout)
        result = self._normalize_result(raw, "check_status")
        if result.get("success"):
            return result

        fallback_raw = await self._run_cli(self._build_gateway_call_args(self.status_fallback_method), timeout)
        return self._normalize_result(fallback_raw, "check_status")

    async def execute_action(self, action_type, payload):
        action_type = str(action_type or "").strip()
        payload = self._normalize_action_payload(action_type, payload or {})

        if not self.is_enabled():
            return self._disabled_result(action_type)

        if action_type == "check_status":
            return await self.check_status()

        if self.mode == "http":
            raw = await self._post_http(self.action_path, self._build_internal_instruction(action_type, payload), self.timeout_seconds)
            return self._normalize_result(raw, action_type)

        if action_type in MESSAGE_ACTIONS:
            return await self._send_message_action(action_type, payload)

        if action_type in MESSAGE_READ_ACTIONS:
            return await self._read_messages_action(action_type, payload)

        if action_type in PRODUCTIVITY_ACTIONS:
            return await self._productivity_gateway_action(action_type, payload)

        if action_type in GENERIC_SUPPORTED_ACTIONS:
            return await self._generic_gateway_action(action_type, payload)

        return self._missing_method_result(action_type)

    def _normalize_action_payload(self, action_type, payload):
        payload = deepcopy(payload or {}) if isinstance(payload, dict) else {}

        if action_type in {"create_calendar_event", "update_calendar_event", "delete_calendar_event"}:
            nested = payload.get("payload")
            if isinstance(nested, dict):
                metadata = {
                    key: value
                    for key, value in payload.items()
                    if key not in {"payload", "calendar_action"}
                }
                payload = {**metadata, **nested}

            for key in ("start", "end", "start_time", "end_time", "startTime", "endTime"):
                value = payload.get(key)
                if isinstance(value, dict):
                    payload[key] = (
                        value.get("dateTime")
                        or value.get("date_time")
                        or value.get("datetime")
                        or value.get("date")
                        or value.get("value")
                    )

            if payload.get("summary") and not payload.get("title"):
                payload["title"] = payload.get("summary")
            if payload.get("timeZone") and not payload.get("time_zone"):
                payload["time_zone"] = payload.get("timeZone")

        return payload

    async def execute_autopilot_reply(self, rule, incoming_message):
        incoming_message = incoming_message or {}
        payload = {
            "channel": incoming_message.get("channel") or (rule or {}).get("channel") or "whatsapp",
            "target": incoming_message.get("target") or (rule or {}).get("target"),
            "canonical_target": incoming_message.get("canonical_target") or incoming_message.get("target") or (rule or {}).get("target"),
            "display_target": incoming_message.get("display_target") or (rule or {}).get("display_target"),
            "kind": incoming_message.get("kind") or (rule or {}).get("kind", "auto"),
            "message": incoming_message.get("outgoing_message") or incoming_message.get("reply") or incoming_message.get("message"),
            "confirmed_by_active_rule": True,
        }
        return await self._send_message_action("autopilot_reply", payload)

    async def send_message(
        self,
        channel="whatsapp",
        target=None,
        message=None,
        canonical_target=None,
        display_target=None,
        kind="auto",
        dry_run=False,
    ):
        return await self.execute_action("send_message", {
            "channel": channel,
            "target": target,
            "message": message,
            "canonical_target": canonical_target,
            "display_target": display_target,
            "kind": kind,
            "dry_run": dry_run,
        })

    async def send_channel_message(self, channel="whatsapp", target=None, message=None, **kwargs):
        return await self.execute_action("send_channel_message", {
            "channel": channel,
            "target": target,
            "message": message,
            **(kwargs or {}),
        })

    async def directory_self(self, channel="whatsapp", account=None):
        if not self.is_enabled():
            return self._disabled_result("directory_self")

        args = ["directory", "self", "--channel", str(channel or "whatsapp")]
        if account:
            args.extend(["--account", str(account)])
        args.append("--json")
        raw = await self._run_cli(args, self.timeout_seconds)
        return self._normalize_result(raw, "directory_self")

    async def directory_peers(self, channel="whatsapp", query=None, limit=50, account=None):
        if not self.is_enabled():
            return self._disabled_result("directory_peers")

        args = ["directory", "peers", "list", "--channel", str(channel or "whatsapp"), "--limit", str(int(limit or 50))]
        if query:
            args.extend(["--query", str(query)])
        if account:
            args.extend(["--account", str(account)])
        args.append("--json")
        raw = await self._run_cli(args, self.timeout_seconds)
        return self._normalize_result(raw, "directory_peers")

    async def directory_groups(self, channel="whatsapp", query=None, limit=50, account=None):
        if not self.is_enabled():
            return self._disabled_result("directory_groups")

        args = ["directory", "groups", "list", "--channel", str(channel or "whatsapp"), "--limit", str(int(limit or 50))]
        if query:
            args.extend(["--query", str(query)])
        if account:
            args.extend(["--account", str(account)])
        args.append("--json")
        raw = await self._run_cli(args, self.timeout_seconds)
        return self._normalize_result(raw, "directory_groups")

    async def read_conversation(
        self,
        channel,
        target,
        limit=10,
        before=None,
        after=None,
        around=None,
        message_id=None,
        thread_id=None,
    ):
        return await self.execute_action("read_conversation", {
            "channel": channel,
            "target": target,
            "limit": int(limit),
            "before": before,
            "after": after,
            "around": around,
            "message_id": message_id,
            "thread_id": thread_id,
        })

    async def list_messages(self, channel, target, limit=10, **kwargs):
        if self._is_whatsapp_channel(channel):
            return {
                "success": False,
                "service": "openclaw",
                "action_type": "list_messages",
                "summary": "WhatsApp no soporta lectura de historial mediante OpenClaw. Usa mensajes inbound guardados en Jarvis.",
                "error": "WhatsApp no soporta lectura de historial mediante OpenClaw. Usa mensajes inbound guardados en Jarvis.",
                "code": "OPENCLAW_WHATSAPP_READ_UNSUPPORTED",
                "raw": None,
                "external_id": None,
                "warnings": ["read_unsupported"],
            }
        return await self.read_conversation(channel, target, limit=limit, **(kwargs or {}))

    async def search_items(self, service, query, max_results=10):
        return await self.execute_action("search_items", {
            "service": service,
            "query": query,
            "max_results": int(max_results),
        })

    async def draft_content(self, service, payload):
        return await self.execute_action("draft_content", {
            "service": service,
            "payload": payload or {},
        })

    async def send_email_like_action(self, payload):
        return await self.execute_action((payload or {}).get("action_type", "send_email"), payload or {})

    async def calendar_action(self, action, payload):
        return await self.execute_action(self._calendar_action_type(action), {
            "calendar_action": action,
            "payload": payload or {},
        })

    async def social_action(self, action, payload):
        return await self.execute_action(self._social_action_type(action), {
            "social_action": action,
            "payload": payload or {},
        })

    async def run_workflow(self, workflow_name, payload):
        return await self.execute_action("run_workflow", {
            "workflow_name": workflow_name,
            "payload": payload or {},
        })

    async def resolve_target(self, channel, target, kind="auto", account=None):
        if not self.is_enabled():
            return self._disabled_result("resolve_target")

        args = [
            *self.resolve_command,
            "--channel",
            str(channel or "whatsapp"),
            "--kind",
            str(kind or "auto"),
        ]
        if account:
            args.extend(["--account", str(account)])
        args.extend([str(target or ""), "--json"])
        raw = await self._run_cli(args, self.timeout_seconds)
        return self._normalize_result(raw, "resolve_target")

    async def _send_message_action(self, action_type, payload):
        payload = payload or {}
        channel = payload.get("channel")
        if not channel and action_type in {"send_whatsapp_message", "autopilot_reply"}:
            channel = "whatsapp"
        channel = channel or "whatsapp"
        target = payload.get("target") or payload.get("contact")
        canonical_target = payload.get("canonical_target") or payload.get("canonicalTarget")
        display_target = payload.get("display_target") or payload.get("displayTarget") or target
        real_target = canonical_target or target
        message = payload.get("message") or payload.get("text")

        if not real_target:
            return self._validation_result(action_type, "Falta el destinatario del mensaje.", "missing_target")
        if not message:
            return self._validation_result(action_type, "Falta el contenido del mensaje.", "missing_message")

        if self.require_resolve and not self._is_whatsapp_channel(channel):
            resolved = await self.resolve_target(channel, real_target, payload.get("kind", "auto"), payload.get("account"))
            if not resolved.get("success"):
                return resolved

        args = [
            *self.message_command,
            "--channel",
            str(channel),
            "--target",
            str(real_target),
            "--message",
            str(message),
            "--json",
        ]
        if payload.get("dry_run") is True or str(payload.get("dry_run")).strip().lower() in {"1", "true", "yes", "on"}:
            args.append("--dry-run")
        raw = await self._run_cli(args, self.timeout_seconds)
        result = self._normalize_result(raw, action_type)
        if result.get("success"):
            result["summary"] = f"Mensaje enviado mediante {channel} a {display_target or real_target}."
        return result

    async def _read_messages_action(self, action_type, payload):
        payload = payload or {}
        channel = payload.get("channel") or "whatsapp"
        target = payload.get("target") or payload.get("contact")
        limit = payload.get("limit", 10)

        args = ["message", "read", "--channel", str(channel)]
        if target:
            args.extend(["--target", str(target)])
        args.extend(["--limit", str(int(limit or 10))])
        for flag, key in (
            ("--before", "before"),
            ("--after", "after"),
            ("--around", "around"),
            ("--message-id", "message_id"),
            ("--thread-id", "thread_id"),
        ):
            if payload.get(key):
                args.extend([flag, str(payload.get(key))])
        args.append("--json")
        raw = await self._run_cli(args, self.timeout_seconds)
        result = self._normalize_result(raw, action_type)

        if not result.get("success") and self._contains_text(raw, "unknown command"):
            return {
                "success": False,
                "service": "openclaw",
                "action_type": action_type,
                "summary": "La lectura de conversaciones aun no esta soportada por el comando OpenClaw disponible.",
                "raw": self._redact(deepcopy(raw)),
                "external_id": None,
                "warnings": ["unsupported_message_read"],
            }
        return result

    async def _generic_gateway_action(self, action_type, payload):
        if not self.generic_call_method:
            return self._missing_method_result(action_type)

        params = {
            "instruction": INTERNAL_OPENCLAW_INSTRUCTION,
            "action_type": action_type,
            "payload": payload or {},
            "expected_response_schema": EXPECTED_OPENCLAW_SCHEMA,
        }
        raw = await self._run_cli(
            self._build_gateway_call_args(self.generic_call_method, params=params),
            self.timeout_seconds,
        )
        return self._normalize_result(raw, action_type)

    async def _productivity_gateway_action(self, action_type, payload):
        if self.productivity_call_method:
            params = {
                "instruction": INTERNAL_OPENCLAW_INSTRUCTION,
                "action_type": action_type,
                "payload": payload or {},
                "expected_response_schema": EXPECTED_OPENCLAW_SCHEMA,
            }
            raw = await self._run_cli(
                self._build_gateway_call_args(self.productivity_call_method, params=params),
                self.timeout_seconds,
            )
            if not self._contains_text(raw, "method not found"):
                return self._normalize_result(raw, action_type)

        if self.generic_call_method:
            return await self._generic_gateway_action(action_type, payload)

        return {
            "success": False,
            "service": "openclaw",
            "action_type": action_type,
            "summary": "La accion esta preparada en Jarvis, pero falta cargar el plugin OpenClaw jarvis-productivity o configurar un metodo generico.",
            "raw": None,
            "external_id": None,
            "warnings": ["missing_openclaw_productivity_method"],
        }

    async def _run_cli(self, command_args, timeout):
        command = [self.executable, *list(command_args or [])]
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except (FileNotFoundError, PermissionError):
            return self._unavailable_raw("OpenClaw executable is not available.")
        except asyncio.TimeoutError:
            return self._unavailable_raw("OpenClaw CLI timed out.", warning="timeout")
        except Exception as exc:
            return self._unavailable_raw(f"OpenClaw CLI failed: {self._safe_short_text(exc)}")

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        raw = {
            "success": proc.returncode == 0,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "returncode": proc.returncode,
            "command": self._redact_command(command),
        }
        parsed = self._parse_json(stdout_text)
        if parsed is not None:
            raw["json"] = parsed
        return raw

    async def _post_http(self, path, payload, timeout):
        url = f"{self.base_url}{path if str(path).startswith('/') else '/' + str(path)}"
        try:
            import aiohttp

            client_timeout = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.post(url, json=payload) as response:
                    text = await response.text()
                    raw = {"success": 200 <= response.status < 300, "status": response.status, "text": text}
                    parsed = self._parse_json(text)
                    if parsed is not None:
                        raw["json"] = parsed
                    return raw
        except asyncio.TimeoutError:
            return self._unavailable_raw("OpenClaw HTTP gateway timed out.", warning="timeout")
        except Exception as exc:
            return self._unavailable_raw(f"OpenClaw HTTP gateway failed: {self._safe_short_text(exc)}")

    def _build_gateway_call_args(self, method, params=None, expect_final=False, timeout_ms=None):
        args = ["gateway", "call", str(method), "--json"]
        if params is not None:
            args.extend(["--params", json.dumps(params or {}, ensure_ascii=False)])
        if timeout_ms is not None:
            args.extend(["--timeout", str(timeout_ms)])
        if self.gateway_url:
            args.extend(["--url", self.gateway_url])
        if self.gateway_token:
            args.extend(["--token", self.gateway_token])
        if expect_final:
            args.append("--expect-final")
        return args

    def _normalize_result(self, raw_result, action_type=None):
        action_type = action_type or "unknown"
        raw = self._redact(deepcopy(raw_result))

        if isinstance(raw, dict) and raw.get("unavailable"):
            summary = raw.get("summary")
            if "timeout" in (raw.get("warnings") or []):
                summary = "OpenClaw CLI timed out."
            return self._unavailable_result(action_type, summary, raw.get("warnings", []), raw)

        if self._contains_text(raw, "not listed in the configured WhatsApp allowlist"):
            return {
                "success": False,
                "service": "openclaw",
                "action_type": action_type,
                "summary": "Target is not allowed by the configured WhatsApp allowlist.",
                "error": "Target is not allowed by the configured WhatsApp allowlist.",
                "code": "OPENCLAW_WHATSAPP_ALLOWLIST_BLOCKED",
                "raw": None,
                "external_id": None,
                "warnings": ["allowlist_blocked"],
            }

        if action_type == "resolve_target" and self._contains_text(raw, "does not support resolve"):
            return {
                "success": False,
                "service": "openclaw",
                "action_type": action_type,
                "summary": "WhatsApp no soporta resolución de targets mediante OpenClaw. Usa agenda local de Jarvis.",
                "error": "WhatsApp no soporta resolución de targets mediante OpenClaw. Usa agenda local de Jarvis.",
                "code": "OPENCLAW_WHATSAPP_RESOLVE_UNSUPPORTED",
                "raw": None,
                "external_id": None,
                "warnings": ["resolve_unsupported"],
            }

        if action_type in MESSAGE_READ_ACTIONS and self._contains_text(raw, "Message action read not supported for channel whatsapp"):
            return {
                "success": False,
                "service": "openclaw",
                "action_type": action_type,
                "summary": "WhatsApp no soporta lectura de historial mediante OpenClaw. Usa mensajes inbound guardados en Jarvis.",
                "error": "WhatsApp no soporta lectura de historial mediante OpenClaw. Usa mensajes inbound guardados en Jarvis.",
                "code": "OPENCLAW_WHATSAPP_READ_UNSUPPORTED",
                "raw": None,
                "external_id": None,
                "warnings": ["read_unsupported"],
            }

        stdout = str(raw.get("stdout", "") if isinstance(raw, dict) else "")
        stderr = str(raw.get("stderr", "") if isinstance(raw, dict) else "")
        parsed_stdout = raw.get("json") if isinstance(raw, dict) else None
        if parsed_stdout is None:
            parsed_stdout = self._parse_json(stdout)
            if parsed_stdout is not None and isinstance(raw, dict):
                raw["json"] = self._redact(deepcopy(parsed_stdout))

        candidate = parsed_stdout if isinstance(parsed_stdout, dict) else (raw if isinstance(raw, dict) else {})
        warnings = self._extract_warnings(candidate, stdout, stderr)
        success = self._infer_success(raw, candidate, action_type)
        summary = self._summary_from_result(raw, candidate, action_type, success)

        return {
            "success": success,
            "service": "openclaw",
            "action_type": action_type,
            "summary": self._safe_short_text(summary),
            "raw": raw,
            "external_id": candidate.get("external_id") or candidate.get("id") if isinstance(candidate, dict) else None,
            "warnings": warnings,
        }

    def _infer_success(self, raw, candidate, action_type):
        if isinstance(candidate, dict):
            if candidate.get("ok") is True:
                return True
            if candidate.get("success") is not None:
                return bool(candidate.get("success"))
            if candidate.get("runtimeVersion") or candidate.get("linkChannel"):
                return True

        if isinstance(raw, dict) and raw.get("returncode") == 0:
            return True
        return bool(isinstance(raw, dict) and raw.get("success"))

    def _summary_from_result(self, raw, candidate, action_type, success):
        stderr = str(raw.get("stderr", "") if isinstance(raw, dict) else "")
        stdout = str(raw.get("stdout", "") if isinstance(raw, dict) else "")
        combined = f"{stderr}\n{stdout}".lower()

        if "unknown command" in combined:
            return "Comando OpenClaw no reconocido."
        if "method not found" in combined:
            return "Metodo RPC de OpenClaw no encontrado."
        if "missing scope" in combined:
            return "OpenClaw respondio, pero faltan permisos para esa operacion."
        if "timeout" in (raw.get("warnings") or []) if isinstance(raw, dict) else False:
            return "OpenClaw CLI timed out."

        if action_type == "check_status" and success:
            summary = "OpenClaw Gateway esta activo."
            if self._whatsapp_connected(candidate):
                summary += " WhatsApp esta conectado."
            return summary

        if isinstance(candidate, dict):
            return (
                candidate.get("summary")
                or candidate.get("action_done")
                or candidate.get("details")
                or candidate.get("message")
                or ("Accion completada." if success else "OpenClaw no esta disponible o no responde.")
            )
        return "Accion completada." if success else "OpenClaw no esta disponible o no responde."

    def _extract_warnings(self, candidate, stdout, stderr):
        warnings = []
        if isinstance(candidate, dict):
            raw_warnings = candidate.get("warnings") or []
            warnings.extend(raw_warnings if isinstance(raw_warnings, list) else [raw_warnings])
            event_loop = str(candidate.get("eventLoop", "")).lower()
            if event_loop == "degraded" or self._nested_contains(candidate, "eventLoop", "degraded"):
                warnings.append("OpenClaw reporta event loop degradado.")

        combined = f"{stdout}\n{stderr}".lower()
        if "connected-no-operator-scope" in combined:
            warnings.append("OpenClaw Gateway esta conectado, pero sin operator scope completo.")
        return [warning for warning in warnings if warning]

    def _whatsapp_connected(self, value):
        if not isinstance(value, (dict, list)):
            return False
        if isinstance(value, list):
            return any(self._whatsapp_connected(item) for item in value)

        for key, item in value.items():
            key_text = str(key).lower()
            if "whatsapp" in key_text and isinstance(item, dict):
                truthy = all(bool(item.get(field)) for field in ("enabled", "configured", "running", "connected"))
                healthy = str(item.get("health") or item.get("status") or "").lower() in {"healthy", "ok", "connected"}
                if truthy or (bool(item.get("connected")) and healthy):
                    return True
            if self._whatsapp_connected(item):
                return True
        return False

    def _nested_contains(self, value, target_key, target_value):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() == str(target_key).lower() and str(item).lower() == str(target_value).lower():
                    return True
                if self._nested_contains(item, target_key, target_value):
                    return True
        if isinstance(value, list):
            return any(self._nested_contains(item, target_key, target_value) for item in value)
        return False

    def _contains_text(self, raw, text):
        blob = json.dumps(raw, ensure_ascii=False).lower() if isinstance(raw, (dict, list)) else str(raw).lower()
        return str(text).lower() in blob

    def _is_whatsapp_channel(self, channel):
        return str(channel or "").strip().lower() == "whatsapp"

    def _build_internal_instruction(self, action_type, payload):
        return {
            "instruction": INTERNAL_OPENCLAW_INSTRUCTION,
            "action_type": action_type,
            "payload": self._redact(deepcopy(payload or {})),
            "expected_response_schema": EXPECTED_OPENCLAW_SCHEMA,
        }

    def _disabled_result(self, action_type):
        return {
            "success": False,
            "service": "openclaw",
            "action_type": action_type,
            "summary": "OpenClaw no esta habilitado.",
            "raw": None,
            "external_id": None,
            "warnings": [],
        }

    def _unavailable_result(self, action_type, summary=None, warnings=None, raw=None):
        return {
            "success": False,
            "service": "openclaw",
            "action_type": action_type,
            "summary": summary or "OpenClaw no esta disponible o no responde.",
            "raw": raw,
            "external_id": None,
            "warnings": warnings or [],
        }

    def _unavailable_raw(self, summary, warning=None):
        warnings = [warning] if warning else []
        return {"unavailable": True, "success": False, "summary": summary, "warnings": warnings}

    def _validation_result(self, action_type, summary, warning):
        return {
            "success": False,
            "service": "openclaw",
            "action_type": action_type,
            "summary": summary,
            "raw": None,
            "external_id": None,
            "warnings": [warning],
        }

    def _missing_method_result(self, action_type):
        return {
            "success": False,
            "service": "openclaw",
            "action_type": action_type,
            "summary": "Esta accion esta preparada en Jarvis, pero aun no hay un metodo OpenClaw configurado para ejecutarla.",
            "raw": None,
            "external_id": None,
            "warnings": ["missing_openclaw_method"],
        }

    def _calendar_action_type(self, action):
        action = str(action or "").strip().lower()
        mapping = {
            "list": "list_calendar_events",
            "list_events": "list_calendar_events",
            "create": "create_calendar_event",
            "update": "update_calendar_event",
            "modify": "update_calendar_event",
            "delete": "delete_calendar_event",
            "cancel": "delete_calendar_event",
        }
        return mapping.get(action, f"{action}_calendar_event" if action else "calendar_action")

    def _social_action_type(self, action):
        action = str(action or "").strip().lower()
        mapping = {
            "prepare": "prepare_social_post",
            "draft": "prepare_social_post",
            "schedule": "schedule_social_post",
            "publish": "publish_social_post",
        }
        return mapping.get(action, f"{action}_social_post" if action else "social_action")

    def _redact(self, value):
        if isinstance(value, dict):
            redacted = {}
            for key, item in value.items():
                key_text = str(key).lower()
                if key_text == "command" and isinstance(item, list):
                    redacted[key] = self._redact_command(item)
                elif any(secret in key_text for secret in SECRET_KEYWORDS):
                    redacted[key] = "[REDACTED]"
                else:
                    redacted[key] = self._redact(item)
            return redacted
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value

    def _redact_command(self, command):
        redacted = []
        redact_next = None
        for part in command:
            if redact_next == "secret":
                redacted.append("[REDACTED]")
                redact_next = None
                continue
            if redact_next == "json":
                parsed = self._parse_json(str(part))
                redacted.append(json.dumps(self._redact(parsed), ensure_ascii=False) if parsed is not None else "[REDACTED]")
                redact_next = None
                continue
            redacted.append(part)
            part_text = str(part).lower()
            if part_text in {"--token", "--authorization", "--cookie", "--api-key", "--password"}:
                redact_next = "secret"
            elif part_text in {"--params"}:
                redact_next = "json"
        return redacted

    def _safe_short_text(self, value, max_length=500):
        text = str(value or "")
        return text[:max_length] + ("..." if len(text) > max_length else "")

    def _parse_json(self, text):
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _env_bool(self, name, default=False):
        raw = os.getenv(name)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    def _csv_env(self, name, default):
        raw = os.getenv(name)
        if raw is None:
            return list(default)
        values = [item.strip() for item in raw.split(",") if item.strip()]
        return values or list(default)


openclaw_bridge = OpenClawBridge()
