"""Restart cloud with v19 + updated server_v2"""
import paramiko, time

import os
HOST = os.environ["CLOUD_SSH_HOST"]
PORT = int(os.environ.get("CLOUD_SSH_PORT", "22")); USER = os.environ.get("CLOUD_SSH_USER", "root"); PASS = os.environ["CLOUD_SSH_PASSWORD"]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=30, look_for_keys=False, allow_agent=False)

def run(cmd, to=15):
    s = c.exec_command(cmd, timeout=to)
    s[1].channel.settimeout(to-5)
    try: return s[1].read().decode('utf-8', errors='replace')
    except: return ''

# 1. Kill all
print("1. Killing...")
run('pkill -9 -f HerUnity 2>/dev/null; pkill -9 -f server.py 2>/dev/null', to=5)
time.sleep(3)
out = run('pgrep -f "HerUnity|server.py" | wc -l')
print(f"   remaining: {out.strip()}")

# 2. Update server.py to v2
print("2. Updating server.py...")
run('cp /data/signalling/server_v2.py /data/signalling/server.py')
out = run('grep -c "unityId" /data/signalling/server.py')
print(f"   has unityId fix: {out.strip()}")

# 3. Clear logs
run('> /data/logs/sig.log; rm -f /tmp/v19.log')

# 4. Start signalling
print("3. Starting signalling...")
run('cd /data/signalling && nohup /data/miniconda/envs/torch/bin/python3 -u server.py >>/data/logs/sig.log 2>&1 &', to=5)
time.sleep(2)
out = run('curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:80/')
print(f"   HTTP: {out.strip()}")

# 5. Start Unity v19
print("4. Starting Unity v19...")
run('cd /data/HerUnity-Build-v19 && DISPLAY=:99 XDG_RUNTIME_DIR=/tmp LD_LIBRARY_PATH=/data/HerUnity-Build-v19:/data/nvidia_libs VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json nohup ./HerUnity.x86_64 -batchmode -RenderOffscreen -logfile /tmp/v19.log >/tmp/v19s.log 2>&1 &', to=5)
time.sleep(20)
out = run('pgrep -fc HerUnity.x86_64')
print(f"   Unity processes: {out.strip()}")
out = run('grep -c "SIGSEGV\|Caught fatal" /tmp/v19.log')
print(f"   Crashes: {out.strip()}")
out = run('grep "Signaling.*connected\|NetworkClient" /tmp/v19.log')
print(f"   Init: {out.strip()[:300]}")

# 6. Test viewer
print("5. Running viewer test...")
out = run('/data/miniconda/envs/torch/bin/python3 /tmp/test_viewer.py', to=30)
print(out[:800] if out.strip() else "(no output)")

time.sleep(2)
out = run('grep -E "Receiving|Sending" /tmp/v19.log | tail -5')
print(f"   Unity RS: {out.strip()[:400]}")
out = run('tail -8 /data/logs/sig.log')
print(f"   Sig: {out.strip()[:400]}")

c.close()
print("\nDone.")
