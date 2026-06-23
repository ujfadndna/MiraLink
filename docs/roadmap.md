# Roadmap

HerUnity is scoped as a portfolio demo for a real-time Unity digital human. The main path is local and reproducible; cloud streaming and production operations are optional extensions.

## Completed Core Work

- Unity scene with VRM avatar and RenderStreaming components.
- Backend WebSocket routes for avatar, sensor, and voice call flows.
- Phone debug controller with video, controls, connection state, and logs.
- Clean phone touch page for full-screen demo mode.
- Immediate `sensor.feedback` path from phone input to Unity feedback.
- HUD state, last event, latency, FPS, energy, affinity, and score display.
- Mock backend mode for local smoke tests.
- Adapter structure for real ASR, TTS, LLM/Agent, and viseme generation.

## Current Priorities

1. Keep the local demo stable and easy to run.
2. Verify `avatar_touch.html` on a real phone in portrait mode.
3. Verify swipe and touch mapping against the live Unity video.
4. Run the real voice chain with non-mock ASR/TTS/LLM backends.
5. Run local Unity Standalone regression.
6. Confirm two-minute continuous interaction stability.
7. Record a short public demo video or GIF.
8. Keep public docs concise and free of private infrastructure details.

## Optional Extensions

- Cloud Unity RenderStreaming through HTTPS/WSS gateway and TURN.
- Real IndexTTS or cloud TTS services.
- faster-whisper or cloud ASR.
- Visual perception with MediaPipe or similar systems.
- More advanced gameplay loops around affinity, energy, score, and combo rules.
- Longer-running process management for hosted demos.

## Non-Goals

- Production SaaS deployment.
- Multi-tenant user management.
- Kubernetes or large-scale operations.
- Replacing the phone/Unity live loop with a static demo.
- Treating mock ASR/TTS/LLM as proof of real voice acceptance.

