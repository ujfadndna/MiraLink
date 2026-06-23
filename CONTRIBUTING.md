# Contributing to HerUnity

HerUnity is a Unity real-time digital human portfolio demo. Contributions should preserve the live interaction loop across phone browser, FastAPI backend, WebSocket protocol, and Unity avatar feedback.

## Setup

Requirements:

- Unity 2022.3 LTS, tested with `2022.3.62f3c1`
- Python 3.11+
- Git
- Node.js, optional for frontend simulation tests

```powershell
git clone <repo-url>
cd HerUnity

cd backend
pip install -r requirements.txt
Copy-Item .env.example .env
```

The `.env` file is optional for mock smoke tests. Real ASR/TTS/LLM acceptance requires provider-specific environment variables.

## Local Demo

Backend:

```powershell
cd <repo>\backend
uvicorn app.main:app --host 0.0.0.0 --port 8100
```

RenderStreaming signalling:

```powershell
cd <repo>
$env:PORT="8080"
$env:BACKEND_WS="ws://127.0.0.1:8100/ws/avatar"
$env:ICE_TRANSPORT_POLICY="all"
python tools/server_v3.py
```

Static files:

```powershell
cd <repo>
python -m http.server 8081 --bind 0.0.0.0
```

Open `<repo>` in Unity Hub and run `assets/Scenes/MainScene.unity`.

## Pull Requests

1. Create a branch from `main`.
2. Keep changes focused.
3. Run the relevant tests.
4. Update docs when changing protocols, configuration, or demo steps.
5. Open a PR with a clear summary and verification notes.

Suggested title prefixes: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.

## Project Boundaries

Preserve these core routes:

- Phone touch/sensor events use `/ws/sensor`.
- Unity receives avatar messages through `/ws/avatar`.
- Voice calls use `/ws/call`.
- Unity interaction feedback goes through `NetworkClient.cs` and `JdDemoInteractionController.cs`.
- Voice playback and lip sync use the ASR/TTS/Agent/viseme services and Unity audio/facial animation components.

Do not replace the main demo with static video, mock-only UI, or text input as the primary interaction path.

## Code Style

Backend:

- Keep FastAPI routers thin and put business logic in `backend/app/services/`.
- Register backend implementations through `backend/app/services/base.py`.
- Update `backend/app/schemas.py` and docs when adding WebSocket messages.

Unity:

- `NetworkClient.cs` handles connection and message dispatch.
- Interaction logic belongs in dedicated components such as `JdDemoInteractionController.cs`.
- Do not edit Unity-generated folders: `Library/`, `Temp/`, `Logs/`, `UserSettings/`.

Frontend:

- Keep `avatar_touch.html` as the clean full-screen demo entry.
- Use `sensor_controller.html` for debug controls and logs.

## Verification

Use the narrowest test set that covers your change. Common commands:

```powershell
cd <repo>\backend
python -m pytest test_jd_sensor_feedback.py -q
python -m pytest test_call_ws_protocol.py -q
python -m compileall -q app
```

For frontend behavior:

```powershell
cd <repo>
node frontend/test_avatar_touch.js
```

For Unity changes, verify in Unity Editor Play Mode and document what scene and interaction path were tested.

## Security

Never commit:

- `.env` files
- API keys or tokens
- SSH passwords
- TURN username or credential values
- private keys or certificates
- local workspaces, logs, screenshots, or diagnostics with infrastructure details

Report security issues privately. See [SECURITY.md](SECURITY.md).
