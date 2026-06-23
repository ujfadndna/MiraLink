# Testing

Run real verification before marking a change complete. Mock tests are useful, but they do not prove real ASR/TTS/LLM acceptance.

## Backend

All backend tests:

```powershell
cd <repo>\backend
python -m pytest -v
```

Focused public-release checks:

```powershell
cd <repo>\backend
python -m pytest test_avatar_intent.py test_avatar_action_ws.py test_call_ws_protocol.py test_jd_sensor_feedback.py test_runtime_diagnostics.py -q
python -m compileall -q app
```

Common focused tests:

| Change | Command |
|---|---|
| Sensor protocol or router | `python -m pytest test_jd_sensor_feedback.py -q` |
| Voice call protocol | `python -m pytest test_call_ws_protocol.py -q` |
| Avatar actions | `python -m pytest test_avatar_intent.py test_avatar_action_ws.py -q` |
| Runtime diagnostics | `python -m pytest test_runtime_diagnostics.py -q` |
| ASR adapter | `python -m pytest test_cloud_asr.py -q` |
| TTS chain | `python -m pytest test_m2_e2e.py -q` |
| Memory / affinity | `python -m pytest test_m7_memory.py -q` |

## Frontend

Run the headless runtime simulation when Node.js is installed:

```powershell
cd <repo>
node frontend/test_avatar_touch.js
```

Manual checks:

- `avatar_touch.html` normal state has no visible controls/logs/status text.
- Hidden configuration drawer opens by the documented gesture.
- Touching head/face/hand areas sends sensor events.
- `sensor_controller.html` can connect, bind, show logs, and send debug events.

## Unity

There is no full automated Unity Play Mode suite for the complete scene. For Unity changes, verify manually:

- Open `<repo>` in Unity.
- Run `assets/Scenes/MainScene.unity`.
- Confirm `NetworkClient` connects to backend.
- Confirm HUD shows state/session/FPS/latency.
- Send `shake`, `tap`, `wave`, `reset`, and at least one touch/swipe event from the phone page or debug page.
- Confirm visible feedback and no console errors.

## End-to-End

With backend and signalling running:

```powershell
cd <repo>
python tools/e2e_test.py
```

For WebRTC inspection:

```powershell
cd <repo>
python tools/avatar_touch_webrtc_stats.py
```

Treat results involving cloud TURN, GPU, HTTPS, real ASR, or real TTS as environment-dependent. If required infrastructure is missing, report it as an environment blocker rather than a code pass.

## Release Hygiene

Before publishing:

```powershell
cd <repo>
git diff --check
git ls-files | rg "(diagnostics/|docs/archive/|workspace/|Library/|Logs/|Temp/|UserSettings/|\\.env$)"
rg "D:\\\\MiraLink|C:\\\\Users\\\\|connect\\.westb\\.seetacloud\\.com|124\\.222\\.184\\.71" -n
rg "BEGIN .*PRIVATE KEY" -n
rg "sk-proj-|sk-" -n
```

The `git ls-files` command should not list local runtime outputs, archives, generated Unity folders, or `.env`.
