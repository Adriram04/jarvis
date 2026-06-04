"""Ready-to-use automation templates and default seed automations.

Templates use the canonical spec model:
    id, name, description, enabled, trigger, conditions, actions, safety

``list_templates`` / ``get_template`` power the "Plantillas rapidas" UI.
``seed_automations`` is used by AutomationManager to populate the store the very
first time it runs (so a fresh install already shows useful examples).
"""

from copy import deepcopy


DEFAULT_TIMEZONE = "Europe/Madrid"


def _template(template_id, name, description, trigger, actions, conditions=None, enabled=False, safety=None):
    return {
        "id": template_id,
        "name": name,
        "description": description,
        "enabled": enabled,
        "trigger": trigger,
        "conditions": conditions or [],
        "actions": actions,
        "safety": safety or {"requires_confirmation": "auto", "sensitive": False},
    }


# --------------------------------------------------------------------- templates
TEMPLATES = [
    _template(
        "smart_startup",
        "Arranque inteligente",
        "Al iniciar JARVIS comprueba integraciones y prepara un resumen del dia.",
        {"type": "system.startup", "filters": {}},
        [
            {"action_type": "check_integrations", "payload": {}, "human_summary": "Comprobar estado de las integraciones.", "stop_on_error": False},
            {"action_type": "summarize_day", "payload": {}, "human_summary": "Preparar resumen del dia.", "stop_on_error": False},
        ],
        enabled=False,
    ),
    _template(
        "daily_summary",
        "Resumen diario",
        "Cada manana a las 09:00 lee la agenda y prepara un resumen.",
        {"type": "schedule", "schedule": {"kind": "daily", "hour": 9, "minute": 0, "timezone": DEFAULT_TIMEZONE}},
        [
            {"action_type": "summarize_day", "payload": {}, "human_summary": "Resumen del dia (agenda, mensajes, pendientes).", "stop_on_error": False},
        ],
        conditions=[{"type": "has_calendar_events"}],
        enabled=False,
    ),
    _template(
        "whatsapp_urgent",
        "Mensajes urgentes de WhatsApp",
        "Si llega un WhatsApp que contiene 'urgente', crea una notificacion prioritaria.",
        {"type": "whatsapp.message_received", "filters": {}},
        [
            {"action_type": "notify", "payload": {"title": "WhatsApp urgente", "priority": "high"}, "human_summary": "Avisar de mensaje urgente.", "stop_on_error": False},
        ],
        conditions=[{"type": "message_contains", "any": ["urgente", "urgent", "emergencia"]}],
        enabled=False,
    ),
    _template(
        "work_mode",
        "Modo trabajo",
        "Rutina manual: musica, abrir proyecto y mostrar la agenda de hoy.",
        {"type": "manual"},
        [
            {"action_type": "play_music", "payload": {"playlist": "Focus"}, "human_summary": "Poner musica de concentracion.", "stop_on_error": False},
            {"action_type": "open_project", "payload": {}, "human_summary": "Abrir el proyecto activo.", "stop_on_error": False},
            {"action_type": "list_calendar_today", "payload": {}, "human_summary": "Mostrar la agenda de hoy.", "stop_on_error": False},
        ],
        enabled=False,
    ),
    _template(
        "tfg_defense_mode",
        "Modo defensa TFG",
        "Rutina manual: activa la simulacion, comprueba servicios y avisa de que todo esta listo.",
        {"type": "manual"},
        [
            {"action_type": "activate_simulation", "payload": {}, "human_summary": "Activar la simulacion (sin hardware).", "stop_on_error": False},
            {"action_type": "check_integrations", "payload": {}, "human_summary": "Comprobar servicios e integraciones.", "stop_on_error": False},
            {"action_type": "notify", "payload": {"title": "Modo defensa TFG listo", "priority": "high"}, "human_summary": "Avisar de que el modo defensa esta listo.", "stop_on_error": False},
        ],
        enabled=False,
    ),
    _template(
        "openwa_sync_contacts",
        "Sincronizar contactos al conectar OpenWA",
        "Cuando OpenWA se conecta, importa los contactos para que JARVIS pueda resolverlos.",
        {"type": "openwa.connected", "filters": {}},
        [
            {"action_type": "openclaw_import_contacts", "payload": {}, "human_summary": "Importar contactos de OpenWA.", "stop_on_error": False},
        ],
        conditions=[{"type": "provider_connected", "provider": "openwa"}],
        enabled=False,
    ),
]

_TEMPLATES_BY_ID = {item["id"]: item for item in TEMPLATES}


def list_templates():
    """Public list of templates (deep-copied so callers cannot mutate them)."""
    return [deepcopy(item) for item in TEMPLATES]


def get_template(template_id):
    template = _TEMPLATES_BY_ID.get(str(template_id or "").strip())
    return deepcopy(template) if template else None


def template_as_automation_payload(template_id, overrides=None):
    """Build a ``create_automation`` payload from a template id."""
    template = get_template(template_id)
    if not template:
        return None
    payload = deepcopy(template)
    payload.pop("id", None)  # let AutomationManager assign a fresh uuid
    payload["template_id"] = template_id
    if isinstance(overrides, dict):
        payload.update(deepcopy(overrides))
    return payload


def seed_automations():
    """Default automations created on first run (a small enabled-off sample)."""
    seeds = ["daily_summary", "whatsapp_urgent", "smart_startup"]
    payloads = []
    for template_id in seeds:
        template = get_template(template_id)
        if template:
            template.pop("id", None)
            payloads.append(template)
    return payloads
