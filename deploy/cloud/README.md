# HerUnity 云端部署指南

本文档用于 HerUnity 云端 WebRTC 扩展部署。云端部署不是本地 JD Demo 的必要条件；本地演示优先参考 [`docs/deployment.md`](../../docs/deployment.md)。

## 服务器要求

- Linux x86_64 服务器，建议 Ubuntu 20.04/22.04 或兼容发行版。
- NVIDIA GPU，已安装可用的 NVIDIA Driver、CUDA/Vulkan 运行依赖，并可通过 `nvidia-smi` 检查。
- Unity Linux Player 构建产物，例如 `/opt/herunity/build/HerUnity.x86_64`。
- Python 3.10+ 或 Conda 环境，用于 FastAPI backend 与 Python signalling server。
- Xvfb，用于给 Unity Linux Player 提供虚拟显示 `:99`。
- systemd，用于长期运行 signalling、backend、unity 服务。
- 可访问的 HTTPS/WSS 入口、反向代理或云平台 ingress。公网 WebRTC 推荐配置 TURN relay。

## 目录约定

以下路径是模板占位值，可按服务器实际情况调整：

```bash
/opt/herunity/
  backend/
  signalling/
  build/
  logs/
  deploy.env
```

推荐将仓库中的文件放置为：

- `backend/` 上传到 `/opt/herunity/backend/`
- `tools/server_v3.py` 上传为 `/opt/herunity/signalling/server.py`
- Unity Linux Player 上传到 `/opt/herunity/build/`
- 本目录下的 systemd 文件复制到 `/etc/systemd/system/`
- `deploy/.env.example` 复制到 `/opt/herunity/deploy.env` 后填入真实变量

## 配置环境变量

先复制模板：

```bash
cp /opt/herunity/deploy/.env.example /opt/herunity/deploy.env
chmod 600 /opt/herunity/deploy.env
```

至少需要检查这些值：

```bash
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic

TURN_URLS=turn:your-turn-server:3478?transport=udp,turn:your-turn-server:3478?transport=tcp
TURN_USERNAME=herunity
TURN_CREDENTIAL=<turn-credential>

PORT=8080
BACKEND_WS=ws://127.0.0.1:8100/ws/avatar
ICE_TRANSPORT_POLICY=all
```

生产环境如使用外部 TURN relay，可将 `ICE_TRANSPORT_POLICY` 调整为 `relay`；局域网或无 TURN 环境建议保持 `all`。

## 部署步骤

### 1. 安装依赖

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip xvfb curl unzip rsync
nvidia-smi
```

如果使用 Conda，请将 systemd 模板中的 Python 路径改成实际路径，例如：

```text
/data/miniconda/envs/torch/bin/python3
```

### 2. 上传代码和构建产物

示例：

```bash
sudo mkdir -p /opt/herunity/{backend,signalling,build,logs}
sudo chown -R "$USER":"$USER" /opt/herunity

rsync -av backend/ user@your-cloud-server:/opt/herunity/backend/
rsync -av tools/server_v3.py user@your-cloud-server:/opt/herunity/signalling/server.py
rsync -av path/to/HerUnity-Linux-Build/ user@your-cloud-server:/opt/herunity/build/
rsync -av deploy/.env.example user@your-cloud-server:/opt/herunity/deploy.env
```

Unity 构建脚本可参考仓库内：

- [`scripts/build_cloud_unity_linux.ps1`](../../scripts/build_cloud_unity_linux.ps1)
- [`assets/Scripts/Editor/BuildScript.cs`](../../assets/Scripts/Editor/BuildScript.cs)
- [`assets/Scripts/Editor/BuildOpenGLCoreScript.cs`](../../assets/Scripts/Editor/BuildOpenGLCoreScript.cs)

云端辅助部署脚本可参考：

- [`tools/deploy_cloud.py`](../../tools/deploy_cloud.py)
- [`scripts/deploy_cloud_stage2.sh`](../../scripts/deploy_cloud_stage2.sh)
- [`tools/ssh_restart.py`](../../tools/ssh_restart.py)

### 3. 安装 Python 依赖

```bash
cd /opt/herunity/backend
python3 -m venv /opt/herunity/.venv
/opt/herunity/.venv/bin/pip install -U pip
/opt/herunity/.venv/bin/pip install -r requirements.txt
```

`tools/server_v3.py` 使用 Python HTTP/WebSocket signalling。若服务器缺少依赖，请按启动报错补装到同一个 venv 中。

### 4. 安装 systemd 服务

```bash
sudo cp deploy/cloud/signalling.service /etc/systemd/system/herunity-signalling.service
sudo cp deploy/cloud/backend.service /etc/systemd/system/herunity-backend.service
sudo cp deploy/cloud/unity.service /etc/systemd/system/herunity-unity.service
sudo systemctl daemon-reload
```

如果实际路径不是 `/opt/herunity/`，先编辑三个 service 文件中的 `WorkingDirectory`、`ExecStart`、`EnvironmentFile` 和 Unity 构建路径。

### 5. 启动服务

```bash
sudo systemctl enable --now herunity-backend.service
sudo systemctl enable --now herunity-signalling.service
sudo systemctl enable --now herunity-unity.service
```

也可以使用一键脚本：

```bash
sudo bash deploy/cloud/setup.sh
```

### 6. 检查状态

```bash
systemctl status herunity-backend.service --no-pager
systemctl status herunity-signalling.service --no-pager
systemctl status herunity-unity.service --no-pager

curl -sS http://127.0.0.1:8100/health
curl -sS http://127.0.0.1:8080/health

tail -120 /opt/herunity/logs/backend.log
tail -120 /opt/herunity/logs/signalling.log
tail -120 /opt/herunity/logs/unity.log
```

## 当前命令来源

这些模板基于 [`docs/deployment.md`](../../docs/deployment.md) 中的云端启动参考整理：

- Signalling：`tools/server_v3.py`，对应文档中的 Python signalling server。
- Backend：`backend/` 下 `uvicorn app.main:app --host 0.0.0.0 --port 8100`。
- Unity：`DISPLAY=:99`、`XDG_RUNTIME_DIR=/tmp`、`LD_LIBRARY_PATH`、`VK_ICD_FILENAMES`、`-batchmode -RenderOffscreen`。

不要将真实 TURN 凭据、SSH 密码或 API key 提交到 git。
