"""M2 E2E integration test — WebSocket full pipeline."""
import sys, io, asyncio, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    import websockets
    ws = await websockets.connect('ws://127.0.0.1:8110/ws/avatar')

    # Session start
    await ws.send(json.dumps({'type': 'session.start', 'avatar_id': 'vrm_female_001', 'language': 'zh'}))
    m = json.loads(await ws.recv())
    assert m['type'] == 'session.started', f'FAIL session.started: {m}'
    sid = m['session_id']
    print(f'1. Session: {sid}')
    m = json.loads(await ws.recv())
    print(f'2. State: {m["state"]}')

    # Turn 1: self-intro
    await ws.send(json.dumps({'type': 'turn.submit_text', 'session_id': sid, 'text': '你好，介绍一下你自己'}))
    m = json.loads(await ws.recv())
    assert m['type'] == 'state.change' and m['state'] == 'thinking', f'FAIL thinking: {m}'
    print(f'3. -> {m["state"]}')

    m = json.loads(await ws.recv())
    assert m['type'] == 'turn.start', f'FAIL turn.start: {m}'
    print(f'4. Turn: emotion={m.get("emotion")} act={m.get("dialogue_act")}')

    m = json.loads(await ws.recv())
    print(f'5. -> {m["state"]}')

    # Drain to turn.end
    count = 0
    while True:
        m = json.loads(await ws.recv())
        if m['type'] == 'turn.end':
            print(f'6. Turn end ({count} chunks)')
            break
        elif m['type'] == 'error':
            print(f'FAIL: {m["message"]}')
            return
        count += 1

    m = json.loads(await ws.recv())
    assert m['state'] == 'idle', f'FAIL idle: {m}'
    print(f'7. -> {m["state"]}')

    # Turn 2: context follow-up
    await ws.send(json.dumps({'type': 'turn.submit_text', 'session_id': sid, 'text': '你刚才说你的核心算法是什么'}))
    m = json.loads(await ws.recv())  # thinking
    m = json.loads(await ws.recv())  # turn.start
    print(f'8. Turn2: emotion={m.get("emotion")} act={m.get("dialogue_act")}')

    while True:
        m = json.loads(await ws.recv())
        if m['type'] == 'state.change' and m['state'] == 'idle':
            print(f'9. -> idle')
            break

    # Verify session history
    import httpx
    async with httpx.AsyncClient() as c:
        r = await c.get('http://127.0.0.1:8110/api/v1/sessions')
        sessions = r.json()
        s = sessions[-1]
        print(f'10. Session: {s["turn_count"]} turns')
        for t in s['turns']:
            print(f'    [{t["emotion"]}/{t["dialogue_act"]}] {t["user_text"]} -> {t["reply_text"][:40]}...')

    await ws.close()
    print('ALL PASSED')

asyncio.run(main())
