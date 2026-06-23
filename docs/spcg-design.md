# SPCG 设计摘要

SPCG 是 HerUnity 的行为规划能力：**Semantic-Prosody Coupled Gesture and Expression Planner**，即语义-韵律耦合的表情与手势规划器。

当前 JD Demo 主线只需要使用已有规则能力来驱动可见动作和表情，不需要继续训练模型或追求完整 prosody 评测。本文作为算法设计摘要和面试加分材料保留。

本文只保留当前仍有价值的算法设计。原始 2026-06-13 方案书已归档到 [archive/PROJECT-2026-06-13-original.md](archive/PROJECT-2026-06-13-original.md)。

## 目标

给定用户输入、Agent 回复文本、TTS 时间戳和韵律特征，生成可被 Unity 数字人消费的行为时间轴：

- viseme / blendshape 口型曲线
- emotion expression 表情权重
- gesture 手势事件
- gaze/head motion 凝视和头动事件
- state transition，例如 thinking、speaking、idle

SPCG 的目标不是只“随机播放动作”，而是让手势和表情跟文本重点、语音重音、停顿和情绪一致。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `user_text` | 浏览器/Unity/语音 ASR | 对话上下文 |
| `reply_text` | Agent | 语义锚点提取 |
| `emotion` | Agent 或情绪分类 | 表情和语气控制 |
| `dialogue_act` | Agent | 区分解释、枚举、安慰、提问等行为 |
| `phoneme_intervals` | TTS/alignment | 口型同步 |
| `word_timestamps` | TTS/alignment | 语义锚点对齐到时间轴 |
| `prosody` | TTS 或分析器 | 重音、停顿、能量、语速 |
| `avatar_constraints` | Unity 角色配置 | 动作可用性、冷却、当前状态 |

当前 MVP 多数输入可以来自 MockTTS 和规则 Agent。真实 TTS 接入后，phoneme、word timestamp 和 prosody 指标才具备完整可信度。

## 输出

示例结构：

```json
{
  "turn_id": "turn-001",
  "duration_ms": 3200,
  "emotion": "happy",
  "visemes": [
    { "time_ms": 120, "weights": { "aa": 0.7, "ih": 0.1 } }
  ],
  "expressions": [
    { "time_ms": 0, "name": "happy", "weight": 0.45 },
    { "time_ms": 1800, "name": "smile", "weight": 0.65 }
  ],
  "gestures": [
    { "time_ms": 640, "type": "enumerate", "hand": "right", "strength": 0.8 }
  ],
  "gaze": [
    { "time_ms": 0, "target": "user", "mode": "speaking" }
  ]
}
```

Unity 侧应把这些事件当作时间轴指令，而不是在网络层直接写业务规则。

## 三阶段流程

### 1. 语义锚点提取

从 `reply_text` 中识别值得配动作的内容：

- 枚举：第一、第二、第三、一二三
- 对比：但是、相比、不同的是
- 强调：重点、核心、最重要
- 场景指向：这里、这个、左边、右边
- 情绪表达：开心、担心、想你、抱歉

当前 JD Demo 可用规则、关键词和 LLM 结构化标签。后续可训练轻量 token classifier，但不属于投递版本阻塞项。

### 2. 韵律对齐

将语义锚点对齐到音频时间轴：

- 优先使用词级时间戳。
- 没有词级时间戳时，使用 phoneme chunk 或句子位置做近似。
- 重音、能量峰、停顿后起句适合放置 gesture。
- 口型以 phoneme/viseme 为主，不应被 gesture 调度打断。

当前 MockTTS 下，韵律指标只能作为 proxy；报告必须明确标注不可替代真实 prosody。

### 3. 约束感知动作合成

把候选动作转换为 Unity 可执行事件：

- 避免同一时间多个大动作冲突。
- 控制 gesture cooldown，避免频繁抽动。
- speaking 状态下优先表情、轻手势和凝视。
- thinking 状态下优先 idle 头动、目光偏移、轻微表情。
- 传感器即时反馈应优先于后续 TTS 台词，但不应破坏当前口型播放队列。

## 当前实现边界

- M4 已完成 SPCG-MVP：规则语义锚点、基础 gesture 调度和 Unity 播放链路。
- 当前 JD Demo 重点是手机传感器即时互动和可见反馈，不重新训练 SPCG 模型。
- IndexTTS2 未完成前，口型和 gesture timing 的真实指标仍受 MockTTS 限制。
- 浏览器端传感器和视觉感知属于输入扩展，进入后端后应统一成事件，不直接耦合 Unity 组件。

## 评测

当前评测重点：

- `emotion_consistency`：回复情绪与期望情绪一致性。
- `lip_offset`：口型相对音频时间轴偏移。
- `gesture_timing_error`：手势触发点相对语义/韵律锚点的偏移。
- `gesture_diversity`：动作多样性，避免单一动作反复出现。
- `turn_latency`：用户输入到 `turn.start`、到第一帧可见响应的延迟。

MockTTS 条件下：

- `lip_offset` 和 `gesture_timing_error` 只能作为 proxy。
- 报告不能静默输出 null；应标注计算方式和适用范围。

真实 TTS 条件下：

- 使用真实 phoneme/word timestamp。
- 记录音频时长、时间戳覆盖范围、单调性和 Unity 播放对齐情况。
- 对比 V0 idle、V1 lip-only、V2 SPCG full 三种链路。

## 相关文件

| 文件 | 作用 |
|---|---|
| `backend/app/services/gesture.py` | SPCG-MVP 规则手势服务 |
| `backend/app/services/viseme.py` | phoneme/viseme 映射 |
| `backend/app/services/agent.py` | Agent 回复、emotion、dialogue_act |
| `Assets/Scripts/GestureController.cs` | Unity 手势播放 |
| `Assets/Scripts/ExpressionController.cs` | Unity 表情控制 |
| `Assets/Scripts/StreamingAudioPlayer.cs` | 音频播放和动画时间轴 |
| `scripts/eval/` | V0/V1/V2 评测框架 |
