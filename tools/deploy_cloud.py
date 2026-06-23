import os
import paramiko, time

# SSH credentials are read from environment variables.
# Set CLOUD_SSH_HOST, CLOUD_SSH_PORT, CLOUD_SSH_USER, CLOUD_SSH_PASSWORD before running.
HOST = os.environ["CLOUD_SSH_HOST"]
PORT = int(os.environ.get("CLOUD_SSH_PORT", "22"))
USER = os.environ.get("CLOUD_SSH_USER", "root")
PW   = os.environ["CLOUD_SSH_PASSWORD"]

def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PW, timeout=20)
    return ssh

def run(ssh, cmd, timeout=30):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode().strip()
    err = e.read().decode().strip()
    result = out or err or '(empty)'
    print(f'$ {cmd[:90]}\n  {result[:300]}')
    return out

def upload(ssh, content, remote_path):
    sftp = ssh.open_sftp()
    with sftp.open(remote_path, 'w') as f:
        f.write(content)
    sftp.close()
    print(f'  [uploaded] {remote_path}')

def wait_done(ssh, donefile, logfile, label, max_sec=360):
    for i in range(max_sec // 10):
        time.sleep(10)
        out = run(ssh, f'cat {donefile} 2>/dev/null || echo pending')
        if out == '0':
            print(f'  [OK] {label} (~{(i+1)*10}s)')
            return True
        elif out not in ('pending', ''):
            run(ssh, f'tail -10 {logfile}')
            return False
        tail = run(ssh, f'tail -1 {logfile} 2>/dev/null || echo ...')
        print(f'  [{(i+1)*10}s] {label}: {tail}')
    print(f'  [TIMEOUT] {label}')
    return False

ssh = connect()

# Step 1: Install nvm + Node in background
print('=== [1/5] Installing Node.js (background) ===')
nvm_script = r"""
export NVM_DIR="$HOME/.nvm"
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm install --lts
NODE_BIN=$(ls -d ~/.nvm/versions/node/*/bin/node 2>/dev/null | tail -1)
[ -n "$NODE_BIN" ] && ln -sf "$NODE_BIN" /usr/local/bin/node && ln -sf "$(dirname $NODE_BIN)/npm" /usr/local/bin/npm
node --version
"""
run(ssh, 'rm -f /data/logs/nvm.done /data/logs/nvm.log')
upload(ssh, nvm_script, '/tmp/install_nvm.sh')
run(ssh, 'nohup bash -c "bash /tmp/install_nvm.sh >> /data/logs/nvm.log 2>&1; echo $? > /data/logs/nvm.done" </dev/null >/dev/null 2>&1 &', timeout=5)
wait_done(ssh, '/data/logs/nvm.done', '/data/logs/nvm.log', 'nvm+node install', max_sec=360)
run(ssh, 'node --version && npm --version')

# Step 2: npm install ws (already have /data/signalling from old server)
print('\n=== [2/5] npm install ws ===')
run(ssh, 'ls /data/signalling/', timeout=10)
has_ws = run(ssh, 'ls /data/signalling/node_modules/ws 2>/dev/null || echo MISSING')
if 'MISSING' in has_ws:
    run(ssh, 'cd /data/signalling && npm install ws 2>&1 | tail -3', timeout=60)
else:
    print('  ws already installed')

# Step 3: Verify/re-upload signalling server
print('\n=== [3/5] Signalling server ===')
run(ssh, 'ls /data/signalling/server.js 2>/dev/null && echo exists || echo missing')
# Start it
run(ssh, 'pkill -f "signalling/server.js" 2>/dev/null || true; sleep 1')
run(ssh, 'HTTP_PORT=80 WS_PORT=8888 nohup node /data/signalling/server.js >> /data/logs/signalling.log 2>&1 & sleep 3 && echo launched')
run(ssh, 'curl -s http://localhost:80/ | head -1')
run(ssh, 'tail -3 /data/logs/signalling.log')

# Step 4: Backend
print('\n=== [4/5] Backend ===')
be = run(ssh, 'curl -s http://localhost:8100/health 2>/dev/null || echo not-running')
if 'ok' not in be:
    print('  Starting backend...')
    run(ssh, '''cd /data/backend && source venv/bin/activate 2>/dev/null; \
TTS_BACKEND=mock AGENT_BACKEND=mock ASR_BACKEND=mock \
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8100 \
>> /data/logs/backend.log 2>&1 &''')
    time.sleep(5)
    run(ssh, 'curl -s http://localhost:8100/health')
else:
    print(f'  Backend healthy: {be}')

# Step 5: Summary
print('\n=== [5/5] Summary ===')
run(ssh, 'node --version && npm --version')
run(ssh, 'curl -s http://localhost:8100/health')
run(ssh, 'ps aux | grep -E "server.js|uvicorn" | grep -v grep')
run(ssh, 'ls /data/MiraLink-Build/ 2>/dev/null || echo "(empty — upload Unity build here)"')

public_ip = run(ssh, 'curl -s ifconfig.me 2>/dev/null || hostname -I | awk "{print $1}"')

ssh.close()
print(f'''
=== DONE ===
Signalling:  http://{public_ip}:80
Backend:     http://{public_ip}:8100/health

Next steps:
  1. Unity Editor → File → Build Settings → Linux x86_64 → Build
  2. scp -P {PORT} -r <build-dir>/ root@{HOST}:/data/MiraLink-Build/
  3. ssh -p {PORT} root@{HOST} "bash /data/start_ps.sh"
''')
