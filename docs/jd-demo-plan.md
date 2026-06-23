# Acceptance Notes

HerUnity is a portfolio demo for real-time Unity digital human interaction.

## Main Acceptance Path

```text
Phone browser
  -> Unity RenderStreaming video
  -> touch / hold / swipe / shake simulation
  -> /ws/sensor
  -> FastAPI backend
  -> /ws/avatar
  -> Unity avatar feedback
```

The formal demo page is `frontend/avatar_touch.html`. It should remain clean in normal state: no default visible controls, logs, labels, status bars, or anchor markers.

The debug page is `frontend/sensor_controller.html`. It may show video, controls, session binding, logs, and connection state.

## Voice Acceptance Path

```text
Voice input
  -> ASR
  -> LLM/Agent
  -> TTS + viseme
  -> Unity playback and lip sync
```

Mock ASR/TTS/Agent is acceptable for smoke testing only. Full voice acceptance requires real, non-mock backends for the intended demo configuration.

## Current Capability Checklist

- [x] Backend exposes `/ws/avatar`, `/ws/sensor`, and `/ws/call`.
- [x] Unity `MainScene` contains avatar, network client, HUD, and feedback controllers.
- [x] Phone debug page can send sensor events.
- [x] Clean touch page exists for full-screen demo mode.
- [x] `sensor.feedback` drives Unity-visible feedback.
- [x] HUD displays session, state, last event, latency, FPS, energy, affinity, and score.
- [x] Local RenderStreaming signalling is available through `tools/server_v3.py`.
- [ ] Real phone portrait validation for `avatar_touch.html`.
- [ ] Live swipe validation on phone.
- [ ] Real ASR -> LLM/Agent -> TTS -> viseme -> Unity playback/lip-sync validation.
- [ ] Local Unity Standalone regression.
- [ ] Two-minute continuous interaction stability pass.
- [ ] Public demo video or GIF.

## Feedback Requirements

Each primary interaction should produce visible feedback through at least two categories where practical:

- expression change
- head/gaze movement
- gesture or body motion
- Unity HUD/UI change
- sound effect
- particles or VFX
- energy, affinity, score, or combo change

Target interaction latency for the local demo is under 300 ms from phone event to visible Unity feedback under normal conditions.

## State Requirements

Unity should keep these states observable:

- `Idle`
- `Connected`
- `Reacting`
- `Speaking`
- `Reconnecting`
- `Error`

Unknown messages, malformed JSON, stale sessions, and disconnects should not crash Unity or the backend.

## Local Demo Ports

| Port | Service |
|---:|---|
| `8100` | FastAPI backend |
| `8080` | RenderStreaming signalling |
| `8081` | static phone pages |

See [local-demo.md](local-demo.md) for startup commands.

## Demo Script

1. Start backend, signalling, static server, and Unity `MainScene`.
2. Open `avatar_touch.html` on a phone.
3. Bind the phone page to the Unity HUD session.
4. Confirm Unity video appears on the phone.
5. Touch avatar regions such as head, face, or hand.
6. Trigger a hold or swipe gesture.
7. Show visible avatar state, gesture, expression, HUD, SFX/VFX, and score/energy changes.
8. Optionally switch to `sensor_controller.html` to show debug logs and manual buttons.
9. For voice, run the real ASR/TTS/LLM configuration and show playback with lip sync.

## Optional Cloud Extension

Cloud Unity/WebRTC is documented in [cloud-demo.md](cloud-demo.md). It is useful as an extension, but it is not the default acceptance path for the local portfolio demo.
