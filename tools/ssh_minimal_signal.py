import paramiko

import os
host = os.environ["CLOUD_SSH_HOST"]
port = int(os.environ.get("CLOUD_SSH_PORT", "22"))
user = os.environ.get("CLOUD_SSH_USER", "root")
pw   = os.environ["CLOUD_SSH_PASSWORD"]

def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, port=port, username=user, password=pw, timeout=20)
    return ssh

def run(ssh, cmd, timeout=30):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode().strip()
    err = e.read().decode().strip()
    result = out or err or '(empty)'
    print(f'$ {cmd[:80]}\n  {result[:300]}')
    return out

def upload_file(ssh, local_content, remote_path):
    """Upload file content via SFTP"""
    sftp = ssh.open_sftp()
    with sftp.open(remote_path, 'w') as f:
        f.write(local_content)
    sftp.close()
    print(f'  [uploaded] {remote_path}')

ssh = connect()

# Minimal Unity RenderStreaming signalling server
# Implements the WebSocket protocol that Unity's SignalingManager expects:
# - /signaling endpoint for Unity streamer
# - /signaling endpoint for browser viewer
# Uses only built-in Node.js 'ws' package (pure websocket)

run(ssh, 'mkdir -p /data/signalling && cd /data/signalling && npm init -y 2>&1 | tail -1')
run(ssh, 'cd /data/signalling && npm install ws 2>&1 | tail -3', timeout=60)

# Write the minimal signalling server
signalling_server = r'''
// Unity RenderStreaming minimal signalling server
// Protocol ref: https://github.com/Unity-Technologies/UnityRenderStreaming
const WebSocket = require('ws');
const http = require('http');

const HTTP_PORT = parseInt(process.env.HTTP_PORT || '80');
const WS_PORT   = parseInt(process.env.WS_PORT   || '8888');

// Simple HTTP server (serves basic page for browser)
const htmlPage = `<!DOCTYPE html>
<html><head><title>HerUnity Stream</title></head>
<body style="margin:0;background:#000;font-family:sans-serif;overflow:hidden">
<video id="v" autoplay playsinline style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:contain"></video>
<div id="hud" style="position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,0.7);padding:10px;display:flex;gap:8px;align-items:center">
  <span id="status" style="color:#4f4;font-size:12px;min-width:60px">● idle</span>
  <input id="msg" type="text" placeholder="输入消息..." style="flex:1;padding:10px;border:1px solid #333;border-radius:6px;background:#1a1a2e;color:#fff;font-size:14px" disabled>
  <button id="send" onclick="sendText()" style="padding:10px 16px;background:#4f4;border:none;border-radius:6px;color:#000;font-weight:bold;font-size:14px" disabled>发送</button>
</div>
<script>
const WS_PORT = '${WS_PORT}';
const BACKEND_PORT = '8100';
let ws, pc, sessionId;
const statusEl = document.getElementById('status');
const msgEl = document.getElementById('msg');
const sendBtn = document.getElementById('send');

function setStatus(txt, color) { statusEl.textContent = txt; statusEl.style.color = color; }

// WebRTC video signalling
ws = new WebSocket('ws://' + location.hostname + ':' + WS_PORT);
ws.onmessage = async e => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'offer') {
    pc = new RTCPeerConnection({iceServers:[{urls:'stun:stun.l.google.com:19302'}]});
    pc.ontrack = ev => { document.getElementById('v').srcObject = ev.streams[0]; setStatus('● connected','#48f'); };
    pc.onicecandidate = ev => { if(ev.candidate) ws.send(JSON.stringify({type:'candidate',candidate:ev.candidate})); };
    await pc.setRemoteDescription(msg);
    const ans = await pc.createAnswer();
    await pc.setLocalDescription(ans);
    ws.send(JSON.stringify({type:'answer',sdp:ans.sdp}));
  } else if (msg.type === 'candidate' && pc) {
    await pc.addIceCandidate(msg.candidate);
  }
};

// AI chat via backend WebSocket
async function connectChat() {
  const chatWs = new WebSocket('ws://' + location.hostname + ':' + BACKEND_PORT + '/ws/avatar');
  chatWs.onopen = () => {
    chatWs.send(JSON.stringify({type:'session.start',avatar_id:'vrm_female_001',language:'zh'}));
  };
  chatWs.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.type === 'session.started') { sessionId = m.session_id; msgEl.disabled = false; sendBtn.disabled = false; setStatus('● idle','#4f4'); }
    else if (m.type === 'state.change') { setStatus('● '+m.state, m.state==='thinking'?'#ff4':m.state==='speaking'?'#48f':'#4f4'); }
  };
  chatWs.onclose = () => { sessionId = null; msgEl.disabled = true; sendBtn.disabled = true; setStatus('● disconnected','#f44'); };
  return chatWs;
}
const chatWs = connectChat();

function sendText() {
  if (!sessionId || !msgEl.value.trim()) return;
  chatWs.send(JSON.stringify({type:'turn.submit_text',session_id:sessionId,text:msgEl.value.trim()}));
  msgEl.value = '';
}
msgEl.addEventListener('keydown', e => { if (e.key==='Enter') sendText(); });
</script></body></html>`;

const httpServer = http.createServer((req, res) => {
  res.writeHead(200, {'Content-Type': 'text/html'});
  res.end(htmlPage);
});
httpServer.listen(HTTP_PORT, () => console.log(`HTTP browser page: :${HTTP_PORT}`));

// WebSocket signalling for Unity streamer
const wss = new WebSocket.Server({ port: WS_PORT });
let streamer = null;
const viewers = new Set();

wss.on('connection', (ws, req) => {
  const ua = req.headers['user-agent'] || '';
  const isStreamer = req.url === '/streaming' || ua.includes('Unity') || req.url === '/';

  if (isStreamer && !streamer) {
    streamer = ws;
    console.log('[+] Unity streamer connected');
    ws.on('message', data => {
      const msg = JSON.parse(data);
      console.log('<- streamer:', msg.type);
      viewers.forEach(v => { if (v.readyState === WebSocket.OPEN) v.send(data); });
    });
    ws.on('close', () => { streamer = null; console.log('[-] Unity streamer disconnected'); });
  } else {
    viewers.add(ws);
    console.log(`[+] Browser viewer connected (total: ${viewers.size})`);
    // Tell streamer a new viewer arrived
    if (streamer && streamer.readyState === WebSocket.OPEN)
      streamer.send(JSON.stringify({type:'connect'}));
    ws.on('message', data => {
      const msg = JSON.parse(data);
      console.log('<- viewer:', msg.type);
      if (streamer && streamer.readyState === WebSocket.OPEN) streamer.send(data);
    });
    ws.on('close', () => {
      viewers.delete(ws);
      console.log(`[-] Browser viewer disconnected (total: ${viewers.size})`);
    });
  }
});

console.log(`Unity streamer WS: :${WS_PORT}`);
'''

upload_file(ssh, signalling_server, '/data/signalling/server.js')

# Test it starts
run(ssh, 'pkill -f "signalling/server.js" 2>/dev/null || true; sleep 1')
run(ssh, 'HTTP_PORT=80 WS_PORT=8888 nohup node /data/signalling/server.js >> /data/logs/signalling.log 2>&1 & sleep 2 && echo launched')
run(ssh, 'ps aux | grep "signalling/server.js" | grep -v grep')
run(ssh, 'curl -s http://localhost:80/ | head -3')
run(ssh, 'tail -5 /data/logs/signalling.log')

# Update start_ps.sh
start_sh = '''#!/usr/bin/env bash
set -e
LOG=/data/logs
mkdir -p $LOG

echo "=== Starting HerUnity Pixel Streaming Stack ==="

# 1. Virtual display
pkill -f "Xvfb :99" 2>/dev/null || true
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
sleep 1
echo "[OK] Xvfb :99"

# 2. Signalling server
pkill -f "signalling/server.js" 2>/dev/null || true
HTTP_PORT=80 WS_PORT=8888 nohup node /data/signalling/server.js >> $LOG/signalling.log 2>&1 &
sleep 2
echo "[OK] Signalling server (HTTP:80 WS:8888)"

# 3. Backend health check
curl -s http://localhost:8100/health && echo " [OK] Backend :8100" || echo "[WARN] Backend not running"

# 4. Unity (only if build exists)
BUILD=/data/HerUnity-Build/HerUnity.x86_64
if [ ! -f "$BUILD" ]; then
    echo "[SKIP] Unity build not found: $BUILD"
    echo "  Upload build first: scp -P $CLOUD_SSH_PORT -r <build-dir>/ root@$CLOUD_SSH_HOST:/data/HerUnity-Build/"
    exit 0
fi
pkill -f "HerUnity.x86_64" 2>/dev/null || true
chmod +x "$BUILD"
DISPLAY=:99 "$BUILD" -RenderOffscreen -PixelStreamingURL ws://127.0.0.1:8888 >> $LOG/unity.log 2>&1 &
sleep 3
echo "[OK] Unity started"

echo ""
echo "Browser:  http://<YOUR_SERVER_IP>:80"
echo "Backend:  http://<YOUR_SERVER_IP>:8100/health"
echo "Logs:     $LOG/"
'''

upload_file(ssh, start_sh, '/data/start_ps.sh')
run(ssh, 'chmod +x /data/start_ps.sh')

stop_sh = '''#!/usr/bin/env bash
pkill -f "HerUnity.x86_64"      2>/dev/null && echo "Unity stopped"      || true
pkill -f "signalling/server.js"  2>/dev/null && echo "Signalling stopped"  || true
pkill -f "Xvfb :99"             2>/dev/null && echo "Xvfb stopped"        || true
echo "Done."
'''
upload_file(ssh, stop_sh, '/data/stop_ps.sh')
run(ssh, 'chmod +x /data/stop_ps.sh')

print('\n=== Final cloud state ===')
run(ssh, 'node --version && npm --version')
run(ssh, 'curl -s http://localhost:8100/health')
run(ssh, 'ls /data/')
run(ssh, 'ps aux | grep -E "server.js|uvicorn" | grep -v grep')

ssh.close()
print('\nDONE')
