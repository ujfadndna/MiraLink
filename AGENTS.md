# AGENTS.md

Default workflow:

```powershell
cd <repo>
git status --short
```

Read current active docs before making assumptions. Do not infer current behavior from archived or local-only notes. Prefer `rg` for search, then `git grep`.

## Product Contract

The main demo paths must remain real and runnable:

```text
Voice input
  -> ASR
  -> LLM/Agent
  -> TTS + viseme curve
  -> Unity /ws/avatar
  -> avatar audio playback, lip sync, expression, gesture

Touch / phone controller
  -> WebSocket sensor event
  -> FastAPI backend
  -> sensor feedback or Agent rule
  -> Unity /ws/avatar
  -> visible avatar animation, expression, UI, SFX, or VFX within the demo loop
```

Mock backends are allowed for smoke tests and offline development. They are not evidence that the real ASR/TTS/LLM voice chain is complete.

Do not replace the main phone interaction with text input, static video, mock-only UI, or a backend-only API demo. Do not bypass `sensor.feedback`, `NetworkClient`, `JdDemoInteractionController`, `call_ws.py`, `tts.py`, `asr.py`, `agent.py`, `viseme.py`, `StreamingAudioPlayer`, or `FacialAnimationController` when working on the core demo path.

`frontend/avatar_touch.html` is the formal demo page. In normal state it should remain a clean full-screen experience without default visible buttons, logs, status bars, anchors, or control labels.

## Current Task Entry Points

| Task | Start Here |
|---|---|
| Overall roadmap | `docs/roadmap.md` |
| Acceptance notes | `docs/jd-demo-plan.md` |
| Architecture | `docs/architecture.md` |
| Local launch | `docs/local-demo.md` |
| Cloud extension | `docs/cloud-demo.md` |
| Protocol details | `docs/protocol.md` |
| Test commands | `docs/testing.md` |
| Backend app | `backend/app/main.py` |
| Backend config | `backend/app/config.py` |
| Message models | `backend/app/schemas.py` |
| Backend factory | `backend/app/services/base.py` |
| Unity network | `assets/Scripts/NetworkClient.cs` |
| Unity feedback | `assets/Scripts/JdDemoInteractionController.cs` |
| Debug phone page | `frontend/sensor_controller.html` |
| Clean phone page | `frontend/avatar_touch.html` |
| Cloud helper | `tools/cloud_unity_manager.py` |

The Unity project root is the repository root, not a `unity/` subdirectory.

## Project Boundaries

Owned by this repo:

- Phone browser controller and clean touch page.
- WebSocket communication: `/ws/sensor`, `/ws/avatar`, `/ws/call`.
- FastAPI backend services and protocol models.
- Unity VRM avatar, scene, HUD, state machine, gesture, expression, gaze, audio, VFX, and lip-sync integration.
- RenderStreaming signalling helper for local or optional cloud demos.
- Documentation and acceptance notes for the portfolio demo.

Out of scope unless explicitly requested:

- Production multi-user platform work.
- Kubernetes or production operations.
- Turning the cloud path into the only supported demo route.
- Replacing the local portfolio demo with cloud-only infrastructure.

## Key Directories

```text
<repo>/
  assets/
    Scenes/MainScene.unity
    Scripts/
      NetworkClient.cs
      JdDemoInteractionController.cs
      JdDemoHud.cs
      GazeController.cs
      ExpressionController.cs
      GestureAnimationController.cs
      FacialAnimationController.cs
      StreamingAudioPlayer.cs
    Animations/
    Audio/
    Data/
  backend/
    app/
      main.py
      config.py
      schemas.py
      routers/
      services/
    requirements.txt
    .env.example
  frontend/
    avatar_touch.html
    sensor_controller.html
    test_avatar_touch.js
  tools/
    server_v3.py
    local_https_gateway.py
    cloud_unity_manager.py
  docs/
    architecture.md
    local-demo.md
    cloud-demo.md
    protocol.md
    testing.md
    roadmap.md
  Packages/
  ProjectSettings/
```

Do not edit Unity-generated folders: `Library/`, `Temp/`, `Logs/`, `UserSettings/`, or `Library/PackageCache/`.

## Local Smoke Test

Backend:

```powershell
cd <repo>\backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8100
```

Static files:

```powershell
cd <repo>
python -m http.server 8081 --bind 0.0.0.0
```

RenderStreaming signalling:

```powershell
cd <repo>
$env:PORT="8080"
$env:BACKEND_WS="ws://127.0.0.1:8100/ws/avatar"
$env:ICE_TRANSPORT_POLICY="all"
python tools/server_v3.py
```

Open `<repo>` in Unity Hub and run `assets/Scenes/MainScene.unity`.

Phone URLs:

```text
http://<dev-machine-lan-ip>:8081/frontend/avatar_touch.html
http://<dev-machine-lan-ip>:8081/frontend/sensor_controller.html
```

## Configuration

Priority:

```text
environment variables > backend/.env > code defaults
```

Important variables:

| Variable | Purpose |
|---|---|
| `SERVER_PORT` | FastAPI port, usually `8100` |
| `TTS_BACKEND` | `mock`, `indextts`, or `cloud` |
| `AGENT_BACKEND` | `mock`, `langgraph`, or `cloud` |
| `ASR_BACKEND` | `mock`, `faster_whisper`, or `cloud_whisper` |
| `ANTHROPIC_API_KEY` | optional LLM key |
| `ANTHROPIC_BASE_URL` | optional compatible endpoint |
| `INDEXTTS_API_URL` | optional IndexTTS HTTP service |

Do not commit `.env`.

## Testing

```powershell
cd <repo>\backend
python -m pytest -v
python -m compileall -q app
```

Focused examples:

```powershell
python -m pytest test_jd_sensor_feedback.py -q
python -m pytest test_call_ws_protocol.py -q
python -m pytest test_avatar_intent.py test_avatar_action_ws.py -q
```

Frontend simulation:

```powershell
cd <repo>
node frontend/test_avatar_touch.js
```

Unity changes require Unity Editor Play Mode verification. Report Unity, scene, and interaction path tested.

## Cloud Extension Rules

Cloud Unity/WebRTC is optional. Use templates and environment variables only:

```powershell
$env:SEETA_SSH_HOST="<cloud-ssh-host>"
$env:SEETA_SSH_PORT="<cloud-ssh-port>"
$env:SEETA_SSH_USER="<cloud-user>"
$env:SEETA_SSH_PASSWORD="<set-only-in-current-shell>"
```

Use Paramiko-based tools such as `tools/cloud_unity_manager.py` and `tools/seetacloud_port_forward.py` for cloud automation. Do not write SSH passwords, TURN credentials, API keys, or host-specific private values into docs, scripts, `.env.example`, or commits.

When using a reverse tunnel for cloud Unity to reach local backend, `CloudBackendPort=18100` is the documented default to avoid conflicts with a backend already listening on the cloud machine. Treat this as a generic port-conflict convention, not a server-specific fact.

TURN public IPs and credentials must be supplied as placeholders or runtime environment variables:

```powershell
-IceTransportPolicy relay -TurnPublicIp "<turn-public-ip>"
```

## Documentation Rules

- Commands must include `cd <repo>` or the correct relative directory.
- Distinguish mock smoke tests from real backend acceptance.
- Update `backend/.env.example` when adding configuration.
- Update `backend/app/schemas.py` and `docs/protocol.md` when adding WebSocket messages.
- Do not document real cloud hosts, SSH ports, TURN credentials, personal paths, or private run logs.

