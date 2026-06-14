# Arquitectura de Proveedores — JARVIS

## Visión general

JARVIS separa el proveedor de mensajería WhatsApp del gateway de productividad legacy:

```
┌─────────────────────────────────────┐
│           JARVIS Backend            │
│                                     │
│  WhatsApp  ──── OpenWABridge ───▶ OpenWA (REST :2785)
│                                     │
│  Calendar  ──┐                      │
│  LinkedIn  ──┼── OpenClawBridge ──▶ OpenClaw CLI/Gateway
│  Workflows ──┘                      │
└─────────────────────────────────────┘
```

## Variable de selección

```env
JARVIS_WHATSAPP_PROVIDER=openwa   # Usar OpenWA para WhatsApp
JARVIS_WHATSAPP_PROVIDER=openclaw # Usar OpenClaw (legacy) para WhatsApp
```

## OpenWA (proveedor principal de WhatsApp)

- **Para qué**: envío y recepción de mensajes WhatsApp
- **Cómo funciona**: servicio Node.js externo con API REST
- **Puerto por defecto**: 2785
- **Autenticación**: header `X-API-Key`
- **Archivo del bridge**: `backend/integrations/openwa_bridge.py`
- **Documentación**: `docs/integration/openwa_integration.md`

### Variables relevantes

```env
JARVIS_OPENWA_ENABLED=true
JARVIS_OPENWA_BASE_URL=http://127.0.0.1:2785/api
JARVIS_OPENWA_API_KEY=<clave>
JARVIS_OPENWA_SESSION_ID=jarvis-main
JARVIS_OPENWA_TIMEOUT_SECONDS=30
JARVIS_OPENWA_SEND_STYLE=send-text
```

## OpenClaw (gateway legacy)

- **Para qué**: Calendar, LinkedIn, workflows, y WhatsApp en modo legacy (email/Telegram quedan fuera del alcance)
- **Cómo funciona**: CLI subprocess o gateway WebSocket
- **Archivo del bridge**: `backend/integrations/openclaw_bridge.py`
- **No se elimina**: OpenClaw sigue siendo el gateway para productividad

### Variables relevantes

```env
JARVIS_OPENCLAW_ENABLED=true
JARVIS_OPENCLAW_MODE=cli
JARVIS_OPENCLAW_EXECUTABLE=openclaw
JARVIS_OPENCLAW_GATEWAY_URL=          # vacio para gateway local; ws://... solo para gateway remoto
```

## Reglas de routing

| Acción              | Provider openwa | Provider openclaw |
|---------------------|-----------------|-------------------|
| WhatsApp send       | OpenWA          | OpenClaw          |
| Google Calendar     | OpenClaw        | OpenClaw          |
| LinkedIn post       | OpenClaw        | OpenClaw          |
| Workflows           | OpenClaw        | OpenClaw          |

## Seguridad preservada

Independientemente del proveedor, el envío de WhatsApp siempre pasa por:

1. Validación de **allowlist** (openclaw_targets_manager)
2. Creación de **pending action** (confirmación del usuario)
3. Log de **evento** (openclaw_events_manager)
4. Sin devolver API keys al frontend

## Endpoints de estado

```
GET /api/whatsapp/provider   → proveedor configurado
GET /api/whatsapp/status     → estado del proveedor activo
GET /api/openclaw/status     → estado de OpenClaw (siempre disponible)
```

## Dashboard

- **OpenClaw** aparece como integración legacy (Calendar, LinkedIn, etc.)
- **WhatsApp** muestra estado de OpenWA cuando `JARVIS_WHATSAPP_PROVIDER=openwa`
- Si OpenClaw está online pero OpenWA no, WhatsApp aparece offline (correcto)
- No se mezclan los estados entre proveedores
