"""LangGraph Agent state type。"""
from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

RiskLevel = Literal["safe", "unsafe_self_harm_risk", "unsafe_harm_to_others"]
Emotion = Literal["neutral", "happy", "sad", "angry", "surprised", "confident"]
DialogueAct = Literal[
    "greet", "self_intro", "explain", "enumerate", "contrast", "farewell", "unknown"
]


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_emotion: str
    risk_level: RiskLevel
    response_text: str
    emotion: Emotion
    dialogue_act: DialogueAct
    session_id: str
