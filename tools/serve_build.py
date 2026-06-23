import http.server, threading, os, time, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAR_FILE = str(ROOT / "tools" / "build.tar.gz")
BUILD_DIR = os.environ.get("HERUNITY_BUILD_DIR", str(ROOT.parent / "HerUnity-LinuxBuild"))
HTTP_PORT = 8765

# Check tar exists
if not os.path.exists(TAR_FILE):
    print('Packing...')
    subprocess.run(['tar', 'czf', TAR_FILE, '-C', BUILD_DIR, '.'], check=True)
    print(f'Packed: {os.path.getsize(TAR_FILE)//1024//1024}MB')
else:
    print(f'Tar exists: {os.path.getsize(TAR_FILE)//1024//1024}MB')

# Start HTTP server serving the tar file directory
os.chdir(os.path.dirname(TAR_FILE))
handler = http.server.SimpleHTTPRequestHandler
httpd = http.server.HTTPServer(('0.0.0.0', HTTP_PORT), handler)
print(f'HTTP server on :{HTTP_PORT}')
t = threading.Thread(target=httpd.serve_forever)
t.daemon = True
t.start()
print('Ready. Run on cloud:')
print(f'  curl http://<YOUR_LOCAL_IP>:{HTTP_PORT}/build.tar.gz -o /data/build.tar.gz')
print('Waiting 10 minutes...')
time.sleep(600)
httpd.shutdown()
