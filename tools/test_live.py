"""Test HerUnity signalling + backend proxy"""
import asyncio, websockets, json

async def test_backend_proxy():
    """Test /ws/avatar proxy through signalling :80"""
    print("Testing backend proxy on :80/ws/avatar...")
    try:
        ws = await asyncio.wait_for(
            websockets.connect("ws://127.0.0.1:80/ws/avatar"),
            timeout=5
        )
        print("PROXY_OK: connected to backend via signalling proxy")
        await ws.send(json.dumps({"type": "turn.submit_text", "session_id": "", "text": "hello"}))
        resp = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(resp)
        print(f"Response type: {data.get('type', '?')}")
        await ws.close()
    except Exception as e:
        print(f"PROXY_FAIL: {type(e).__name__}: {e}")

async def test_viewer_ws():
    """Test viewer connection to signalling (should trigger connect to streamer)"""
    print("Testing viewer WS on :80...")
    try:
        ws = await asyncio.wait_for(
            websockets.connect("ws://127.0.0.1:80"),
            timeout=5
        )
        print("VIEWER_OK: connected to signalling")
        # Wait for any message (offer from streamer via signalling)
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            print(f"Received: type={data.get('type', '?')}")
            if data.get('type') == 'offer':
                print("GOT_OFFER: WebRTC negotiation started!")
        except asyncio.TimeoutError:
            print("No offer received (streamer might not be creating offer)")
        await ws.close()
    except Exception as e:
        print(f"VIEWER_FAIL: {type(e).__name__}: {e}")

async def main():
    await test_backend_proxy()
    print("---")
    await test_viewer_ws()

asyncio.run(main())
