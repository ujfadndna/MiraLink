<div align="center">



https://github.com/user-attachments/assets/772fe8b6-eac0-4354-b8c0-fe8a2c8f8c6a


# MiraLink

### 实时数字人交互 Demo

[English](README.md) · [中文文档](README.zh.md) · [GitHub](https://github.com/ujfadndna/MiraLink)

![License](https://img.shields.io/badge/License-See%20Repo-blue)
![Unity](https://img.shields.io/badge/Unity-2022.3-black)
![Python](https://img.shields.io/badge/Python-3.11%2B-brightgreen)
![FastAPI](https://img.shields.io/badge/FastAPI-009688)
![WebSocket](https://img.shields.io/badge/WebSocket-realtime-orange)
![WebRTC](https://img.shields.io/badge/WebRTC-RenderStreaming-00AEEF)

<br/>

<a href="https://github.com/ujfadndna/MiraLink">
  <img src="https://img.shields.io/badge/VISIT%20MIRALINK%20REPOSITORY-00AEEF?style=for-the-badge&logo=github&logoColor=white" alt="Visit MiraLink Repository">
</a>

<br/>
<br/>

[效果展示](#效果展示) · [选择运行路线](#选择运行路线) · [快速开始](#快速开始) · [项目结构](#项目结构) · [核心链路](#核心链路) · [协议与接口](#协议与接口) · [测试](#测试) · [Roadmap](#roadmap)

</div>

---

## 项目简介

MiraLink 是一个本地优先的实时数字人 Demo 工程，目标是把“手机端交互、后端 AI 服务、Unity 头像表现”串成一条可以运行、可以演示、可以继续扩展的完整链路。

核心演示路径包括：

- 语音对话：浏览器或通话入口采集语音，后端完成 ASR、LLM/Agent、TTS 和 viseme 口型曲线生成，再推送给 Unity 头像播放语音、口型、表情和动作。
- 手机触控：手机浏览器发送触摸、滑动、传感器等事件，FastAPI 后端转换为反馈或 Agent 规则，再通过 WebSocket 驱动 Unity 头像做出可见响应。
- 本地作品集演示：默认支持本机 FastAPI、静态网页、RenderStreaming signalling 和 Unity Editor Play Mode 组合运行。
- 可替换后端：ASR、TTS、Agent 都通过配置选择 mock、本地或云端实现，适合先跑通烟测，再替换真实模型服务。

Mock 后端可以用于离线开发和烟测，但正式演示链路应保持真实可运行：语音输入需要经过 ASR、Agent、TTS、viseme 和 Unity 播放；手机触控需要经过 `/ws/sensor`、后端反馈和 `/ws/avatar`，最终在 Unity 中呈现动画、表情、UI、音效或特效。

## 效果展示

MiraLink 的主展示场景在 Unity 中运行，手机页面负责输入，后端负责协议和 AI 服务编排。

典型效果：

- 手机触摸头像区域后，Unity 头像做出表情、动作或反馈。
- 语音输入后，头像用 TTS 语音回答，并同步口型曲线。
- 后端可向 Unity 推送 avatar action、音频、viseme、表情、手势和状态消息。
- `frontend/avatar_touch.html` 是正式演示页面，默认保持全屏、干净、无调试控件。
- `frontend/sensor_controller.html` 是调试页面，适合开发时查看传感器和连接状态。

## 选择运行路线

| 路线 | 适合场景 | 需要准备 | 验证重点 |
|---|---|---|---|
| Mock 烟测 | 第一次跑项目、没有外部模型服务 | Python、Node.js、Unity Editor | WebSocket 协议、页面输入、后端转发、Unity 可见反馈 |
| 本地真实语音链路 | 本地演示 ASR/TTS/Agent | ASR/TTS/LLM 配置或本地服务 | 语音输入到头像语音播放和口型同步 |
| 云端模型扩展 | 使用云端 ASR、TTS、Agent 或云端 Unity | API Key、云端服务地址、可选端口转发 | 本地/云端服务之间的 WebSocket 和媒体链路 |
| RenderStreaming 演示 | 手机或浏览器观看 Unity 输出 | signalling 服务、Unity RenderStreaming 配置 | 浏览器端可见 Unity 画面和交互反馈 |

建议第一次先跑 Mock 烟测，确认端口、WebSocket、网页和 Unity 场景都正常，再切换真实 ASR/TTS/Agent。

## 快速开始

以下命令以仓库根目录为 `<repo>`。

### 1. 启动后端

```powershell
cd <repo>\backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8100
```

默认后端端口是 `8100`。配置优先级为：

```text
环境变量 > backend/.env > 代码默认值
```

常用配置：

| 变量 | 说明 |
|---|---|
| `SERVER_PORT` | FastAPI 端口，通常为 `8100` |
| `ASR_BACKEND` | ASR 后端，可选 `mock`、`faster_whisper`、`cloud_whisper` |
| `AGENT_BACKEND` | Agent 后端，可选 `mock`、`langgraph`、`cloud` |
| `TTS_BACKEND` | TTS 后端，可选 `mock`、`indextts`、`cloud` |
| `ANTHROPIC_API_KEY` | 可选 LLM Key |
| `ANTHROPIC_BASE_URL` | 可选兼容端点 |
| `INDEXTTS_API_URL` | 可选 IndexTTS HTTP 服务地址 |

不要提交 `backend/.env`。

### 2. 启动静态页面

```powershell
cd <repo>
python -m http.server 8081 --bind 0.0.0.0
```

手机或浏览器访问：

```text
http://<dev-machine-lan-ip>:8081/frontend/avatar_touch.html
http://<dev-machine-lan-ip>:8081/frontend/sensor_controller.html
```

其中 `avatar_touch.html` 是正式演示页面，`sensor_controller.html` 是调试页面。

### 3. 启动 RenderStreaming signalling

```powershell
cd <repo>
$env:PORT="8080"
$env:BACKEND_WS="ws://127.0.0.1:8100/ws/avatar"
$env:ICE_TRANSPORT_POLICY="all"
python tools/server_v3.py
```

### 4. 启动 Unity 场景

用 Unity Hub 打开仓库根目录 `<repo>`，运行：

```text
assets/Scenes/MainScene.unity
```

注意：Unity 项目根目录就是仓库根目录，不是 `unity/` 子目录。

## 项目结构

```text
<repo>/
  assets/
    Scenes/MainScene.unity
    Scripts/
      NetworkClient.cs
      JdDemoInteractionController.cs
      JdDemoHud.cs
      GazeController.cs
      ExpressionController.cs
      GestureAnimationController.cs
      FacialAnimationController.cs
      StreamingAudioPlayer.cs
  backend/
    app/
      main.py
      config.py
      schemas.py
      routers/
      services/
    requirements.txt
    .env.example
  frontend/
    avatar_touch.html
    sensor_controller.html
    test_avatar_touch.js
  tools/
    server_v3.py
    local_https_gateway.py
    cloud_unity_manager.py
  docs/
    architecture.md
    local-demo.md
    cloud-demo.md
    protocol.md
    testing.md
    roadmap.md
```

不要编辑 Unity 生成目录：`Library/`、`Temp/`、`Logs/`、`UserSettings/`、`Library/PackageCache/`。

## 核心链路

### 语音输入链路

```text
Voice input
  -> ASR
  -> LLM/Agent
  -> TTS + viseme curve
  -> Unity /ws/avatar
  -> avatar audio playback, lip sync, expression, gesture
```

关键文件：

- `backend/app/routers/call_ws.py`
- `backend/app/services/asr.py`
- `backend/app/services/agent.py`
- `backend/app/services/tts.py`
- `backend/app/services/viseme.py`
- `assets/Scripts/StreamingAudioPlayer.cs`
- `assets/Scripts/FacialAnimationController.cs`
- `assets/Scripts/NetworkClient.cs`

### 手机触控链路

```text
Touch / phone controller
  -> WebSocket sensor event
  -> FastAPI backend
  -> sensor feedback or Agent rule
  -> Unity /ws/avatar
  -> visible avatar animation, expression, UI, SFX, or VFX
```

关键文件：

- `frontend/avatar_touch.html`
- `frontend/sensor_controller.html`
- `backend/app/main.py`
- `backend/app/schemas.py`
- `assets/Scripts/NetworkClient.cs`
- `assets/Scripts/JdDemoInteractionController.cs`

## 协议与接口

主要 WebSocket：

| 路径 | 用途 |
|---|---|
| `/ws/sensor` | 手机触控和传感器事件入口 |
| `/ws/avatar` | 后端向 Unity 推送头像动作、表情、音频、口型和状态 |
| `/ws/call` | 语音通话链路入口 |

新增 WebSocket 消息时，需要同步更新：

- `backend/app/schemas.py`
- `docs/protocol.md`

## 测试

后端测试：

```powershell
cd <repo>\backend
python -m pytest -v
python -m compileall -q app
```

常用聚焦测试：

```powershell
cd <repo>\backend
python -m pytest test_jd_sensor_feedback.py -q
python -m pytest test_call_ws_protocol.py -q
python -m pytest test_avatar_intent.py test_avatar_action_ws.py -q
```

前端触控模拟：

```powershell
cd <repo>
node frontend/test_avatar_touch.js
```

Unity 相关改动需要在 Unity Editor Play Mode 中验证，并记录测试的 Unity 版本、场景和交互路径。

## 云端扩展

云端 Unity 或 WebRTC 是可选能力。相关配置应通过环境变量传入，不要把真实主机、SSH 端口、密码、TURN 凭据或 API Key 写入文档、脚本、`.env.example` 或提交记录。

示例：

```powershell
cd <repo>
$env:SEETA_SSH_HOST="<cloud-ssh-host>"
$env:SEETA_SSH_PORT="<cloud-ssh-port>"
$env:SEETA_SSH_USER="<cloud-user>"
$env:SEETA_SSH_PASSWORD="<set-only-in-current-shell>"
python tools/cloud_unity_manager.py
```

如果云端 Unity 需要反连本地后端，文档默认约定 `CloudBackendPort=18100`，用于避免和云端机器已有后端端口冲突。

TURN 参数应使用占位符或运行时环境变量：

```powershell
cd <repo>
python tools/server_v3.py -IceTransportPolicy relay -TurnPublicIp "<turn-public-ip>"
```

## Roadmap

当前重点：

- 保持语音输入到 Unity 头像播放的真实链路稳定可运行。
- 完善手机触控到 Unity 可见反馈的正式演示体验。
- 提升 ASR、TTS、Agent 后端的可插拔配置和错误提示。
- 打磨 Unity 头像表情、手势、凝视、口型和音频播放的一致性。
- 补齐本地演示、云端扩展、协议和验收文档。

待优化项：

- 降低首字耗时，让语音回复更快开始。
- 优化动画事件触发，提升动作与语音、表情的同步感。
- 完善 Agent 工具外部接入，支持更多真实业务能力。
- 调整触屏互动灵敏度，让手机操作更稳定、更自然。

更多计划见 `docs/roadmap.md` 和 `docs/jd-demo-plan.md`。

## 文档

- 总体路线：`docs/roadmap.md`
- 验收说明：`docs/jd-demo-plan.md`
- 架构说明：`docs/architecture.md`
- 本地启动：`docs/local-demo.md`
- 云端扩展：`docs/cloud-demo.md`
- 协议细节：`docs/protocol.md`
- 测试命令：`docs/testing.md`

## 致谢

本项目使用或集成了以下方向的技术生态：

- FastAPI 和 Python WebSocket 服务
- Unity、VRM、RenderStreaming
- ASR、LLM/Agent、TTS 和 viseme 口型生成
- 浏览器传感器、手机触控和本地网络调试工具

## 许可

请以仓库中的许可证文件为准。
