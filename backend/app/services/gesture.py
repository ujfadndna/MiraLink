"""语义锚点提取 + 手势调度服务。

M4 MVP 使用规则匹配提取语义锚点，生成 gesture_events 列表。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import AudioWithTimestamps, GestureEvent


# ── 语义锚点规则表 ─────────────────────────────────────────
# (pattern, anchor_type, priority)
# priority 越高越优先触发手势

_ANCHOR_RULES: list[tuple[str, str, float]] = [
    # 枚举
    (r"第一|首先|第二|其次|第三|再者|最后|一方面|另一方面", "enumerate", 0.9),
    # 强调
    (r"最重要|核心|关键|重点|本质|精髓|创新|突破|最.*是|尤其|特别是|值得注意", "emphasis", 0.85),
    # 对比/转折
    (r"但是|然而|相比|对比|不同于|区别|而不是|不是.*而是|传统.*而.*我们|反之", "contrast", 0.8),
    # 解释
    (r"也就是说|换句话说|具体来说|简单来说|举个例子|比如|例如|即|意味着", "explain", 0.7),
    # 问候/欢迎
    (r"你好|大家好|欢迎|很高兴|见到你|认识你", "greet", 0.75),
    # 否定
    (r"不是|并非|错误|不对|不能|不会|绝对不|从不", "deny", 0.65),
    # 不确定
    (r"可能|也许|大概|应该|或许|不确定|不一定", "uncertain", 0.5),
]

# anchor_type → gesture clip name
_ANCHOR_TO_GESTURE: dict[str, str] = {
    "enumerate": "gesture_enumerate",
    "emphasis":  "gesture_emphasis",
    "contrast":  "gesture_contrast",
    "explain":   "gesture_explain",
    "greet":     "gesture_greet",
    "deny":      "gesture_beat",       # 无 disagree clip 时降级
    "uncertain": "gesture_uncertain",
    "beat":      "gesture_beat",
}

# emotion 对表情强度的影响
_EMOTION_INTENSITY: dict[str, float] = {
    "happy":     1.0,
    "confident": 1.0,
    "surprised": 0.9,
    "neutral":   0.7,
    "sad":       0.5,
    "angry":     0.8,
}


@dataclass
class SemanticAnchor:
    text_fragment: str
    anchor_type: str
    confidence: float
    char_offset: int          # 在原文中的字符位置
    audio_time_ms: float = 0  # 对齐到音频后的时间


def extract_anchors(text: str) -> list[SemanticAnchor]:
    """从文本中提取语义锚点。"""
    anchors: list[SemanticAnchor] = []
    seen_offsets: set[int] = set()

    for pattern, anchor_type, confidence in _ANCHOR_RULES:
        for m in re.finditer(pattern, text):
            offset = m.start()
            # 避免同一位置重复触发
            if any(abs(offset - s) < 4 for s in seen_offsets):
                continue
            seen_offsets.add(offset)
            anchors.append(SemanticAnchor(
                text_fragment=m.group(0),
                anchor_type=anchor_type,
                confidence=confidence,
                char_offset=offset,
            ))

    anchors.sort(key=lambda a: a.char_offset)
    return anchors


def align_anchors_to_audio(
    anchors: list[SemanticAnchor],
    tts_result: AudioWithTimestamps,
) -> list[SemanticAnchor]:
    """将锚点字符位置映射到音频时间轴。

    MockTTS 没有词级时间戳，使用字符位置线性估算。
    真实 TTS 接入后可替换为精确对齐。
    """
    text_len = sum(
        len(pi.phoneme) for pi in tts_result.phoneme_intervals
    ) or 1
    duration_ms = tts_result.duration_ms

    # 用字符在文本中的比例估算时间
    total_chars = max(
        sum(len(pi.phoneme) for pi in tts_result.phoneme_intervals), 1
    )

    for anchor in anchors:
        ratio = min(anchor.char_offset / total_chars, 1.0)
        anchor.audio_time_ms = ratio * duration_ms

    return anchors


def schedule_gestures(
    anchors: list[SemanticAnchor],
    emotion: str,
    duration_ms: float,
    min_interval_ms: float = 1200,
    max_per_minute: int = 3,
) -> list[GestureEvent]:
    """从锚点列表生成手势事件，应用调度约束。"""
    if not anchors:
        return []

    intensity_scale = _EMOTION_INTENSITY.get(emotion, 0.7)
    events: list[GestureEvent] = []
    last_gesture_time: float = -min_interval_ms
    gesture_count: dict[str, int] = {}

    for anchor in anchors:
        gesture_name = _ANCHOR_TO_GESTURE.get(anchor.anchor_type, "gesture_beat")

        # 约束1：1.2秒内不重复大幅手势
        if anchor.audio_time_ms - last_gesture_time < min_interval_ms:
            continue

        # 约束2：同一手势每分钟不超过 max_per_minute 次
        minute_bucket = int(anchor.audio_time_ms / 60000)
        key = f"{gesture_name}_{minute_bucket}"
        if gesture_count.get(key, 0) >= max_per_minute:
            continue

        # 手势时长估算（根据 clip 类型）
        gesture_duration = _estimate_duration(anchor.anchor_type)
        pre_onset_ms = gesture_duration * 0.3   # apex 在手势开始后 30%

        start_ms = max(0, anchor.audio_time_ms - pre_onset_ms)
        apex_ms = anchor.audio_time_ms
        intensity = min(1.0, anchor.confidence * intensity_scale)

        events.append(GestureEvent(
            gesture_name=gesture_name,
            start_ms=start_ms,
            apex_ms=apex_ms,
            duration_ms=gesture_duration,
            intensity=intensity,
            anchor_type=anchor.anchor_type,
        ))

        last_gesture_time = anchor.audio_time_ms
        gesture_count[key] = gesture_count.get(key, 0) + 1

    return events


def _estimate_duration(anchor_type: str) -> float:
    """估算各类手势动作时长（ms）。"""
    durations = {
        "enumerate":  2000,
        "emphasis":   1500,
        "contrast":   2000,
        "explain":    1800,
        "greet":      2500,
        "deny":       1200,
        "uncertain":  1500,
        "beat":       1000,
    }
    return durations.get(anchor_type, 1500)


def compute_gesture_events(
    text: str,
    tts_result: AudioWithTimestamps,
    emotion: str = "neutral",
) -> list[GestureEvent]:
    """主入口：从文本和 TTS 结果计算手势事件列表。"""
    anchors = extract_anchors(text)
    if not anchors:
        return []

    anchors = align_anchors_to_audio(anchors, tts_result)
    return schedule_gestures(anchors, emotion, tts_result.duration_ms)
