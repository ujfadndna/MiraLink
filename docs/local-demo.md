# Local Demo

This is the default portfolio demo path. It does not require cloud GPU, TURN, NVENC, or public hosting.

## Requirements

- Unity 2022.3 LTS, tested with `2022.3.62f3c1`
- Python 3.11+
- Phone and development machine on the same Wi-Fi

## 1. Start Backend

```powershell
cd <repo>\backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8100
```

Check:

```powershell
Invoke-RestMethod http://127.0.0.1:8100/health
```

## 2. Start RenderStreaming Signalling

```powershell
cd <repo>
$env:PORT="8080"
$env:BACKEND_WS="ws://127.0.0.1:8100/ws/avatar"
$env:ICE_TRANSPORT_POLICY="all"
python tools/server_v3.py
```

## 3. Start Static File Server

```powershell
cd <repo>
python -m http.server 8081 --bind 0.0.0.0
```

## 4. Start Unity

Open `<repo>` in Unity Hub and run:

```text
assets/Scenes/MainScene.unity
```

Unity should connect to signalling at:

```text
ws://127.0.0.1:8080
```

## 5. Open Phone Page

Find the development machine LAN IP, then open one of:

```text
http://<dev-machine-lan-ip>:8081/frontend/avatar_touch.html
http://<dev-machine-lan-ip>:8081/frontend/sensor_controller.html
```

Use the Unity HUD session ID when binding the phone page. Each Unity Play Mode restart may create a new session.

## Expected Result

- Phone page connects to backend.
- Phone page receives Unity video.
- Unity HUD shows connection/session state.
- `tap`, `hold`, `swipe`, `shake`, `wave`, or `reset` events produce Unity feedback.
- Feedback appears in the Unity scene and in the streamed video.

## Troubleshooting

Phone cannot load the page:

- Confirm both devices are on the same network.
- Use the machine LAN IP, not `localhost`.
- Confirm static server is listening on `0.0.0.0:8081`.

Video does not play:

- Confirm `tools/server_v3.py` is running on `8080`.
- Close duplicate viewer tabs.
- Use `ICE_TRANSPORT_POLICY=all` for local same-Wi-Fi testing unless TURN is explicitly configured.

Controls do nothing:

- Confirm backend is connected.
- Re-bind using the current Unity HUD session ID.
- If Unity was restarted, refresh or re-bind the phone page.

