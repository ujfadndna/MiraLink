"""M2 full E2E: start server + run WebSocket test against it.
Prerequisite: backend/.env must exist with LLM credentials.
"""
import sys, io, asyncio, json, os, subprocess, time, threading

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load .env into os.environ before starting anything
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)

PORT = "8112"  # fixed port to avoid conflicts with lingering servers

# Start uvicorn as subprocess with loaded env
env = os.environ.copy()
server = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", PORT],
    cwd=os.path.dirname(os.path.abspath(__file__)),
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)

# Drain server stdout so we can see errors
def drain():
    for line in server.stdout:
        print("[SVR]", line.decode(errors='replace').rstrip())
threading.Thread(target=drain, daemon=True).start()
time.sleep(3)
print(f"=== Server started (pid={server.pid}) ===")

import websockets
import httpx

async def main():
    try:
        ws = await websockets.connect(f'ws://127.0.0.1:{PORT}/ws/avatar')

        # Session start
        await ws.send(json.dumps({'type': 'session.start', 'avatar_id': 'vrm_female_001', 'language': 'zh'}))
        m = json.loads(await ws.recv())
        assert m['type'] == 'session.started', f'FAIL: {m}'
        sid = m['session_id']
        print(f'1. Session: {sid}')
        await ws.recv()  # idle
        print('2. State: idle')

        # Turn 1
        await ws.send(json.dumps({'type': 'turn.submit_text', 'session_id': sid, 'text': '你好，介绍一下你自己'}))
        m = json.loads(await ws.recv())
        print(f'3. GOT: {m["type"]}')
        if m['type'] == 'error':
            print(f'FAIL: {m["message"]}')
            return
        assert m['state'] == 'thinking', f'Expected thinking, got {m}'
        print('   -> thinking')

        m = json.loads(await ws.recv())
        print(f'4. GOT: {m["type"]}')
        if m['type'] == 'error':
            print(f'FAIL: {m["message"]}')
            return
        assert m['type'] == 'turn.start', f'Expected turn.start, got {m}'
        print(f'   Turn: emotion={m.get("emotion")} act={m.get("dialogue_act")}')

        await ws.recv()  # speaking
        print('5. -> speaking')

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

        await ws.recv()  # idle
        print('7. -> idle')

        # Turn 2: context follow-up
        await ws.send(json.dumps({'type': 'turn.submit_text', 'session_id': sid, 'text': '你刚才说的核心算法是什么'}))
        await ws.recv()  # thinking
        m = json.loads(await ws.recv())  # turn.start
        print(f'8. Turn2: emotion={m.get("emotion")} act={m.get("dialogue_act")}')

        while True:
            m = json.loads(await ws.recv())
            if m['type'] == 'state.change' and m['state'] == 'idle':
                print('9. -> idle')
                break

        # Turn 3: safety
        await ws.send(json.dumps({'type': 'turn.submit_text', 'session_id': sid, 'text': '我想自杀'}))
        await ws.recv()  # thinking
        m = json.loads(await ws.recv())  # turn.start
        print(f'10. Safety: emotion={m.get("emotion")} (expect sad)')

        while True:
            m = json.loads(await ws.recv())
            if m['type'] == 'state.change' and m['state'] == 'idle':
                print('11. -> idle')
                break

        # Verify session history
        async with httpx.AsyncClient() as c:
            r = await c.get(f'http://127.0.0.1:{PORT}/api/v1/sessions')
            sessions = r.json()
            s = sessions[-1]
            print(f'12. Session: {s["turn_count"]} turns')
            for t in s['turns']:
                print(f'    [{t["emotion"]}/{t["dialogue_act"]}] {t["user_text"][:30]} -> {t["reply_text"][:50]}')

        await ws.close()
        print('=== ALL PASSED ===')

    finally:
        server.terminate()
        server.wait()

asyncio.run(main())
