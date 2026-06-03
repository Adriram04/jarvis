# OpenWA — Integración con JARVIS

## Resumen

OpenWA es el proveedor de WhatsApp principal de JARVIS cuando se configura
`JARVIS_WHATSAPP_PROVIDER=openwa`. Se ejecuta como servicio externo independiente y
expone una API REST que JARVIS consume mediante `OpenWABridge`.

---

## Arquitectura

```
JARVIS (backend)
  └─ OpenWABridge  ──HTTP──▶  OpenWA (puerto 2785)
                                └─ WhatsApp Web.js
                                     └─ WhatsApp
```

OpenClaw queda como gateway legacy para Calendar, LinkedIn, email y workflows.
WhatsApp sólo pasa por OpenClaw si `JARVIS_WHATSAPP_PROVIDER=openclaw`.

---

## Instalación de OpenWA

```powershell
# 1. Clonar (si no está ya clonado)
git clone https://github.com/rmyndharis/OpenWA C:/Users/<usuario>/OpenWA

# 2. Instalar dependencias
cd C:/Users/<usuario>/OpenWA
npm install

# 3. Configurar entorno
copy .env.minimal .env

# 4. Crear directorios de datos
mkdir data/sessions
mkdir data/media

# 5. Arrancar en modo desarrollo
npm run dev
```

### Nota Windows

Si `npm install` falla por un script `postinstall` de Unix, edita el
`package.json` de OpenWA y elimina o comenta la entrada `"postinstall"` antes de
volver a ejecutar `npm install`. No modifiques nada en JARVIS.

---

## Obtener la API Key

Una vez que OpenWA está arrancado, la clave se genera automáticamente:

```powershell
Get-Content C:/Users/<usuario>/OpenWA/data/.api-key
```

---

## Comprobar que OpenWA está activo

```powershell
Invoke-RestMethod http://127.0.0.1:2785/api/health
```

Respuesta esperada:
```json
{ "status": "ok" }
```

---

## Configurar JARVIS

En el archivo `.env` del proyecto JARVIS:

```env
JARVIS_WHATSAPP_PROVIDER=openwa
JARVIS_OPENWA_ENABLED=true
JARVIS_OPENWA_BASE_URL=http://127.0.0.1:2785/api
JARVIS_OPENWA_API_KEY=<clave-del-archivo-data/.api-key>
JARVIS_OPENWA_SESSION_ID=jarvis-main
JARVIS_OPENWA_TIMEOUT_SECONDS=30
JARVIS_OPENWA_SEND_STYLE=send-text
```

---

## Gestión de sesión

### Crear sesión

```powershell
Invoke-RestMethod -Method POST http://localhost:8000/api/whatsapp/session/create `
  -ContentType "application/json" `
  -Body '{"name":"jarvis-main"}'
```

### Iniciar sesión

```powershell
Invoke-RestMethod -Method POST http://localhost:8000/api/whatsapp/session/start `
  -ContentType "application/json" `
  -Body '{"session_id":"jarvis-main"}'
```

### Obtener QR para escanear

```powershell
Invoke-RestMethod http://localhost:8000/api/whatsapp/session/qr?session_id=jarvis-main
```

El campo `qr` contiene el código QR en base64. Escanéalo con WhatsApp.

---

## Enviar mensaje de prueba (con confirmación)

```powershell
Invoke-RestMethod -Method POST http://localhost:8000/api/whatsapp/send `
  -ContentType "application/json" `
  -Body '{"target":"34600111222@c.us","message":"Hola desde JARVIS + OpenWA"}'
```

Esto crea una acción pendiente. Confírmala desde el dashboard o:

```powershell
$action = Invoke-RestMethod http://localhost:8000/api/pending-actions
$id = $action.actions[0].id
Invoke-RestMethod -Method POST "http://localhost:8000/api/pending-actions/$id/confirm"
```

---

## Comprobar estado desde JARVIS

```powershell
# Estado del proveedor configurado
Invoke-RestMethod http://localhost:8000/api/whatsapp/provider

# Estado de WhatsApp (usa el proveedor activo)
Invoke-RestMethod http://localhost:8000/api/whatsapp/status
```

---

## Qué conserva JARVIS con OpenWA

| Función                    | Estado |
|----------------------------|--------|
| Allowlist de contactos     | Conservada (openclaw_targets_manager) |
| Confirmaciones manuales    | Conservadas (pending_actions_manager) |
| Pending actions            | Conservadas |
| Log de eventos             | Conservado (openclaw_events_manager) |
| Mensajes inbound           | Conservados (openclaw_messages_manager) |
| Reglas autopilot           | Conservadas (openclaw_autopilot_manager) |
| Normalización de teléfonos | Implementada en OpenWABridge |

---

## Flujo de envío con OpenWA

```
[Voz o Dashboard]
      │
      ▼
_execute_openclaw_action(send_message, payload)
      │  allowlist OK?
      ▼
  SI: _whatsapp_provider() == "openwa"?
      │
      ▼
openwa_bridge.execute_action(...)
      │
      ▼
POST /sessions/jarvis-main/messages/send-text
      │  → 404? fallback:
      ▼
POST /sessions/jarvis-main/messages
      │
      ▼
openclaw_events_manager.add_event("outbound" | "error")
```

---

## Solución de problemas

| Error | Causa | Solución |
|-------|-------|----------|
| `JARVIS_OPENWA_ENABLED=false` | Variable no activada | `JARVIS_OPENWA_ENABLED=true` en .env |
| `Falta JARVIS_OPENWA_API_KEY` | API key no configurada | Copiar clave de `data/.api-key` |
| `OpenWA: 401` | API key incorrecta | Verificar clave con `Get-Content data/.api-key` |
| `OpenWA: 404` | session_id incorrecto | Crear sesión con `/api/whatsapp/session/create` |
| `OpenWA no responde` | Servicio no arrancado | `cd OpenWA && npm run start:dev` |
