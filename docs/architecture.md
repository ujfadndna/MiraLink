# Architecture

MiraLink connects a mobile browser, a FastAPI backend, and a Unity digital human scene.

## Runtime Paths

### Phone Interaction

```text
Phone browser
  -> /ws/sensor
  -> FastAPI backend
  -> sensor.feedback
  -> Unity /ws/avatar
  -> JdDemoInteractionController
  -> state, expression, gesture, HUD, SFX, VFX
```

The phone can use the clean demo page (`frontend/avatar_touch.html`) or the debug controller (`frontend/sensor_controller.html`). Both send structured sensor events and bind to a Unity session.

### Voice Call

```text
Phone/browser microphone or audio source
  -> /ws/call
  -> ASR backend
  -> LLM/Agent backend
  -> TTS backend
  -> viseme curve
  -> Unity /ws/avatar
  -> StreamingAudioPlayer + FacialAnimationController
```

Mock ASR/TTS/Agent backends are smoke-test tools. Real acceptance requires a non-mock backend for each required stage.

### Video

```text
Unity MainScene
  -> RenderStreaming VideoStreamSender
  -> tools/server_v3.py signalling
  -> phone browser WebRTC viewer
```

Local demos usually use `ICE_TRANSPORT_POLICY=all`. Cloud demos typically require a reachable TURN server and credentials supplied at runtime.

## Main Components

| Area | Component |
|---|---|
| Backend entry | `backend/app/main.py` |
| Protocol models | `backend/app/schemas.py` |
| Avatar WebSocket | `backend/app/routers/ws.py` |
| Sensor WebSocket | `backend/app/routers/sensor_ws.py` |
| Voice call WebSocket | `backend/app/routers/call_ws.py` |
| Backend factory | `backend/app/services/base.py` |
| ASR/TTS/Agent | `backend/app/services/asr.py`, `tts.py`, `agent.py` |
| Sensor rules | `backend/app/services/sensor.py` |
| Visemes | `backend/app/services/viseme.py` |
| Unity networking | `assets/Scripts/NetworkClient.cs` |
| Unity feedback | `assets/Scripts/JdDemoInteractionController.cs` |
| Unity HUD | `assets/Scripts/JdDemoHud.cs` |
| Lip sync | `assets/Scripts/FacialAnimationController.cs` |
| Audio playback | `assets/Scripts/StreamingAudioPlayer.cs` |

## State and Feedback

The Unity scene exposes a compact state model for demo visibility:

- `Idle`
- `Connected`
- `Reacting`
- `Speaking`
- `Reconnecting`
- `Error`

Sensor events should produce at least two visible feedback categories where practical: expression, movement, gesture, HUD change, SFX, VFX, score, energy, or affinity.

## Configuration

Backend configuration priority:

```text
environment variables > backend/.env > code defaults
```

Keep secrets out of the repository. Use `backend/.env.example` and `deploy/.env.example` as templates only.

