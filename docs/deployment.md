# Deployment Notes

The default MiraLink demo is local. See [local-demo.md](local-demo.md).

Cloud deployment is optional and documented as a template in [cloud-demo.md](cloud-demo.md). Do not publish real infrastructure details in this repository.

## Local Demo

Backend:

```powershell
cd <repo>\backend
uvicorn app.main:app --host 0.0.0.0 --port 8100
```

Signalling:

```powershell
cd <repo>
$env:PORT="8080"
$env:BACKEND_WS="ws://127.0.0.1:8100/ws/avatar"
$env:ICE_TRANSPORT_POLICY="all"
python tools/server_v3.py
```

Static files:

```powershell
cd <repo>
python -m http.server 8081 --bind 0.0.0.0
```

Unity:

```text
Open <repo> in Unity Hub and run assets/Scenes/MainScene.unity.
```

Phone:

```text
http://<dev-machine-lan-ip>:8081/frontend/avatar_touch.html
http://<dev-machine-lan-ip>:8081/frontend/sensor_controller.html
```

## Cloud Template

Set values at runtime:

```powershell
$env:SEETA_SSH_HOST="<cloud-ssh-host>"
$env:SEETA_SSH_PORT="<cloud-ssh-port>"
$env:SEETA_SSH_USER="<cloud-user>"
$env:SEETA_SSH_PASSWORD="<cloud-ssh-password>"
```

Start with a template command:

```powershell
cd <repo>
.\scripts\start_cloud_unity_demo.ps1 `
  -SshHost $env:SEETA_SSH_HOST `
  -SshPort $env:SEETA_SSH_PORT `
  -SshUser $env:SEETA_SSH_USER `
  -SshPassword $env:SEETA_SSH_PASSWORD `
  -RemoteRoot "<remote-root>" `
  -CloudBackendPort 18100 `
  -IceTransportPolicy relay `
  -TurnPublicIp "<turn-public-ip>"
```

The cloud path requires reachable TURN configuration when direct browser-to-Unity connectivity is unavailable.

## Hygiene

Do not commit:

- `.env`
- SSH passwords
- TURN credentials
- private hostnames or server IPs
- screenshots or diagnostics containing infrastructure values
- local Unity generated folders
