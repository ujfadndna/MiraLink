# HerUnity

HerUnity is a portfolio demo for a real-time Unity digital human: a phone browser streams the Unity scene, sends touch and sensor-like events over WebSocket, and drives a VRM avatar's animation, facial expression, UI, sound, particles, and optional voice response chain.

> Demo media: add a short GIF or screenshot here after recording the public demo.

## What It Shows

```text
Phone browser
  -> WebRTC viewer for Unity RenderStreaming video
  -> WebSocket sensor/touch events
  -> FastAPI backend
  -> Unity /ws/avatar
  -> avatar state, gesture, expression, HUD, SFX, VFX

Voice input
  -> ASR
  -> LLM/Agent
  -> TTS + viseme curve
  -> Unity audio playback, lip sync, expression, gesture
```

The project is intentionally presented as a demo, not a production SDK. The core goal is to prove a live interaction loop across mobile web, backend services, and Unity.

## Current Status

- Local phone-to-Unity interaction loop is implemented.
- `frontend/avatar_touch.html` is the clean demo entry: full-screen Unity video with hidden touch handling.
- `frontend/sensor_controller.html` is the debug controller: video, buttons, connection state, and logs.
- Backend supports mock and real ASR/TTS/LLM adapters. Mock mode is for smoke tests only.
- Unity contains a VRM avatar scene, WebSocket client, interaction controller, HUD, expression, gaze, gesture, audio, and lip-sync components.
- Cloud WebRTC is documented as an optional extension, not the default demo path.

## Features

- Mobile browser as a hardware-like controller: tap, hold, swipe, shake simulation, and debug buttons.
- Unity RenderStreaming video on the phone browser.
- WebSocket protocol for `/ws/sensor`, `/ws/avatar`, and `/ws/call`.
- Digital human feedback: facial expression, head/gaze movement, gestures, UI state, SFX, particles, energy, affinity, and score.
- Voice pipeline adapters: ASR -> LLM/Agent -> TTS -> viseme/lip sync -> Unity playback.
- Session binding, acknowledgements, reconnect/error states, and runtime diagnostics.

## Quick Start

Prerequisites:

- Unity 2022.3 LTS, tested with `2022.3.62f3c1`
- Python 3.11+
- A phone and development machine on the same local network
- Optional real ASR/TTS/LLM services for full voice acceptance

### Mock Smoke Test

Mock mode verifies that the local services, WebSocket protocol, Unity connection, and browser pages can start. It does not prove the real ASR/TTS/LLM chain.

Terminal 1, backend:

```powershell
cd <repo>\backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8100
```

Terminal 2, RenderStreaming signalling:

```powershell
cd <repo>
$env:PORT="8080"
$env:BACKEND_WS="ws://127.0.0.1:8100/ws/avatar"
$env:ICE_TRANSPORT_POLICY="all"
python tools/server_v3.py
```

Terminal 3, static files:

```powershell
cd <repo>
python -m http.server 8081 --bind 0.0.0.0
```

Unity:

```text
Open <repo> in Unity Hub.
Run assets/Scenes/MainScene.unity.
```

Phone:

```text
http://<dev-machine-lan-ip>:8081/frontend/avatar_touch.html
http://<dev-machine-lan-ip>:8081/frontend/sensor_controller.html
```

Use the Unity HUD session ID when binding the phone page. Each Unity Play Mode restart can generate a new session.

### Real ASR/TTS/LLM Acceptance

For the full voice chain, configure real backends through environment variables or `backend/.env` copied from `backend/.env.example`.

```powershell
cd <repo>\backend
Copy-Item .env.example .env
```

Then set the relevant values:

```text
AGENT_BACKEND=langgraph or cloud
ASR_BACKEND=faster_whisper or cloud_whisper
TTS_BACKEND=indextts or cloud
ANTHROPIC_API_KEY=<your-key>
ANTHROPIC_BASE_URL=<optional-compatible-endpoint>
INDEXTTS_API_URL=<optional-indextts-http-url>
```

Mock results are useful for smoke tests but must not be used as evidence that real voice input, ASR, LLM/Agent, TTS, viseme generation, Unity playback, and lip sync are complete.

## Repository Layout

```text
HerUnity/
  assets/                         Unity scene, scripts, animations, audio, data, model
  backend/                        FastAPI app, WebSocket routers, ASR/TTS/Agent services
  frontend/                       phone demo page and debug controller
  tools/                          signalling server, local gateway, diagnostics, cloud helpers
  scripts/                        test, build, and demo helper scripts
  docs/                           architecture, local demo, cloud demo, protocol, testing, roadmap
  deploy/                         deployment templates
  Packages/com.unity.renderstreaming/
  ProjectSettings/
```

Unity-generated directories such as `Library/`, `Temp/`, `Logs/`, and `UserSettings/` are intentionally ignored.

## Documentation

- [Architecture](docs/architecture.md)
- [Local Demo](docs/local-demo.md)
- [Cloud Demo](docs/cloud-demo.md)
- [Protocol](docs/protocol.md)
- [Testing](docs/testing.md)
- [Roadmap](docs/roadmap.md)
- [Acceptance Notes](docs/jd-demo-plan.md)

## Development

Run focused backend tests:

```powershell
cd <repo>\backend
python -m pytest test_avatar_intent.py test_avatar_action_ws.py test_call_ws_protocol.py test_jd_sensor_feedback.py test_runtime_diagnostics.py -q
python -m compileall -q app
```

Run the browser page simulation when Node.js is available:

```powershell
cd <repo>
node frontend/test_avatar_touch.js
```

Format Python code:

```powershell
cd <repo>\backend
black .
isort .
ruff check .
```

## Security

Do not commit `.env`, API keys, SSH passwords, TURN credentials, certificates, private keys, screenshots with private infrastructure details, or local run workspaces. See [SECURITY.md](SECURITY.md).

If a secret has ever been placed in a local `.env` or log file, rotate it before publishing the repository.

## License

MIT License. See [LICENSE](LICENSE).
