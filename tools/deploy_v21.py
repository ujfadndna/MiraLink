"""Package v21 -> upload -> restart -> test"""
import paramiko, time, os, subprocess

import os
HOST = os.environ["CLOUD_SSH_HOST"]; PORT = int(os.environ.get("CLOUD_SSH_PORT", "22"))
USER = os.environ.get("CLOUD_SSH_USER", "root"); PASS = os.environ["CLOUD_SSH_PASSWORD"]
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

print("1. Packaging v21...")
tgz = os.path.join(ROOT, 'build_v21.tar.gz')
if os.path.exists(tgz): os.remove(tgz)
subprocess.run(['tar', '-czf', tgz, '-C', os.path.join(ROOT, 'build_v21'), '.'], check=True)
print(f"   {os.path.getsize(tgz)/(1024*1024):.1f} MB")

print("2. Connecting...")
c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=60, look_for_keys=False, allow_agent=False)

def run(cmd, to=15):
    s = c.exec_command(cmd, timeout=to); s[1].channel.settimeout(to-3)
    try: return s[1].read().decode('utf-8', errors='replace')
    except: return ''

print("3. Killing...")
run('pkill -9 -f HerUnity 2>/dev/null; pkill -9 -f server.py 2>/dev/null', to=5); time.sleep(3)

print("4. Uploading...")
sftp = c.open_sftp(); sftp.put(tgz, '/data/build_v21.tar.gz'); sftp.close()
print("   done")

print("5. Extracting...")
out = run('cd /data && rm -rf HerUnity-Build-v21 && mkdir HerUnity-Build-v21 && tar -xzf build_v21.tar.gz -C HerUnity-Build-v21 && chmod +x HerUnity-Build-v21/HerUnity.x86_64 && echo OK')
print(f"   {out.strip()}")

print("6. Starting signalling...")
run('> /data/logs/sig.log; cd /data/signalling && nohup /data/miniconda/envs/torch/bin/python3 -u server.py >>/data/logs/sig.log 2>&1 &', to=5)
time.sleep(2)
out = run('curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:80/')
print(f"   HTTP {out.strip()}")

print("7. Starting Unity v21...")
run('rm -f /tmp/v21.log; cd /data/HerUnity-Build-v21 && DISPLAY=:99 XDG_RUNTIME_DIR=/tmp LD_LIBRARY_PATH=/data/HerUnity-Build-v21:/data/nvidia_libs VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json nohup ./HerUnity.x86_64 -batchmode -RenderOffscreen -logfile /tmp/v21.log >/tmp/v21s.log 2>&1 &', to=5)
time.sleep(20)
out = run('grep "Signaling.*connected" /tmp/v21.log')
print(f"   Unity: {out.strip()[:200]}")
out = run('grep -c "SIGSEGV" /tmp/v21.log')
print(f"   Crashes: {out.strip()}")

print("8. Testing viewer...")
sftp = c.open_sftp(); sftp.put(os.path.join(BASE, 'test_viewer.py'), '/tmp/test_viewer.py'); sftp.close()
time.sleep(3)
out = run('/data/miniconda/envs/torch/bin/python3 /tmp/test_viewer.py', to=45)
print(out[:1000] if out.strip() else "(no output)")

time.sleep(2)
out = run('grep -E "Receiving|Sending" /tmp/v21.log | tail -10')
print(f"   RS msgs: {out.strip()[:500]}")
out = run('tail -5 /data/logs/sig.log')
print(f"   Sig: {out.strip()[:300]}")

c.close()
print(f"\nDone! Test: https://{os.environ.get('CLOUD_PAGE_HOST', 'your-server')}")
