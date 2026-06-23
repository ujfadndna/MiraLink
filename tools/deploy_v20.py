"""Package v20 -> upload -> restart -> test"""
import paramiko, time, os, subprocess

import os
HOST = os.environ["CLOUD_SSH_HOST"]
PORT = int(os.environ.get("CLOUD_SSH_PORT", "22")); USER = os.environ.get("CLOUD_SSH_USER", "root"); PASS = os.environ["CLOUD_SSH_PASSWORD"]
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

# 1. Package v20
print("1. Packaging v20...")
tgz = os.path.join(ROOT, 'build_v20.tar.gz')
if os.path.exists(tgz): os.remove(tgz)
subprocess.run(['tar', '-czf', tgz, '-C', os.path.join(ROOT, 'build_v20'), '.'], check=True)
size_mb = os.path.getsize(tgz) / (1024*1024)
print(f"   Created: {size_mb:.1f} MB")

# 2. Connect
print("2. Connecting...")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=60, look_for_keys=False, allow_agent=False)

def run(cmd, to=15):
    s = c.exec_command(cmd, timeout=to)
    s[1].channel.settimeout(to-3)
    try: return s[1].read().decode('utf-8', errors='replace')
    except: return ''

# 3. Kill all
print("3. Killing all services...")
run('pkill -9 -f HerUnity 2>/dev/null; pkill -9 -f server.py 2>/dev/null', to=5)
time.sleep(3)

# 4. Upload
print("4. Uploading v20...")
sftp = c.open_sftp()
sftp.put(tgz, '/data/build_v20.tar.gz')
sftp.put(os.path.join(BASE, 'server_v2.py'), '/data/signalling/server_v2.py')
sftp.close()
print("   Upload done")

# 5. Extract
print("5. Extracting v20...")
out = run('cd /data && rm -rf HerUnity-Build-v20 && mkdir HerUnity-Build-v20 && tar -xzf build_v20.tar.gz -C HerUnity-Build-v20 && chmod +x HerUnity-Build-v20/HerUnity.x86_64 && echo OK')
print(f"   {out.strip()}")

# 6. Update server
run('cp /data/signalling/server_v2.py /data/signalling/server.py')

# 7. Start services
print("6. Starting signalling...")
run('> /data/logs/sig.log; cd /data/signalling && nohup /data/miniconda/envs/torch/bin/python3 -u server.py >>/data/logs/sig.log 2>&1 &', to=5)
time.sleep(2)
out = run('curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:80/')
print(f"   HTTP: {out.strip()}")

print("7. Starting Unity v20...")
run('rm -f /tmp/v20.log; cd /data/HerUnity-Build-v20 && DISPLAY=:99 XDG_RUNTIME_DIR=/tmp LD_LIBRARY_PATH=/data/HerUnity-Build-v20:/data/nvidia_libs VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json nohup ./HerUnity.x86_64 -batchmode -RenderOffscreen -logfile /tmp/v20.log >/tmp/v20s.log 2>&1 &', to=5)
time.sleep(20)

out = run('pgrep -fc HerUnity.x86_64')
print(f"   Procs: {out.strip()}")
out = run('grep -c "SIGSEGV\|Caught fatal" /tmp/v20.log 2>/dev/null')
print(f"   Crashes: {out.strip()}")
out = run('grep "Signaling.*connected\|NetworkClient.*Connected" /tmp/v20.log 2>/dev/null')
print(f"   Init: {out.strip()[:300]}")

# 8. Test viewer
print("8. Testing viewer...")
# Upload updated test script
sftp = c.open_sftp()
sftp.put(os.path.join(BASE, 'test_viewer.py'), '/tmp/test_viewer.py')
sftp.close()
time.sleep(5)
out = run('/data/miniconda/envs/torch/bin/python3 /tmp/test_viewer.py', to=45)
print(out[:1000] if out.strip() else "(no output)")

time.sleep(2)
out = run('grep -E "Receiving|Sending" /tmp/v20.log | tail -10')
print(f"   Unity RS: {out.strip()[:500]}")
out = run('tail -5 /data/logs/sig.log')
print(f"   Sig: {out.strip()[:400]}")

c.close()
print(f"\nDone! Open https://{os.environ.get('CLOUD_PAGE_HOST', 'your-server')} to test.")
