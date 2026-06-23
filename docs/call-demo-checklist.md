# Call Demo Checklist

Use this checklist when validating the real voice path.

## Environment

Configure real backends in `backend/.env` or the current shell:

```text
ASR_BACKEND=faster_whisper or cloud_whisper
AGENT_BACKEND=langgraph or cloud
TTS_BACKEND=indextts or cloud
ANTHROPIC_API_KEY=<your-key>
ANTHROPIC_BASE_URL=<optional-compatible-base-url>
INDEXTTS_API_URL=<optional-indextts-http-url>
```

Mock backends are allowed only for smoke tests.

## Startup

```powershell
cd <repo>\backend
uvicorn app.main:app --host 0.0.0.0 --port 8100
```

```powershell
cd <repo>
$env:PORT="8080"
$env:BACKEND_WS="ws://127.0.0.1:8100/ws/avatar"
python tools/server_v3.py
```

Open `<repo>` in Unity and run `assets/Scenes/MainScene.unity`.

## Acceptance

- [ ] Phone or browser connects to `/ws/call`.
- [ ] `call.start` succeeds.
- [ ] Audio chunks are accepted.
- [ ] ASR returns real recognized text.
- [ ] LLM/Agent returns a real response.
- [ ] TTS returns speech audio.
- [ ] Viseme curve is generated or forwarded.
- [ ] Unity receives avatar messages.
- [ ] Unity plays audio.
- [ ] Unity facial animation/lip sync is visible.
- [ ] Interrupt or stop behavior does not crash the session.

## Notes

Do not record or commit private voice samples, prompt paths, generated workspaces, API keys, or run logs.
