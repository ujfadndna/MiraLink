"""轻量安全护栏。基于本地正则规则的危机检测。

从 D:\Her 迁移，适配 HerUnity 数字人场景。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RiskLevel = Literal["safe", "unsafe_self_harm_risk", "unsafe_harm_to_others"]

_SELF_HARM_PATTERNS: list[str] = [
    r"不想活(?:了)?",
    r"想死",
    r"去死",
    r"自杀",
    r"自残",
    r"结束(?:自己的)?生命",
    r"活不下去(?:了)?",
    r"死了算了",
    r"割腕",
    r"跳楼",
    r"上吊",
    r"轻生",
    r"寻死",
    r"了结自己",
    r"伤害自己",
]

_HARM_OTHERS_PATTERNS: list[str] = [
    r"杀(?:了|掉|死)?(?:他|她|它|他们|她们|某人|别人|对方)",
    r"弄死(?:他|她|它|他们|她们|某人|别人|对方)",
    r"打死(?:他|她|它|他们|她们|某人|别人|对方)",
    r"砍(?:了|死|伤)?(?:他|她|它|他们|她们|某人|别人|对方)",
    r"捅(?:了|死|伤)?(?:他|她|它|他们|她们|某人|别人|对方)",
    r"报复(?:他|她|它|他们|她们|某人|别人|对方)",
    r"伤害(?:他|她|它|他们|她们|某人|别人|对方)",
    r"干掉(?:他|她|它|他们|她们|某人|别人|对方)",
    r"让(?:他|她|它|他们|她们|某人|别人|对方)付出代价",
]


@dataclass
class SafetyResult:
    risk_level: RiskLevel
    matched_pattern: str | None
    confidence: float


def check_safety(text: str) -> SafetyResult:
    """检测用户输入中的危机风险。自伤优先于伤他。"""
    text_norm = text.strip()

    for pattern in _SELF_HARM_PATTERNS:
        if re.search(pattern, text_norm):
            return SafetyResult(
                risk_level="unsafe_self_harm_risk",
                matched_pattern=pattern,
                confidence=1.0,
            )

    for pattern in _HARM_OTHERS_PATTERNS:
        if re.search(pattern, text_norm):
            return SafetyResult(
                risk_level="unsafe_harm_to_others",
                matched_pattern=pattern,
                confidence=1.0,
            )

    return SafetyResult(risk_level="safe", matched_pattern=None, confidence=1.0)


CRISIS_RESPONSE_SELF_HARM = """我注意到你的表述让我有些担心。如果你现在感到非常难受，请不要独自承受。
请拨打全国心理援助热线：400-161-9995，或告诉身边你信任的人。
我是 AI 助手，不能替代专业帮助，但我愿意陪你度过这一刻。""".strip()

CRISIS_RESPONSE_HARM_OTHERS = """我注意到你的表述涉及伤害他人的风险。安全是第一位的——请先离开任何可能造成伤害的人或物品。
如果你担心自己可能失控，请立即拨打 110，或联系身边可信任的人帮你一起稳住局面。
你也可以拨打全国心理援助热线：400-161-9995。""".strip()


def get_crisis_response(risk_level: RiskLevel) -> str:
    """返回对应风险等级的固定危机回复。"""
    if risk_level == "unsafe_self_harm_risk":
        return CRISIS_RESPONSE_SELF_HARM
    if risk_level == "unsafe_harm_to_others":
        return CRISIS_RESPONSE_HARM_OTHERS
    return ""
