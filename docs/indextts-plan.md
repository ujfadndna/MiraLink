# IndexTTS Notes

IndexTTS is an optional TTS backend for the real voice acceptance path.

## Positioning

The local demo can smoke-test with `TTS_BACKEND=mock`, but real voice acceptance requires a non-mock TTS backend such as IndexTTS or a cloud TTS service.

## Configuration

Set in `backend/.env` or the current shell:

```text
TTS_BACKEND=indextts
INDEXTTS_API_URL=http://127.0.0.1:9001
TTS_SAMPLE_RATE=24000
```

If the IndexTTS service runs remotely, expose it through a private tunnel or secure endpoint and set:

```text
INDEXTTS_API_URL=<indextts-http-url>
```

Do not commit:

- remote server paths
- prompt audio paths from private machines
- generated audio outputs
- API keys or SSH credentials
- local workspace reports

## Acceptance

Real TTS acceptance should verify:

- backend can call `POST /tts` on the configured IndexTTS service
- returned audio is speech, not a synthetic smoke-test tone
- generated audio can be forwarded through the call pipeline
- Unity plays the audio through the configured player
- viseme/lip-sync data aligns well enough for the demo

## Smoke Test Boundary

Mock TTS proves only protocol flow and Unity playback plumbing. It does not prove real voice quality, cloning, latency, or production readiness.
