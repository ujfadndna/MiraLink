"""Restart all cloud services with v2 signalling server"""
import paramiko, time, sys

import os
HOST = os.environ["CLOUD_SSH_HOST"]
PORT = int(os.environ.get("CLOUD_SSH_PORT", "22"))
USER = os.environ.get("CLOUD_SSH_USER", "root")
PASS = os.environ["CLOUD_SSH_PASSWORD"]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASS, timeout=30, look_for_keys=False, allow_agent=False)

def run(cmd, timeout=20):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    # For nohup/background commands, close stdin to avoid blocking
    stdin.close()
    try:
        out = stdout.read().decode('utf-8', errors='replace')
    except:
        out = ""
    return out

def run_bg(cmd):
    """Run a background command without reading output"""
    transport = client.get_transport()
    channel = transport.open_session()
    channel.exec_command(cmd)
    # Don't wait - just close
    channel.close()

# 1. Verify v2 server is in place
print("1. Verifying v2 server source...")
out = run('grep -c polite /data/signalling/server.py')
print(f"   polite count: {out.strip()}")
out = run('grep -c welcome /data/signalling/server.py')
print(f"   welcome count: {out.strip()}")

# 2. Kill all
print("2. Killing all services...")
run('pkill -9 -f "server.py" 2>/dev/null; pkill -9 -f HerUnity.x86_64 2>/dev/null; pkill -9 -f uvicorn 2>/dev/null', timeout=5)
time.sleep(3)
out = run('ps aux | grep -E "server.py|HerUnity|uvicorn" | grep -v grep || echo "all dead"')
print(f"   {out.strip()[:100]}")

# 3. Clear logs
run('> /tmp/v17.log; > /data/logs/sig.log')

# 4. Check Xvfb
out = run('test -S /tmp/.X11-unix/X99 && echo OK || echo MISSING')
if 'MISSING' in out:
    run_bg('Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX &')
    time.sleep(2)
    out = run('test -S /tmp/.X11-unix/X99 && echo OK || echo FAIL')
print(f"3. Xvfb: {out.strip()}")

# 5. Start Backend
print("4. Starting Backend...")
run_bg('cd /data/backend && nohup /data/miniconda/envs/torch/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8100 </dev/null >>/data/logs/backend.log 2>&1 &')
time.sleep(5)
out = run('curl -s --max-time 5 http://127.0.0.1:8100/health 2>/dev/null || echo "waiting..."')
print(f"   {out.strip()}")

# 6. Start Signalling v2
print("5. Starting Signalling v2...")
run_bg('cd /data/signalling && nohup /data/miniconda/envs/torch/bin/python3 -u server.py >>/data/logs/sig.log 2>&1 &')
time.sleep(3)
out = run('curl -s --max-time 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:80/ 2>/dev/null')
print(f"   HTTP: {out.strip()}")
out = run('tail -3 /data/logs/sig.log')
print(f"   log: {out.strip()}")

# 7. Start Unity
print("6. Starting Unity...")
run_bg('cd /data/HerUnity-Build && DISPLAY=:99 XDG_RUNTIME_DIR=/tmp LD_LIBRARY_PATH=/data/HerUnity-Build:/data/nvidia_libs VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json nohup ./HerUnity.x86_64 -batchmode -RenderOffscreen -logfile /tmp/v17.log </dev/null >>/tmp/v17s.log 2>&1 &')
time.sleep(12)
out = run('pgrep -f HerUnity.x86_64 && echo "RUNNING" || echo "DEAD"')
print(f"   Unity: {out.strip()}")

# 8. Check Unity log for RenderStreaming
print("7. Unity RenderStreaming log:")
time.sleep(3)
out = run('grep -i "signaling\|offer\|connect\|peer\|Receiving\|Sending" /tmp/v17.log 2>/dev/null | head -15')
print(f"   {out[:500] if out else '(no matches yet)'}")

client.close()
print("\nDone.")
