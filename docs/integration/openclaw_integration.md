# Integracion OpenClaw en J.A.R.V.I.S.

## Roles

J.A.R.V.I.S. sigue siendo el asistente principal. Interpreta la intencion del usuario, resuelve aliases locales, aplica permisos, crea pending actions y responde al frontend.

OpenClaw actua solo como gateway interno para ejecutar acciones externas reales. Jarvis no implementa WhatsApp Web propio, scraping ni APIs propias de WhatsApp, Gmail, Calendar o redes sociales.

## Capacidades reales de WhatsApp

Validado en OpenClaw WhatsApp:

- Envio por numero o target canonico: soportado.
- `channels resolve`: no soportado para WhatsApp.
- `message read`: no soportado para WhatsApp.
- `directory peers list`: no expone la agenda completa; puede devolver solo el propio usuario.
- `directory groups list`: puede devolver `[]`.

Por eso Jarvis usa una agenda local para contactos, aliases y grupos. Los mensajes nuevos se leen desde inbound guardado en Jarvis, no desde historial remoto.

## Comandos usados

Estado:

```bash
openclaw gateway call health --json
openclaw gateway call status --json
```

Envio WhatsApp:

```bash
openclaw message send --channel whatsapp --target <numero_o_target> --message <mensaje> --json
```

Directorio informativo:

```bash
openclaw directory self --channel whatsapp --json
openclaw directory peers list --channel whatsapp --limit <n> --json
openclaw directory groups list --channel whatsapp --limit <n> --json
```

Resolucion y lectura solo se usan para canales que las soporten. Para WhatsApp, Jarvis devuelve errores limpios y guia al flujo local.

## Comandos prohibidos

Jarvis no usa:

- `openclaw run`
- `openclaw agent` para mensajes normales
- `openclaw message list`
- scraping de WhatsApp Web
- APIs propias no autorizadas de WhatsApp

## Agenda local

Los contactos se guardan en `backend/demo_state/openclaw_targets.json` con `display_name`, `canonical_target`, `aliases`, `relationship`, `favorite`, `source`, `allowed` y metadatos de OpenClaw si existen.

Para WhatsApp, `canonical_target` puede ser directamente un numero E.164 como `+34722129717`. No se exige `resolved=true` para enviar si hay target canonico.

Aliases como `mi novia`, `novia`, `mama`, `Laura` o `grupo TFG` se resuelven localmente con normalizacion de mayusculas y tildes.

## Importacion

Jarvis permite importar contactos desde:

- CSV con columnas flexibles: `name`, `display_name`, `phone`, `number`, `mobile`, `tel`, `aliases`, `relationship`, `favorite`.
- VCF basico leyendo `FN` y `TEL`.

Los telefonos se normalizan quitando espacios, guiones y parentesis. Para la demo local se asume `+34` cuando el numero empieza por `6`, `7` o `9` sin prefijo.

## Flujo de envio

1. El usuario dice o escribe algo como: "mandale un WhatsApp a mi novia que diga llego en 10".
2. Jarvis busca `mi novia` en la agenda local.
3. Si encuentra target canonico, crea una pending action `send_message`.
4. Jarvis no envia sin confirmacion.
5. Al confirmar, el bridge ejecuta `openclaw message send --channel whatsapp --target <canonical_target> --message <mensaje> --json`.
6. El resultado se registra como evento `outbound` o `error`.

`display_target` se usa para UI y logs; el envio tecnico usa `canonical_target`.

## Flujo inbound y lectura nueva

`POST /api/openclaw/inbound`:

1. Valida `JARVIS_OPENCLAW_INBOUND_SECRET` si existe mediante `X-Jarvis-OpenClaw-Secret`.
2. Normaliza el payload con `openclaw_event_normalizer`.
3. Guarda evento `inbound`.
4. Guarda mensaje en `backend/demo_state/openclaw_messages.json` con `read=false`.
5. Crea o actualiza el contacto o grupo local si llega un target desconocido.
6. Evalua reglas autopilot.
7. Si una regla requiere confirmacion, crea pending action.

Consultas como "dime mensajes nuevos de mi novia" leen desde `openclaw_messages.json` y marcan como leidos si se solicita. Jarvis no promete leer historial antiguo de WhatsApp.

## Grupos

OpenClaw WhatsApp no expone listado completo de grupos actualmente. Los grupos se pueden:

- Crear manualmente si se conoce el target.
- Descubrir automaticamente al recibir un inbound con `kind=group` o un id de grupo.

Despues se pueden anadir aliases como `grupo TFG` para reglas y futuras acciones.

## Autopilot

Las reglas se guardan con `channel`, `kind`, `target` canonico, `display_target`, `target_id`, `mode`, `trigger` y `behavior`.

Modos:

- `draft_only`: crea propuesta, no envia.
- `ask_before_send`: crea pending action.
- `auto_send_limited`: puede enviar solo si respeta limites y condiciones, y la primera respuesta puede requerir confirmacion.

El matching se hace por canal, target canonico, kind y condiciones como keywords. No depende solo del nombre visible.

## Errores normalizados

Resolve WhatsApp no soportado:

```json
{
  "success": false,
  "code": "OPENCLAW_WHATSAPP_RESOLVE_UNSUPPORTED",
  "error": "WhatsApp no soporta resolucion de targets mediante OpenClaw. Usa agenda local de Jarvis."
}
```

Read WhatsApp no soportado:

```json
{
  "success": false,
  "code": "OPENCLAW_WHATSAPP_READ_UNSUPPORTED",
  "error": "WhatsApp no soporta lectura de historial mediante OpenClaw. Usa mensajes inbound guardados en Jarvis."
}
```

Allowlist:

```json
{
  "success": false,
  "code": "OPENCLAW_WHATSAPP_ALLOWLIST_BLOCKED",
  "error": "Target is not allowed by the configured WhatsApp allowlist."
}
```

La allowlist de OpenClaw se respeta siempre.

## Dashboard

`src/components/OpenClawDashboard.jsx` muestra:

- Estado y aviso de capacidades reales.
- Creacion manual de contactos.
- Importacion CSV/VCF.
- Targets, aliases, favorite, source y allow manual.
- Creacion de envio pendiente.
- Mensajes inbound nuevos y marcado como leidos.
- Pending actions, reglas autopilot y eventos.

## Seguridad

No se exponen tokens, secretos ni credenciales. El bridge redacta campos sensibles en resultados crudos. Enviar mensajes y activar reglas sensibles pasa por pending actions.

Calendar y LinkedIn quedan como acciones de productividad solo cuando exista comando o skill real de OpenClaw; Jarvis no inventa comandos. El correo electronico queda fuera del alcance del proyecto.

## Calendario y LinkedIn

Jarvis carga el plugin local `openclaw-plugins/jarvis-productivity`, que expone:

```bash
openclaw gateway call jarvis.productivity.status --json
openclaw gateway call jarvis.productivity.execute --params '{"action_type":"create_calendar_event","payload":{"dry_run":true,"title":"Demo","start":"2026-05-27T17:00:00+02:00","end":"2026-05-27T17:30:00+02:00"}}' --json
```

Variables necesarias para acciones reales:

- `JARVIS_GOOGLE_CALENDAR_ACCESS_TOKEN`: token OAuth con permiso de Calendar; util para pruebas rapidas.
- `JARVIS_GOOGLE_CALENDAR_REFRESH_TOKEN`, `JARVIS_GOOGLE_CALENDAR_CLIENT_ID`, `JARVIS_GOOGLE_CALENDAR_CLIENT_SECRET`: alternativa estable para que Jarvis renueve el token automaticamente.
- `JARVIS_GOOGLE_CALENDAR_ID`: `primary` por defecto.
- `JARVIS_LINKEDIN_ACCESS_TOKEN`: token OAuth con permisos de publicacion (`w_member_social` o `w_organization_social` segun el autor).
- `JARVIS_LINKEDIN_AUTHOR_URN`: `urn:li:person:...` u organizacion autorizada.
- `JARVIS_LINKEDIN_API_VERSION`: version de LinkedIn Marketing API en formato `YYYYMM`; por defecto `202605`.

Calendario usa `POST https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events`. LinkedIn usa la Posts API actual `POST https://api.linkedin.com/rest/posts` con cabeceras `Linkedin-Version` y `X-Restli-Protocol-Version`.

El arranque `npm run dev` lee `.env` y pasa esas variables a OpenClaw. Las acciones que escriben fuera, como crear eventos o publicar en LinkedIn, siguen pasando por pending actions y confirmacion de Jarvis.

## Demos

Demo 1:

1. Importar un CSV con `Laura,+34722129717,"mi novia,novia,Laura",novia,true`.
2. Decir: "Jarvis, mandale un WhatsApp a mi novia que diga llego en 10".
3. Confirmar la pending action.
4. Ver el evento outbound.

Demo 2:

1. Simular inbound con `POST /api/openclaw/inbound`.
2. Decir: "Jarvis, dime mensajes nuevos de mi novia".
3. Ver el resumen y el mensaje marcado como leido.

Demo 3:

1. Recibir inbound de grupo.
2. Jarvis crea el target local de grupo.
3. Anadir alias `grupo TFG`.
4. Usarlo en reglas autopilot o futuras acciones.
