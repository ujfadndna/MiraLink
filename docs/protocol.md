# WebSocket Protocol

This document lists the main public protocol messages used by the demo. Field sets are intentionally concise; see `backend/app/schemas.py` and the routers for implementation details.

## `/ws/sensor`

Phone browser to backend.

### `sensor.bind`

Binds a phone page to a Unity avatar session.

```json
{
  "type": "sensor.bind",
  "session_id": "<unity-session-id>"
}
```

Common responses:

```json
{ "type": "sensor.bound", "session_id": "<unity-session-id>" }
{ "type": "sensor.waiting_session", "session_id": "<unity-session-id>" }
```

### `sensor.event`

Sends a touch or sensor-like event.

```json
{
  "type": "sensor.event",
  "event": "tap_head",
  "strength": 0.82,
  "timestamp": 1780000000000,
  "payload": {
    "x": 0.5,
    "y": 0.3
  }
}
```

Common event names include:

- `tap`
- `tap_head`
- `tap_face`
- `tap_hand`
- `hold_*`
- `swipe_left`
- `swipe_right`
- `swipe_up`
- `swipe_down`
- `shake`
- `wave`
- `reset`

### `sensor.ack`

Backend acknowledgement to phone.

```json
{
  "type": "sensor.ack",
  "event": "tap_head",
  "session_id": "<unity-session-id>",
  "latency_ms": 42
}
```

## `/ws/avatar`

Unity to backend and backend to Unity.

### `avatar.hello`

Unity registers an avatar session with the backend.

```json
{
  "type": "avatar.hello",
  "session_id": "<unity-session-id>"
}
```

### `sensor.feedback`

Backend forwards immediate interaction feedback to Unity.

```json
{
  "type": "sensor.feedback",
  "session_id": "<unity-session-id>",
  "event": "tap_head",
  "emotion": "happy",
  "gesture": "nod",
  "energy": 38,
  "affinity": 12,
  "score": 100,
  "latency_ms": 42
}
```

Unity consumes this through `NetworkClient.cs` and routes it to feedback components.

### `avatar.anchors`

Unity can publish screen-space or normalized hit targets to bound sensor clients. `avatar_touch.html` uses these for cleaner touch mapping and falls back to static regions when anchors are unavailable.

```json
{
  "type": "avatar.anchors",
  "session_id": "<unity-session-id>",
  "anchors": [
    { "name": "head", "x": 0.5, "y": 0.22, "radius": 0.08 }
  ]
}
```

## `/ws/call`

Phone/browser voice call to backend.

### `call.start`

```json
{
  "type": "call.start",
  "session_id": "<unity-session-id>",
  "sample_rate": 16000
}
```

### `call.audio`

```json
{
  "type": "call.audio",
  "pcm_b64": "<base64-pcm-int16-mono-16khz>"
}
```

### `call.stop`

```json
{ "type": "call.stop" }
```

### Backend responses

```json
{ "type": "call.started", "session_id": "<unity-session-id>" }
{ "type": "call.state", "state": "listening" }
{ "type": "call.audio.start", "turn_id": "<turn-id>" }
{ "type": "call.audio.chunk", "turn_id": "<turn-id>", "audio_b64": "<base64>" }
{ "type": "call.audio.end", "turn_id": "<turn-id>" }
{ "type": "call.error", "message": "<message>", "recoverable": true }
```

## Compatibility Rule

When adding or changing a message:

1. Update `backend/app/schemas.py`.
2. Update the relevant router/service.
3. Update Unity parsing if Unity consumes it.
4. Update this document and focused tests.

