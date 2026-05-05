# J.A.R.V.I.S

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![React](https://img.shields.io/badge/React-18.2-61DAFB?logo=react)
![Electron](https://img.shields.io/badge/Electron-28-47848F?logo=electron)
![Gemini](https://img.shields.io/badge/Google%20Gemini-Native%20Audio-4285F4?logo=google)
![License](https://img.shields.io/badge/License-MIT-green)

**J.A.R.V.I.S** es un asistente de inteligencia artificial multimodal para escritorio. Integra conversacion por voz, vision por camara, gestos, generacion CAD, automatizacion web, control de dispositivos inteligentes, impresion 3D y memoria de proyectos en una aplicacion Electron con frontend React y backend Python.

> J.A.R.V.I.S = Just-in-Time Autonomous Reasoning, Vision & Integration System

---

## Caracteristicas

| Modulo | Descripcion | Tecnologia |
| --- | --- | --- |
| Voz en tiempo real | Conversacion por audio con baja latencia | Google GenAI SDK |
| CAD generativo | Generacion e iteracion de modelos 3D desde prompts | build123d, STL |
| Impresion 3D | Descubrimiento de impresoras, slicing y envio de trabajos | OrcaSlicer, Moonraker, OctoPrint |
| Vision y gestos | Interaccion con camara y seguimiento de manos | MediaPipe |
| Autenticacion facial | Bloqueo opcional mediante referencia facial local | MediaPipe Face Landmarker |
| Agente web | Navegacion automatizada en navegador | Playwright |
| Smart Home | Control de dispositivos TP-Link Kasa | python-kasa |
| Memoria de proyecto | Historial y artefactos persistentes por proyecto | JSONL y archivos locales |

---

## Arquitectura

```mermaid
graph TB
    subgraph Frontend["Frontend: Electron + React"]
        UI["React UI"]
        THREE["Three.js CAD Viewer"]
        GESTURE["MediaPipe Gestures"]
        SOCKET_C["Socket.IO Client"]
    end

    subgraph Backend["Backend: Python + FastAPI"]
        SERVER["server.py<br/>FastAPI + Socket.IO"]
        JARVIS["jarvis.py<br/>Gemini Live API"]
        CAD["cad_agent.py<br/>CAD + build123d"]
        WEB["web_agent.py<br/>Playwright"]
        PRINTER["printer_agent.py<br/>3D Printing"]
        KASA["kasa_agent.py<br/>Smart Home"]
        AUTH["authenticator.py<br/>Face Auth"]
        PM["project_manager.py<br/>Project Memory"]
    end

    UI --> SOCKET_C
    SOCKET_C <--> SERVER
    SERVER --> JARVIS
    SERVER --> AUTH
    SERVER --> PM
    JARVIS --> CAD
    JARVIS --> WEB
    JARVIS --> KASA
    JARVIS --> PRINTER
    CAD --> THREE
    CAD --> PRINTER
```

---

## Requisitos

- Windows 10/11 recomendado para el estado actual del proyecto.
- Python 3.11 o superior. El entorno actual se ha validado con Python 3.13.
- Node.js 18 o superior.
- npm.
- Git.
- Camara y microfono para las funciones de voz, vision y autenticacion facial.

Conda **no es obligatorio**. Puedes usar el entorno virtual nativo de Python (`venv`) o Conda. Si no tienes Conda instalado, no hace falta instalarlo: usa la opcion A.

---

## Instalacion

Primero clona el repositorio:

```powershell
git clone https://github.com/Adriram04/jarvis.git
cd jarvis
```

### Opcion A: sin Conda, usando venv

Esta es la opcion recomendada si quieres la instalacion mas directa. No requiere instalar nada extra aparte de Python.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium

npm install
```

Para volver a activar el entorno en otra terminal:

```powershell
.\venv\Scripts\Activate.ps1
```

### Opcion B: con Conda, opcional

Usa esta opcion solo si ya tienes Conda instalado o si prefieres gestionar tus entornos con Conda.

```powershell
conda create -n jarvis python=3.11 -y
conda activate jarvis

python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium

npm install
```

Para volver a activar el entorno Conda en otra terminal:

```powershell
conda activate jarvis
```

Ambas opciones instalan las mismas dependencias. La aplicacion funciona correctamente sin Conda usando `venv`.

---

## Variables de entorno

Crea un archivo `.env` en la raiz del proyecto:

```env
GEMINI_API_KEY=tu_api_key_aqui
# Opcional: limite de ejecucion para scripts CAD generados por IA.
JARVIS_CAD_SCRIPT_TIMEOUT_SECONDS=30
```

Puedes crear una API key desde Google AI Studio:

https://aistudio.google.com/app/apikey

No subas `.env` al repositorio.

---

## Ejecucion

### Modo normal

Con el entorno Python activado, ejecuta:

```powershell
npm run dev
```

Este comando arranca Vite, Electron y el backend Python automaticamente. Electron intenta usar primero `venv` local (`venv\Scripts\python.exe` en Windows). Si quieres forzar otro interprete, define `JARVIS_PYTHON` antes de arrancar:

```powershell
$env:JARVIS_PYTHON="C:\ruta\a\python.exe"
npm run dev
```

### Modo desarrollo con backend separado

Terminal 1:

```powershell
.\venv\Scripts\Activate.ps1
python backend\server.py
```

Terminal 2:

```powershell
npm run dev
```

Si estas usando Conda, sustituye la activacion de `venv` por:

```powershell
conda activate jarvis
```

---

## Configuracion

La configuracion local del backend vive en:

```text
backend/settings.json
```

Campos importantes:

| Clave | Descripcion |
| --- | --- |
| `face_auth_enabled` | Activa o desactiva la autenticacion facial. |
| `tool_permissions` | Define que herramientas requieren confirmacion manual. |
| `printers` | Lista de impresoras 3D guardadas. |
| `kasa_devices` | Lista de dispositivos Kasa conocidos. |
| `camera_flipped` | Invierte la direccion horizontal de la camara si es necesario. |

---

## Autenticacion facial

La autenticacion facial es opcional. Para usarla:

1. Captura una imagen de referencia:

   ```powershell
   python backend\capture_face.py
   ```

2. Comprueba que se ha creado:

   ```text
   backend/reference.jpg
   ```

3. Activa `face_auth_enabled` en `backend/settings.json`.

La imagen de referencia se procesa localmente y no debe subirse al repositorio.

---

## Impresion 3D

J.A.R.V.I.S puede descubrir impresoras 3D en red y enviar trabajos de impresion desde modelos STL generados.

Compatibilidad prevista:

- Moonraker/Klipper, por ejemplo Creality K1.
- OctoPrint.
- PrusaLink, de forma experimental.

Para usar esta parte, instala OrcaSlicer o PrusaSlicer y asegurate de que la impresora y el ordenador esten conectados a la misma red local.

---

## Tests

Ejecutar toda la suite configurada:

```powershell
.\venv\Scripts\python.exe -m pytest
```

Ejecutar un modulo concreto:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_cad_agent.py
.\venv\Scripts\python.exe -m pytest tests\test_web_agent.py
.\venv\Scripts\python.exe -m pytest tests\test_printer_agent.py
```

Ejecutar un test especifico:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_cad_agent.py::TestCadGeneration::test_generate_simple_cube
```

Si estas usando Conda:

```powershell
conda activate jarvis
python -m pytest
```

Estado validado recientemente:

```text
74 passed, 5 skipped
```

Los tests saltados corresponden a integraciones que requieren dispositivos Kasa configurados.

---

## Estructura del proyecto

```text
jarvis/
|-- backend/
|   |-- server.py              # FastAPI + Socket.IO
|   |-- jarvis.py              # Integracion principal con Gemini Live API
|   |-- cad_agent.py           # Generacion e iteracion CAD
|   |-- printer_agent.py       # Descubrimiento, slicing e impresion 3D
|   |-- web_agent.py           # Automatizacion web con Playwright
|   |-- kasa_agent.py          # Control TP-Link Kasa
|   |-- authenticator.py       # Autenticacion facial con MediaPipe
|   |-- capture_face.py        # Captura de imagen facial de referencia
|   |-- project_manager.py     # Gestion de proyectos y memoria
|   |-- tools.py               # Definiciones de herramientas para Gemini
|   |-- settings.json          # Configuracion local
|   `-- face_landmarker.task   # Modelo MediaPipe
|-- src/
|   |-- App.jsx
|   |-- main.jsx
|   |-- index.css
|   `-- components/
|-- electron/
|   `-- main.js
|-- tests/
|-- projects/
|-- scripts/
|-- public/
|-- requirements.txt
|-- package.json
|-- pytest.ini
`-- README.md
```

---

## Comandos utiles

```powershell
npm run dev                         # Arranca la app en modo desarrollo
npm run build                       # Genera build de frontend
.\venv\Scripts\python.exe -m pytest # Ejecuta tests con venv
python backend\server.py            # Arranca solo el backend
python backend\capture_face.py      # Captura reference.jpg
```

---

## Seguridad

- No subas `.env` al repositorio.
- No subas `backend/reference.jpg`.
- Revisa las confirmaciones antes de permitir escrituras en disco, navegacion web o impresion 3D.
- Los datos de proyectos se guardan localmente en `projects/`.

---

## Limitaciones conocidas

- La API de Gemini requiere conexion a internet.
- Algunas funciones dependen de hardware local: camara, microfono, impresora 3D o dispositivos Kasa.
- Las pruebas de Kasa se saltan si no hay dispositivos configurados.
- La impresion 3D depende de la configuracion del slicer y de la red local.

---

## Licencia

Este proyecto esta publicado bajo licencia MIT. Consulta [LICENSE](LICENSE) para mas detalles.

---

Desarrollado por Adrian Ramirez Gil.
