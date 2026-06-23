"""Simulate a browser viewer connecting to signalling server"""
import asyncio, websockets, json

async def test():
    uri = "ws://127.0.0.1:80"
    async with websockets.connect(uri) as ws:
        print(f"Connected as viewer")
        msgs = []
        for i in range(8):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=8.0)
                data = json.loads(msg)
                t = data.get('type', '?')
                print(f"Got[{i}]: type={t} keys={list(data.keys())}")
                if t == "welcome":
                    print(f"  connectionId={data.get('connectionId')}")
                elif t == "offer":
                    print(f"  from={data.get('from')} sdp={data.get('data',{}).get('sdp','')[:60]}")
                    # Send answer back
                    cid = data.get('from', 'test-id')
                    answer = {
                        "from": cid,
                        "type": "answer",
                        "data": {"sdp": "v=0\r\no=- 0 0 IN IP4 0.0.0.0\r\ns=-\r\nt=0 0\r\n"}
                    }
                    await ws.send(json.dumps(answer))
                    print(f"  Sent answer from={cid}")
                    break
                msgs.append(data)
            except asyncio.TimeoutError:
                print(f"Timeout[{i}] - no more messages")
                break
        print(f"Total: {len(msgs)} messages")

        # Wait for ICE candidates
        for i in range(3):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(msg)
                print(f"Post[{i}]: type={data.get('type','?')}")
            except asyncio.TimeoutError:
                break

        await asyncio.sleep(1)

asyncio.run(test())
