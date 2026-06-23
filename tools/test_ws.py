import asyncio, websockets, json

async def test_backend_ws():
    print("Testing backend WS...")
    try:
        ws = await asyncio.wait_for(
            websockets.connect("ws://127.0.0.1:8100/ws/avatar"),
            timeout=5
        )
        print("Backend WS: CONNECTED")
        await ws.send(json.dumps({"type": "chat", "text": "hello"}))
        print("Sent: chat message")
        try:
            resp = await asyncio.wait_for(ws.recv(), timeout=10)
            print(f"Received: {resp[:300]}")
        except asyncio.TimeoutError:
            print("No response (timeout)")
        await ws.close()
    except Exception as e:
        print(f"Backend WS FAILED: {type(e).__name__}: {e}")

async def test_signalling():
    print("Testing signalling WS on :80...")
    try:
        ws = await asyncio.wait_for(
            websockets.connect("ws://127.0.0.1:80"),
            timeout=5
        )
        print("Signalling WS: CONNECTED (viewer)")
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"Received: {msg[:300]}")
        except asyncio.TimeoutError:
            print("No init message from signalling")
        await ws.close()
    except Exception as e:
        print(f"Signalling WS FAILED: {type(e).__name__}: {e}")

async def main():
    await test_backend_ws()
    print("---")
    await test_signalling()

asyncio.run(main())
