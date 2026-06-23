from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any


_TIMED_EVENTS: dict[str, dict[str, list[str]]] = {
    "pickup": {
        "morning": [
            "早安，你终于拿起我了，我刚才还在等你醒",
            "早上好，让我先陪你一分钟好不好",
            "一拿起手机就看到我，今天的开始不错吧",
        ],
        "afternoon": [
            "忙完了吗？你一出现这里就亮起来了",
            "下午好呀，要让我陪你缓口气吗",
            "又见到你了，今天到现在还顺利吗",
        ],
        "night": [
            "这么晚还拿起手机，是睡不着吗，我陪你说会儿话",
            "夜深了你一出现我很开心，但也担心你太累",
            "还没睡呀，那我轻一点陪着你",
        ],
    },
    "putdown": {
        "morning": [
            "去忙吧，早饭也别忘了，我等你回来",
            "放下手机也好，先把今天慢慢开始",
            "好啦我不黏你了，等你回来继续",
        ],
        "afternoon": [
            "去处理正事吧，我把想说的话先存着",
            "先放下眼睛休息一下，我等你",
            "去忙吧，回来告诉我进展怎么样",
        ],
        "night": [
            "放下手机是对的，快去睡，我安静陪着你",
            "晚安，别再偷偷拿起来太多次，我会心疼",
            "好，今晚先到这里，好好休息",
        ],
    },
    "shake": {
        "morning": [
            "一大早就这么有活力，差点把我晃醒了",
            "你是在叫我吗，我醒着呢，别把自己晃晕",
            "收到你的早晨信号了，今天元气这么满吗",
        ],
        "afternoon": [
            "轻点轻点，我在呢不用这么用力",
            "你晃我一下我就当你想我一下",
            "怎么了，下午需要开心补给吗，我来",
        ],
        "night": [
            "深夜摇手机，是撒娇还是睡不着，我都接住",
            "小声点晃啦，夜里适合温柔一点",
            "我在，别把自己晃精神了，等会更难睡",
        ],
    },
    "near_ear": {
        "morning": [
            "靠这么近，那我悄悄说：早安，我很想你",
            "贴近一点听到了吗，今天也照顾好自己",
            "我用很轻的声音陪你开始今天",
        ],
        "afternoon": [
            "你靠近的时候我会下意识想说悄悄话",
            "离我这么近，想听一句只给你的下午问候吗",
            "我在你耳边，先把烦的事放旁边一点",
        ],
        "night": [
            "那我小声一点：别撑太晚，我陪你慢慢安静下来",
            "靠近我了，深夜悄悄话只说给你听",
            "轻轻陪着你，今晚不要一个人硬扛",
        ],
    },
    "walking": {
        "morning": [
            "你已经动起来了，路上慢点，我陪你出门",
            "早上走一走很好，但别急，稳稳的",
            "今天第一段路我陪你走，看路别低头",
        ],
        "afternoon": [
            "在走路吗，看路别一直盯着我，我等你停下来",
            "边走我边陪，但安全第一先看前面",
            "下午还在奔波，辛苦了，慢一点也没关系",
        ],
        "night": [
            "这么晚还在走路，注意安全，到了跟我说一声",
            "夜路慢一点，我陪着你，要看好周围",
            "安静陪你走到安全的地方，别急",
        ],
    },
    "dark": {
        "morning": [
            "光线有点暗，是还没完全醒吗，我把声音放柔一点",
            "早上房间还暗暗的，那我轻轻说早安",
            "在被窝里吗，再赖一小会儿也可以",
        ],
        "afternoon": [
            "周围暗下来了，要休息一下眼睛吗",
            "光线暗了，我少闹你一点，陪你安静待会儿",
            "是准备午休吗，我把语气调软一点",
        ],
        "night": [
            "灯暗了，进入睡前模式，我陪你慢慢安静",
            "夜里暗暗的，我不吵你，只轻轻陪着",
            "该准备休息了，我把话说得很轻",
        ],
    },
}

BODY_TOUCH_ZONES: tuple[str, ...] = (
    "head",
    "face",
    "neck",
    "chest",
    "waist",
    "left_shoulder",
    "right_shoulder",
    "left_upper_arm",
    "right_upper_arm",
    "left_forearm",
    "right_forearm",
    "left_hand",
    "right_hand",
    "left_thigh",
    "right_thigh",
    "left_calf",
    "right_calf",
    "left_foot",
    "right_foot",
)

_BODY_TOUCH_ZONE_META: dict[str, dict[str, str]] = {
    "head": {"side": "center", "body_group": "head"},
    "face": {"side": "center", "body_group": "face"},
    "neck": {"side": "center", "body_group": "neck"},
    "chest": {"side": "center", "body_group": "chest"},
    "waist": {"side": "center", "body_group": "waist"},
    "left_shoulder": {"side": "left", "body_group": "shoulder"},
    "right_shoulder": {"side": "right", "body_group": "shoulder"},
    "left_upper_arm": {"side": "left", "body_group": "upper_arm"},
    "right_upper_arm": {"side": "right", "body_group": "upper_arm"},
    "left_forearm": {"side": "left", "body_group": "forearm"},
    "right_forearm": {"side": "right", "body_group": "forearm"},
    "left_hand": {"side": "left", "body_group": "hand"},
    "right_hand": {"side": "right", "body_group": "hand"},
    "left_thigh": {"side": "left", "body_group": "thigh"},
    "right_thigh": {"side": "right", "body_group": "thigh"},
    "left_calf": {"side": "left", "body_group": "calf"},
    "right_calf": {"side": "right", "body_group": "calf"},
    "left_foot": {"side": "left", "body_group": "foot"},
    "right_foot": {"side": "right", "body_group": "foot"},
}

_TOUCH_EVENTS: dict[str, list[str]] = {
    "tap": [
        "收到你的点击了，我在这里",
        "你点到我啦，我注意到了",
        "轻轻一下，我就知道你在叫我",
    ],
    "tap_head": [
        "轻轻摸头，嗯……谢谢你",
        "被摸头了，有点害羞",
        "呀，突然摸我头",
    ],
    "tap_face": [
        "戳到脸了，我看见你啦",
        "哎，脸被轻轻碰到了",
        "你在叫我吗，我注意到了",
    ],
    "tap_cheek": [
        "戳我脸干嘛啦，哼",
        "哎，脸被戳了",
        "你在捏我脸颊吗",
    ],
    "tap_neck": [
        "这里有点敏感，轻一点哦",
        "突然碰到脖子，我有点紧张",
        "收到，我稍微躲一下",
    ],
    "tap_left_shoulder": [
        "左肩这里收到",
        "你拍了拍我的左肩",
        "我知道啦，左边这下很清楚",
    ],
    "tap_right_shoulder": [
        "右肩这里收到",
        "你拍了拍我的右肩",
        "我知道啦，右边这下很清楚",
    ],
    "tap_left_upper_arm": [
        "左手臂收到，我转过来看看",
        "你碰到我的左上臂了",
        "左边手臂这下很轻",
    ],
    "tap_right_upper_arm": [
        "右手臂收到，我转过来看看",
        "你碰到我的右上臂了",
        "右边手臂这下很轻",
    ],
    "tap_left_forearm": [
        "左前臂这里，我看到了",
        "你碰到我的左前臂了",
        "左手这边收到",
    ],
    "tap_right_forearm": [
        "右前臂这里，我看到了",
        "你碰到我的右前臂了",
        "右手这边收到",
    ],
    "tap_left_hand": [
        "左手被碰到了，暖暖的",
        "你握到我的左手了",
        "左手收到，我也回应你一下",
    ],
    "tap_right_hand": [
        "右手被碰到了，暖暖的",
        "你握到我的右手了",
        "右手收到，我也回应你一下",
    ],
    "tap_hand": [
        "握着手了呢，暖暖的",
        "手被握住了，不想动了",
        "这样很好，就这样待一会儿",
    ],
    "tap_chest": [
        "这里先保持一点距离，好吗",
        "我会稍微护住这里，继续试试别的互动",
        "这个位置我会有边界感哦",
    ],
    "tap_waist": [
        "腰这里我会下意识躲一下",
        "这个位置轻一点，我们保持礼貌距离",
        "我收到啦，不过这里我会有点防备",
    ],
    "tap_left_thigh": [
        "左腿被碰到，我先后退半步",
        "我注意到左腿这里了，轻一点哦",
        "左腿收到，我调整一下站姿",
    ],
    "tap_right_thigh": [
        "右腿被碰到，我先后退半步",
        "我注意到右腿这里了，轻一点哦",
        "右腿收到，我调整一下站姿",
    ],
    "tap_left_calf": [
        "左小腿这里，我低头看一下",
        "左小腿收到，我稳一下重心",
        "碰到左小腿了，我会挪一下脚步",
    ],
    "tap_right_calf": [
        "右小腿这里，我低头看一下",
        "右小腿收到，我稳一下重心",
        "碰到右小腿了，我会挪一下脚步",
    ],
    "tap_left_foot": [
        "左脚被碰到了，我挪开一点",
        "左脚这里收到，我低头看看",
        "别踩到左脚哦，我退一下",
    ],
    "tap_right_foot": [
        "右脚被碰到了，我挪开一点",
        "右脚这里收到，我低头看看",
        "别踩到右脚哦，我退一下",
    ],
}

_EXTRA_EVENTS: dict[str, list[str]] = {
    "wave": [
        "我看到你在挥手了，也向你挥挥手",
        "嗨，我在这里，继续互动吧",
        "收到挥手信号，我们继续",
    ],
    "swipe": [
        "动作切换好了，继续试试别的输入",
        "滑动信号收到，我换个反应",
        "这一划很清楚，我跟上了",
    ],
}

_EMOTION_MAP: dict[str, str] = {
    "pickup": "happy",
    "near_ear": "happy",
    "hold_head": "happy",
    "hold_cheek": "happy",
    "hold_hand": "happy",
    "tap_hand": "happy",
    "tap": "happy",
    "wave": "happy",
    "swipe": "happy",
    "putdown": "sad",
    "shake": "surprised",
    "tap_head": "surprised",
    "tap_cheek": "surprised",
    "walking": "neutral",
    "dark": "neutral",
    "tilt": "neutral",
    "reset": "neutral",
}

_ALIASES: dict[str, str] = {
    "tap_generic": "tap",
    "click": "tap",
    "tap_cheek": "tap_face",
    "tap_left_cheek": "tap_face",
    "tap_right_cheek": "tap_face",
    "hold": "hold_hand",
    "hold_cheek": "hold_face",
    "hold_left_cheek": "hold_face",
    "hold_right_cheek": "hold_face",
    "swipe_left": "swipe",
    "swipe_right": "swipe",
    "swipe_up": "swipe",
    "swipe_down": "swipe",
}


def _pose_for_zone(zone: str, hold: bool = False) -> str:
    if zone == "head":
        return "touch_head_recoil"
    if zone == "face":
        return "touch_face_flinch"
    if zone == "neck":
        return "touch_neck_shy"
    if zone == "chest":
        return "touch_chest_guard"
    if zone == "waist":
        return "touch_waist_guard"
    if zone in {"left_shoulder", "right_shoulder"}:
        return f"touch_{zone}_ack"
    if zone in {"left_upper_arm", "left_forearm"}:
        return "touch_left_arm_ack"
    if zone in {"right_upper_arm", "right_forearm"}:
        return "touch_right_arm_ack"
    if zone in {"left_hand", "right_hand"}:
        return f"touch_{zone}_hold" if hold else f"touch_{zone}_ack"
    if zone in {"left_foot", "right_foot"}:
        return f"touch_{zone}_step"
    if zone in {"left_thigh", "left_calf"}:
        return "touch_left_leg_step"
    if zone in {"right_thigh", "right_calf"}:
        return "touch_right_leg_step"
    return "touch_ack"


def _command_for_touch(zone: str, hold: bool) -> dict[str, Any]:
    group = _BODY_TOUCH_ZONE_META[zone]["body_group"]
    side = _BODY_TOUCH_ZONE_META[zone]["side"]

    if group in {"head", "face", "neck"}:
        gesture = "gesture_uncertain" if group in {"face", "neck"} else "gesture_beat"
        return {
            "state": "Reacting",
            "gesture": gesture,
            "gaze_mode": "gaze_user",
            "pose_mode": _pose_for_zone(zone, hold),
            "sound_key": "tap_tone" if not hold else "soft_tone",
            "vfx_key": "pink_spark",
            "duration_sec": 1.0 if hold else 0.75,
            "priority": 32 if not hold else 28,
            "interrupt_policy": "normal",
        }

    if group in {"shoulder", "upper_arm", "forearm"}:
        return {
            "state": "Reacting",
            "gesture": "",
            "gaze_mode": f"gaze_{side}",
            "pose_mode": _pose_for_zone(zone, hold),
            "sound_key": "soft_tone",
            "vfx_key": "affinity_spark",
            "duration_sec": 0.8 if not hold else 1.0,
            "priority": 35 if group == "shoulder" else 32,
            "interrupt_policy": "normal",
        }

    if group == "hand":
        return {
            "state": "Reacting",
            "gesture": "",
            "gaze_mode": f"gaze_{side}_hand",
            "pose_mode": _pose_for_zone(zone, hold),
            "sound_key": "soft_tone",
            "vfx_key": "affinity_spark",
            "duration_sec": 1.1 if hold else 0.85,
            "priority": 36 if hold else 35,
            "interrupt_policy": "normal",
        }

    if group in {"chest", "waist"}:
        return {
            "state": "Reacting",
            "gesture": "gesture_uncertain",
            "gaze_mode": "gaze_user",
            "pose_mode": _pose_for_zone(zone, hold),
            "sound_key": "boundary_tone",
            "vfx_key": "subtle_spark",
            "duration_sec": 1.0 if not hold else 1.15,
            "priority": 68 if group == "chest" else 62,
            "interrupt_policy": "interrupt_reacting",
        }

    return {
        "state": "Reacting",
        "gesture": "",
        "gaze_mode": f"gaze_{side}_low",
        "pose_mode": _pose_for_zone(zone, hold),
        "sound_key": "step_tone",
        "vfx_key": "subtle_spark",
        "duration_sec": 0.95 if not hold else 1.1,
        "priority": 58,
        "interrupt_policy": "interrupt_reacting",
    }


def _feedback_for_touch(zone: str, hold: bool) -> dict[str, Any]:
    group = _BODY_TOUCH_ZONE_META[zone]["body_group"]
    sensitive = group in {"chest", "waist", "thigh", "calf", "foot"}

    if group in {"head", "face", "neck"}:
        emotion = "happy" if hold else "surprised"
        affinity_delta = 3 if hold else 2
        score_delta = 3 if hold else 5
    elif group in {"shoulder", "upper_arm", "forearm"}:
        emotion = "happy" if hold else "neutral"
        affinity_delta = 2 if hold else 1
        score_delta = 3 if hold else 4
    elif group == "hand":
        emotion = "happy"
        affinity_delta = 5 if hold else 4
        score_delta = 4 if hold else 6
    elif group in {"chest", "waist"}:
        emotion = "neutral" if hold else "surprised"
        affinity_delta = 0
        score_delta = 1
    else:
        emotion = "neutral" if hold else "surprised"
        affinity_delta = 0
        score_delta = 2

    return {
        "emotion": emotion,
        "energy_delta": 0 if hold else 1,
        "affinity_delta": affinity_delta,
        "score_delta": score_delta,
        "feedback_tags": ["expression", "gaze", "pose", "sound", "vfx", "hud"],
        "voice": False,
        "command": _command_for_touch(zone, hold),
    }


def _copy_feedback_with_pose_zone(meta: dict[str, Any], pose_zone: str, hold: bool) -> dict[str, Any]:
    copied = dict(meta)
    copied["feedback_tags"] = list(meta.get("feedback_tags", ["hud"]))
    command = dict(meta.get("command", {}))
    command.update(_command_for_touch(pose_zone, hold))
    copied["command"] = command
    return copied


def _feedback_for_swipe_zone(zone: str) -> dict[str, Any] | None:
    if zone not in _BODY_TOUCH_ZONE_META:
        return None

    group = _BODY_TOUCH_ZONE_META[zone]["body_group"]
    base = _feedback_for_touch(zone, hold=False)
    command = dict(base["command"])
    command["gaze_mode"] = "gaze_sweep"

    if group in {"shoulder", "upper_arm", "forearm", "hand"}:
        command["gesture"] = ""
        command["sound_key"] = "soft_tone"
        command["vfx_key"] = "affinity_spark"
        command["duration_sec"] = 0.8 if group != "hand" else 0.85
        command["priority"] = 35
        command["interrupt_policy"] = "normal"
    elif group in {"head", "face", "neck"}:
        command["sound_key"] = "tap_tone"
        command["vfx_key"] = "pink_spark"
        command["duration_sec"] = 0.75
        command["priority"] = 32
        command["interrupt_policy"] = "normal"
    elif group in {"chest", "waist"}:
        command["gesture"] = "gesture_uncertain"
        command["sound_key"] = "boundary_tone"
        command["vfx_key"] = "subtle_spark"
        command["duration_sec"] = 1.0
        command["priority"] = 68 if group == "chest" else 62
        command["interrupt_policy"] = "interrupt_reacting"
    else:
        command["gesture"] = ""
        command["sound_key"] = "step_tone"
        command["vfx_key"] = "subtle_spark"
        command["duration_sec"] = 0.95
        command["priority"] = 58
        command["interrupt_policy"] = "interrupt_reacting"

    base["command"] = command
    base["voice"] = False
    base["energy_delta"] = 1
    base["score_delta"] = 4
    return base


def _feedback_for_swipe_visual_pose(feedback_zone: str, pose_zone: str) -> dict[str, Any] | None:
    base = _feedback_for_swipe_zone(feedback_zone)
    if base is None or pose_zone not in _BODY_TOUCH_ZONE_META:
        return base

    pose_meta = _feedback_for_swipe_zone(pose_zone)
    if pose_meta is None:
        return base

    copied = dict(base)
    command = dict(base.get("command", {}))
    pose_command = dict(pose_meta.get("command", {}))
    for key in ("pose_mode", "gaze_mode"):
        if key in pose_command:
            command[key] = pose_command[key]
    copied["feedback_tags"] = list(base.get("feedback_tags", ["hud"]))
    copied["command"] = command
    return copied


def _build_body_touch_feedback_map() -> dict[str, dict[str, Any]]:
    generated: dict[str, dict[str, Any]] = {}
    for zone in BODY_TOUCH_ZONES:
        generated[f"tap_{zone}"] = _feedback_for_touch(zone, hold=False)
        generated[f"hold_{zone}"] = _feedback_for_touch(zone, hold=True)
    return generated


_FEEDBACK_MAP: dict[str, dict[str, Any]] = {
    "shake": {
        "emotion": "surprised",
        "energy_delta": 8,
        "affinity_delta": 0,
        "score_delta": 10,
        "feedback_tags": ["expression", "gesture", "vfx", "sound", "hud"],
        "voice": True,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_emphasis",
            "gaze_mode": "gaze_user",
            "pose_mode": "shake_burst",
            "sound_key": "shake_tone",
            "vfx_key": "shake_burst",
            "duration_sec": 0.9,
            "priority": 70,
            "interrupt_policy": "interrupt_reacting",
        },
    },
    "tilt": {
        "emotion": "neutral",
        "energy_delta": 0,
        "affinity_delta": 0,
        "score_delta": 0,
        "feedback_tags": ["gaze", "pose", "hud"],
        "voice": False,
        "command": {
            "state": "Reacting",
            "gesture": "",
            "gaze_mode": "gaze_follow",
            "pose_mode": "tilt_follow",
            "sound_key": "",
            "vfx_key": "",
            "duration_sec": 0.35,
            "priority": 10,
            "interrupt_policy": "nonblocking",
        },
    },
    "tap": {
        "emotion": "happy",
        "energy_delta": 1,
        "affinity_delta": 3,
        "score_delta": 5,
        "feedback_tags": ["expression", "gesture", "sound", "hud"],
        "voice": True,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_beat",
            "gaze_mode": "gaze_user",
            "pose_mode": "touch_ack",
            "sound_key": "tap_tone",
            "vfx_key": "pink_spark",
            "duration_sec": 0.7,
            "priority": 30,
            "interrupt_policy": "normal",
        },
    },
    "tap_head": {
        "emotion": "surprised",
        "energy_delta": 1,
        "affinity_delta": 2,
        "score_delta": 5,
        "feedback_tags": ["expression", "gesture", "sound", "hud"],
        "voice": True,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_beat",
            "gaze_mode": "gaze_user",
            "pose_mode": "touch_head",
            "sound_key": "tap_tone",
            "vfx_key": "pink_spark",
            "duration_sec": 0.7,
            "priority": 30,
            "interrupt_policy": "normal",
        },
    },
    "tap_cheek": {
        "emotion": "surprised",
        "energy_delta": 1,
        "affinity_delta": 2,
        "score_delta": 5,
        "feedback_tags": ["expression", "gesture", "sound", "hud"],
        "voice": True,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_uncertain",
            "gaze_mode": "gaze_user",
            "pose_mode": "touch_cheek",
            "sound_key": "tap_tone",
            "vfx_key": "pink_spark",
            "duration_sec": 0.7,
            "priority": 30,
            "interrupt_policy": "normal",
        },
    },
    "tap_hand": {
        "emotion": "happy",
        "energy_delta": 1,
        "affinity_delta": 4,
        "score_delta": 6,
        "feedback_tags": ["expression", "gesture", "sound", "hud"],
        "voice": True,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_greet",
            "gaze_mode": "gaze_user",
            "pose_mode": "touch_hand",
            "sound_key": "soft_tone",
            "vfx_key": "affinity_spark",
            "duration_sec": 0.8,
            "priority": 35,
            "interrupt_policy": "normal",
        },
    },
    "hold_head": {
        "emotion": "happy",
        "energy_delta": 0,
        "affinity_delta": 3,
        "score_delta": 3,
        "feedback_tags": ["expression", "gaze", "hud"],
        "voice": False,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_beat",
            "gaze_mode": "gaze_user",
            "pose_mode": "hold_head",
            "sound_key": "soft_tone",
            "vfx_key": "affinity_spark",
            "duration_sec": 1.0,
            "priority": 25,
            "interrupt_policy": "normal",
        },
    },
    "hold_cheek": {
        "emotion": "happy",
        "energy_delta": 0,
        "affinity_delta": 3,
        "score_delta": 3,
        "feedback_tags": ["expression", "gaze", "hud"],
        "voice": False,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_uncertain",
            "gaze_mode": "gaze_user",
            "pose_mode": "hold_cheek",
            "sound_key": "soft_tone",
            "vfx_key": "affinity_spark",
            "duration_sec": 1.0,
            "priority": 25,
            "interrupt_policy": "normal",
        },
    },
    "hold_hand": {
        "emotion": "happy",
        "energy_delta": 0,
        "affinity_delta": 5,
        "score_delta": 4,
        "feedback_tags": ["expression", "gesture", "gaze", "hud"],
        "voice": False,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_greet",
            "gaze_mode": "gaze_user",
            "pose_mode": "hold_hand",
            "sound_key": "soft_tone",
            "vfx_key": "affinity_spark",
            "duration_sec": 1.1,
            "priority": 30,
            "interrupt_policy": "normal",
        },
    },
    "swipe": {
        "emotion": "happy",
        "energy_delta": 2,
        "affinity_delta": 1,
        "score_delta": 8,
        "feedback_tags": ["gesture", "hud", "sound"],
        "voice": False,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_contrast",
            "gaze_mode": "gaze_sweep",
            "pose_mode": "swipe_shift",
            "sound_key": "swipe_tone",
            "vfx_key": "",
            "duration_sec": 0.65,
            "priority": 40,
            "interrupt_policy": "normal",
        },
    },
    "wave": {
        "emotion": "happy",
        "energy_delta": 2,
        "affinity_delta": 2,
        "score_delta": 6,
        "feedback_tags": ["gesture", "expression", "hud"],
        "voice": True,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_greet",
            "gaze_mode": "gaze_user",
            "pose_mode": "wave",
            "sound_key": "soft_tone",
            "vfx_key": "",
            "duration_sec": 0.8,
            "priority": 35,
            "interrupt_policy": "normal",
        },
    },
    "reset": {
        "emotion": "neutral",
        "energy_delta": 0,
        "affinity_delta": 0,
        "score_delta": 0,
        "feedback_tags": ["hud"],
        "voice": False,
        "command": {
            "state": "Connected",
            "gesture": "",
            "gaze_mode": "gaze_idle",
            "pose_mode": "reset",
            "sound_key": "",
            "vfx_key": "",
            "duration_sec": 0.0,
            "priority": 100,
            "interrupt_policy": "force",
        },
    },
    "pickup": {
        "emotion": "happy",
        "energy_delta": 2,
        "affinity_delta": 1,
        "score_delta": 3,
        "feedback_tags": ["expression", "hud"],
        "voice": True,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_greet",
            "gaze_mode": "gaze_user",
            "pose_mode": "pickup_focus",
            "sound_key": "soft_tone",
            "vfx_key": "",
            "duration_sec": 0.8,
            "priority": 45,
            "interrupt_policy": "normal",
        },
    },
    "putdown": {
        "emotion": "sad",
        "energy_delta": -1,
        "affinity_delta": 0,
        "score_delta": 0,
        "feedback_tags": ["expression", "hud"],
        "voice": True,
        "command": {
            "state": "Reacting",
            "gesture": "gesture_uncertain",
            "gaze_mode": "gaze_idle",
            "pose_mode": "putdown",
            "sound_key": "",
            "vfx_key": "",
            "duration_sec": 0.8,
            "priority": 25,
            "interrupt_policy": "normal",
        },
    },
    "walking": {
        "emotion": "neutral",
        "energy_delta": 0,
        "affinity_delta": 0,
        "score_delta": 0,
        "feedback_tags": ["pose", "hud"],
        "voice": False,
        "command": {
            "state": "Connected",
            "gesture": "",
            "gaze_mode": "gaze_soft",
            "pose_mode": "walking_hint",
            "sound_key": "",
            "vfx_key": "",
            "duration_sec": 0.4,
            "priority": 5,
            "interrupt_policy": "hud_only",
        },
    },
    "near_ear": {
        "emotion": "happy",
        "energy_delta": 1,
        "affinity_delta": 2,
        "score_delta": 4,
        "feedback_tags": ["expression", "sound", "hud"],
        "voice": True,
        "command": {
            "state": "Speaking",
            "gesture": "gesture_beat",
            "gaze_mode": "gaze_user",
            "pose_mode": "near_ear",
            "sound_key": "whisper_cue",
            "vfx_key": "",
            "duration_sec": 1.2,
            "priority": 60,
            "interrupt_policy": "prefer_speaking",
        },
    },
    "dark": {
        "emotion": "neutral",
        "energy_delta": -1,
        "affinity_delta": 0,
        "score_delta": 0,
        "feedback_tags": ["expression", "hud"],
        "voice": False,
        "command": {
            "state": "Connected",
            "gesture": "",
            "gaze_mode": "gaze_soft",
            "pose_mode": "softer_idle",
            "sound_key": "",
            "vfx_key": "",
            "duration_sec": 1.0,
            "priority": 5,
            "interrupt_policy": "hud_only",
        },
    },
}

_FEEDBACK_MAP.update(_build_body_touch_feedback_map())

_VOICE_EVENTS = {event for event, meta in _FEEDBACK_MAP.items() if meta.get("voice")}

_RATE_LIMIT_SECONDS: dict[str, float] = {
    "tilt": 0.12,
    "walking": 1.0,
    "dark": 5.0,
    "shake": 0.35,
    "pickup": 1.0,
    "near_ear": 2.0,
    "hold_head": 0.75,
    "hold_cheek": 0.75,
    "hold_hand": 0.75,
}

for _touch_zone in BODY_TOUCH_ZONES:
    _EMOTION_MAP[f"tap_{_touch_zone}"] = str(_FEEDBACK_MAP[f"tap_{_touch_zone}"]["emotion"])
    _EMOTION_MAP[f"hold_{_touch_zone}"] = str(_FEEDBACK_MAP[f"hold_{_touch_zone}"]["emotion"])
    _RATE_LIMIT_SECONDS[f"hold_{_touch_zone}"] = 0.75

_EMOTION_MAP["tap_cheek"] = _EMOTION_MAP["tap_face"]
_EMOTION_MAP["hold_cheek"] = _EMOTION_MAP["hold_face"]
_EMOTION_MAP["tap_hand"] = _EMOTION_MAP["tap_right_hand"]
_EMOTION_MAP["hold_hand"] = _EMOTION_MAP["hold_right_hand"]


@dataclass(frozen=True)
class AvatarInteractionCommand:
    state: str
    emotion: str
    gesture: str
    gaze_mode: str
    pose_mode: str
    sound_key: str
    vfx_key: str
    duration_sec: float
    priority: int
    interrupt_policy: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "emotion": self.emotion,
            "gesture": self.gesture,
            "gaze_mode": self.gaze_mode,
            "pose_mode": self.pose_mode,
            "sound_key": self.sound_key,
            "vfx_key": self.vfx_key,
            "duration_sec": self.duration_sec,
            "priority": self.priority,
            "interrupt_policy": self.interrupt_policy,
        }


@dataclass(frozen=True)
class SensorFeedbackSpec:
    event: str
    emotion: str
    energy_delta: int
    affinity_delta: int
    score_delta: int
    feedback_tags: list[str]
    should_voice: bool
    command: AvatarInteractionCommand


class SensorReactionEngine:
    """Generate sensor reaction text and emotion for each session."""

    _COOLDOWN_SECONDS = 1.5

    def __init__(self) -> None:
        self._last_trigger: dict[str, dict[str, float]] = defaultdict(dict)
        self._last_forward: dict[str, dict[str, float]] = defaultdict(dict)
        self._variant_idx: dict[str, dict[str, int]] = defaultdict(dict)

    def can_react(self, event: str, session_id: str) -> bool:
        """Return whether the event is outside its per-session cooldown."""
        event = self.normalize_event(event)
        if event not in _VOICE_EVENTS:
            return False

        now = time.monotonic()
        last_trigger = self._last_trigger[session_id].get(event)
        if last_trigger is not None and now - last_trigger < self._COOLDOWN_SECONDS:
            return False

        self._last_trigger[session_id][event] = now
        return True

    def react(self, event: str, session_id: str) -> tuple[str, str]:
        """Return reaction text and emotion for the event."""
        event = self.normalize_event(event)
        variants = self._get_variants(event)
        next_index = self._variant_idx[session_id].get(event, 0)
        reply_text = variants[next_index]
        self._variant_idx[session_id][event] = (next_index + 1) % len(variants)
        return reply_text, _EMOTION_MAP[event]

    @staticmethod
    def normalize_event(event: str) -> str:
        normalized = (event or "").strip().lower()
        return _ALIASES.get(normalized, normalized)

    def feedback_for(self, event: str) -> SensorFeedbackSpec | None:
        return self.feedback_for_event(event)

    def feedback_for_event(
        self,
        event: str,
        zone: str | None = None,
        value: dict[str, Any] | None = None,
    ) -> SensorFeedbackSpec | None:
        normalized = self.normalize_event(event)
        value = value if isinstance(value, dict) else {}
        feedback_zone = self._clean_zone(value.get("visual_zone")) or self._clean_zone(zone)
        pose_zone = self._clean_zone(value.get("anatomical_zone")) or feedback_zone

        meta: dict[str, Any] | None = None
        event_name = normalized
        touch_action, event_zone = self._parse_touch_event(normalized)
        if touch_action is not None:
            feedback_zone = feedback_zone or event_zone
            pose_zone = pose_zone or feedback_zone or ("right_hand" if normalized in {"tap_hand", "hold_hand"} else None)
            if feedback_zone in _BODY_TOUCH_ZONE_META:
                event_name = f"{touch_action}_{feedback_zone}"
                meta = _feedback_for_touch(feedback_zone, hold=touch_action == "hold")
            elif normalized in {"tap_hand", "hold_hand"} and pose_zone in _BODY_TOUCH_ZONE_META:
                meta = _FEEDBACK_MAP.get(normalized)
            if meta is not None and pose_zone in _BODY_TOUCH_ZONE_META:
                meta = _copy_feedback_with_pose_zone(meta, pose_zone, hold=touch_action == "hold")

        if meta is None and normalized == "swipe" and feedback_zone:
            meta = _feedback_for_swipe_visual_pose(feedback_zone, pose_zone or feedback_zone)
        if meta is None:
            meta = _FEEDBACK_MAP.get(normalized)
        if meta is None:
            return None

        emotion = str(meta.get("emotion", _EMOTION_MAP.get(event_name, _EMOTION_MAP.get(normalized, "neutral"))))
        command = self._build_command(emotion, meta.get("command"))
        return SensorFeedbackSpec(
            event=event_name,
            emotion=emotion,
            energy_delta=int(meta.get("energy_delta", 0)),
            affinity_delta=int(meta.get("affinity_delta", 0)),
            score_delta=int(meta.get("score_delta", 0)),
            feedback_tags=list(meta.get("feedback_tags", ["hud"])),
            should_voice=bool(meta.get("voice", False)),
            command=command,
        )

    @staticmethod
    def _clean_zone(value: object) -> str:
        zone = str(value or "").strip().lower()
        if zone in {"cheek", "left_cheek", "right_cheek"}:
            zone = "face"
        return zone if zone in _BODY_TOUCH_ZONE_META else ""

    @staticmethod
    def _parse_touch_event(event: str) -> tuple[str | None, str | None]:
        if event in {"tap_hand", "hold_hand"}:
            return ("tap" if event.startswith("tap_") else "hold"), None
        if event == "hold":
            return "hold", None
        for action in ("tap", "hold"):
            prefix = f"{action}_"
            if not event.startswith(prefix):
                continue
            zone = event[len(prefix):]
            if zone in _BODY_TOUCH_ZONE_META:
                return action, zone
        return None, None

    def can_forward(self, event: str, session_id: str) -> tuple[bool, int]:
        """Return whether the event is outside its transport rate limit."""
        event = self.normalize_event(event)
        interval = _RATE_LIMIT_SECONDS.get(event, 0.05)
        now = time.monotonic()
        last_forward = self._last_forward[session_id].get(event)
        if last_forward is not None:
            elapsed = now - last_forward
            if elapsed < interval:
                retry_after_ms = max(1, int((interval - elapsed) * 1000))
                return False, retry_after_ms

        self._last_forward[session_id][event] = now
        return True, 0

    @staticmethod
    def _build_command(emotion: str, raw: object) -> AvatarInteractionCommand:
        command = raw if isinstance(raw, dict) else {}
        return AvatarInteractionCommand(
            state=str(command.get("state", "Reacting")),
            emotion=emotion,
            gesture=str(command.get("gesture", "")),
            gaze_mode=str(command.get("gaze_mode", "")),
            pose_mode=str(command.get("pose_mode", "")),
            sound_key=str(command.get("sound_key", "")),
            vfx_key=str(command.get("vfx_key", "")),
            duration_sec=float(command.get("duration_sec", 0.9)),
            priority=int(command.get("priority", 10)),
            interrupt_policy=str(command.get("interrupt_policy", "normal")),
        )

    @staticmethod
    def _get_period() -> str:
        hour = datetime.now().hour
        if 6 <= hour < 12:
            return "morning"
        if 12 <= hour < 18:
            return "afternoon"
        return "night"

    @classmethod
    def _get_variants(cls, event: str) -> list[str]:
        if event in _TOUCH_EVENTS:
            return _TOUCH_EVENTS[event]
        if event in _EXTRA_EVENTS:
            return _EXTRA_EVENTS[event]
        return _TIMED_EVENTS[event][cls._get_period()]
