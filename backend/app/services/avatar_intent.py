"""Explicit avatar action intent parsing and response shaping."""
from __future__ import annotations

import re

from app.schemas import AgentResponse, AvatarInteractionCommand, GestureEvent


def parse_avatar_action_intent(text: str) -> AvatarInteractionCommand | None:
    normalized = re.sub(r"\s+", "", (text or "").strip().lower())
    if not normalized:
        return None

    if re.search(r"(恢复|回到|变回|普通|正常).*(表情|状态|样子)|neutral|自然表情", normalized):
        return _command(emotion="neutral", gaze_mode="gaze_idle", duration_sec=1.0)

    emotion_map = [
        (r"开心|高兴|快乐|笑一|笑一下|笑笑", "happy", 1.6),
        (r"难过|伤心|沮丧", "sad", 1.6),
        (r"生气|愤怒|凶一点", "angry", 1.4),
        (r"惊讶|吃惊|惊喜", "surprised", 1.4),
        (r"自信|得意|骄傲", "confident", 1.6),
        (r"放松|轻松", "neutral", 1.2),
    ]
    if re.search(r"表情|脸|样子|做.*(开心|高兴|难过|伤心|生气|惊讶|自信|放松)", normalized):
        for pattern, emotion, duration in emotion_map:
            if re.search(pattern, normalized):
                return _command(emotion=emotion, duration_sec=duration)

    if re.search(r"挥挥手|挥手|打个招呼|招手", normalized):
        return _command(emotion="happy", gesture="gesture_greet", gaze_mode="gaze_user", duration_sec=1.4)
    if re.search(r"点头|确认一下|表示确认", normalized):
        return _command(emotion="neutral", gesture="gesture_acknowledge", gaze_mode="gaze_user", duration_sec=1.0)
    if re.search(r"解释一下|讲一下|说明一下", normalized):
        return _command(emotion="neutral", gesture="gesture_explain", gaze_mode="gaze_user", duration_sec=1.2)
    if re.search(r"强调一下|重点|强调", normalized):
        return _command(emotion="confident", gesture="gesture_emphasis", gaze_mode="gaze_user", duration_sec=1.1)
    if re.search(r"摆手|否定一下|不要|拒绝一下", normalized):
        return _command(emotion="neutral", gesture="gesture_negate", gaze_mode="gaze_user", duration_sec=1.0)

    if re.search(r"看左边|往左看|看向左", normalized):
        return _command(gaze_mode="gaze_left", duration_sec=1.4)
    if re.search(r"看右边|往右看|看向右", normalized):
        return _command(gaze_mode="gaze_right", duration_sec=1.4)
    if re.search(r"看我|看着我|看镜头|看用户", normalized):
        return _command(gaze_mode="gaze_user", duration_sec=1.2)
    if re.search(r"低头|往下看|看下面", normalized):
        return _command(gaze_mode="gaze_soft", duration_sec=1.2)
    if re.search(r"看手|看看手", normalized):
        return _command(gaze_mode="gaze_right_hand", duration_sec=1.2)
    if re.search(r"放松看|别盯着|随便看", normalized):
        return _command(gaze_mode="gaze_idle", duration_sec=1.0)

    return None


def apply_avatar_action(response: AgentResponse, command: AvatarInteractionCommand | None) -> AgentResponse:
    if command is None:
        return response

    response.avatar_action = command
    response.dialogue_act = "avatar_action"
    if command.emotion:
        response.emotion = command.emotion
    if not (response.reply_text or "").strip():
        response.reply_text = action_ack_text(command)
    return response


def action_ack_text(command: AvatarInteractionCommand) -> str:
    if command.gesture == "gesture_greet":
        return "好，我挥挥手。"
    if command.gesture == "gesture_emphasis":
        return "好，我强调一下。"
    if command.gesture == "gesture_acknowledge":
        return "好，我点点头。"
    if command.gesture == "gesture_negate":
        return "好，我摆摆手。"
    if command.gaze_mode == "gaze_left":
        return "好，我看向左边。"
    if command.gaze_mode == "gaze_right":
        return "好，我看向右边。"
    if command.gaze_mode == "gaze_user":
        return "好，我看着你。"
    if command.gaze_mode:
        return "好，我调整视线。"
    if command.emotion == "happy":
        return "好，我做一个开心的表情。"
    if command.emotion == "neutral":
        return "好，我恢复自然表情。"
    return "好，我来做一下。"


def avatar_action_gesture_event(command: AvatarInteractionCommand | None) -> GestureEvent | None:
    if command is None or not command.gesture:
        return None
    duration_ms = max(300.0, float(command.duration_sec or 1.0) * 1000.0)
    return GestureEvent(
        gesture_name=command.gesture,
        start_ms=80.0,
        apex_ms=min(420.0, duration_ms * 0.45),
        duration_ms=duration_ms,
        intensity=1.0,
        anchor_type="explicit_action",
    )


def _command(
    *,
    emotion: str = "neutral",
    gesture: str = "",
    gaze_mode: str = "",
    pose_mode: str = "",
    duration_sec: float = 1.2,
) -> AvatarInteractionCommand:
    return AvatarInteractionCommand(
        state="Reacting",
        emotion=emotion,
        gesture=gesture,
        gaze_mode=gaze_mode,
        pose_mode=pose_mode,
        duration_sec=duration_sec,
        priority=80,
        interrupt_policy="prefer_speaking",
    )
