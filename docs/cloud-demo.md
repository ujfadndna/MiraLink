# Cloud Demo

Cloud Unity/WebRTC is an optional extension. The local demo remains the default portfolio path.

## Topology

```text
Phone browser
  -> https://<demo-host>:8443/frontend/avatar_touch.html
  -> wss://<demo-host>:8443/?role=viewer&replace=1
  -> local or hosted HTTPS/WSS gateway
  -> signalling tunnel
  -> cloud Unity RenderStreaming streamer

Phone touch or voice
  -> wss://<demo-host>:8443/ws/sensor or /ws/call
  -> FastAPI backend
  -> reverse tunnel or direct backend route
  -> cloud Unity /ws/avatar
```

Use this only when explicitly validating remote streaming. It requires a reachable TURN server when browser and Unity cannot connect directly.

## Environment Template

Set cloud SSH values only in the current shell/session:

```powershell
$env:SEETA_SSH_HOST="<cloud-ssh-host>"
$env:SEETA_SSH_PORT="<cloud-ssh-port>"
$env:SEETA_SSH_USER="<cloud-user>"
$env:SEETA_SSH_PASSWORD="<cloud-ssh-password>"
```

Do not write real SSH passwords, TURN credentials, public IPs, or private hostnames to committed files.

## Cloud Start Template

```powershell
cd <repo>
.\scripts\start_cloud_unity_demo.ps1 `
  -SshHost $env:SEETA_SSH_HOST `
  -SshPort $env:SEETA_SSH_PORT `
  -SshUser $env:SEETA_SSH_USER `
  -SshPassword $env:SEETA_SSH_PASSWORD `
  -RemoteRoot "<remote-root>" `
  -CloudBackendPort 18100 `
  -VideoProfile phone_stable `
  -DisplayServer nvidia-xorg `
  -IceTransportPolicy relay `
  -TurnPublicIp "<turn-public-ip>" `
  -UploadBuild
```

`CloudBackendPort=18100` is used as a generic conflict-avoidance convention for reverse tunnels. Confirm actual ports in your environment before changing it.

## TURN Rules

- `-TurnPublicIp` must be reachable from the phone/browser.
- Do not use `127.0.0.1`, `localhost`, private LAN addresses, or cloud-only internal IPs as TURN public addresses.
- In `relay` mode, provide valid TURN URL, username, and credential at runtime.
- Use `ICE_TRANSPORT_POLICY=all` only for local debugging or when direct connectivity is intentionally being tested.

## Health Checks

Local gateway:

```powershell
Invoke-RestMethod https://127.0.0.1:8443/health -SkipCertificateCheck
```

Signalling:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

Backend:

```powershell
Invoke-RestMethod http://127.0.0.1:8100/health
```

## Common Failure Modes

- Signalling connects but video remains black: TURN address or credential may be wrong.
- Phone page shows WebSocket `1006`: HTTPS page may be attempting to connect to a non-WSS backend or signalling port.
- Unity receives no avatar events: backend session may differ from the session bound by the phone page.
- Multiple viewer pages may fight for the stream; use `replace=1` and close stale tabs.

