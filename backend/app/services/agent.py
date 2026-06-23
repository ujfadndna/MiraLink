"""Agent 对话服务。MockAgent（规则兜底）+ LangGraphAgent（LLM 驱动）。

当 LLM API key 不可用时自动退化为 MockAgent。
"""
from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from app.agent.config import agent_settings
from app.agent.prompts import (
    CLASSIFY_PROMPT,
    HERUNITY_SYSTEM_PROMPT,
    IDENTITY_DISCLOSURE,
    PERCEIVE_PROMPT,
)
from app.agent.safety import check_safety, get_crisis_response
from app.schemas import AgentResponse
from app.services.base import get_backend, register

# ── MockAgent 规则表 ───────────────────────────────────────

_RULES: list[tuple[str, str, str, str]] = [
    (r"你好|嗨|hello|hi|hey", "你好！很高兴见到你 😊", "happy", "greet"),
    (r"再见|拜拜|bye|下次见", "再见！下次再聊~", "sad", "farewell"),
    (r"你是谁|你叫什么|你的名字", "我是 HerUnity 数字人，一个基于 Unity 3D 的实时虚拟形象助手。我能用语音和你对话，还能根据情绪做出不同的表情哦。", "neutral", "self_intro"),
    (r"介绍一下你自己|你是什么", "我是 HerUnity 数字人，结合了语音合成、口型同步和情绪表情技术。我的核心创新是 SPCG 语义-韵律耦合行为规划算法，能让数字人的手势、表情和语音在时间轴上精确对齐。", "confident", "explain"),
    (r"你的.*创新|算法.*创新|核心.*创新", "我的核心创新是 SPCG 语义-韵律耦合行为规划。它把文本语义、语音韵律和 Unity 动画约束联合建模，让数字人的表情和手势不再随机，而是精准对齐到语义重点和语音重音上。", "confident", "explain"),
    (r"你能做什么|功能|能力", "我能实时对话、展示口型同步、根据情绪改变表情，还能做语义手势。未来我还会学会看向物体、指向目标和更自然的身体动作。", "happy", "explain"),
    (r"开心|高兴|快乐|哈哈", "太好了！看到你开心我也很开心~", "happy", "greet"),
    (r"难过|伤心|不开心|郁闷", "别难过，我会一直在这里陪着你。要不要和我说说发生了什么？", "sad", "greet"),
    (r"生气|愤怒|讨厌", "我理解你的感受。深呼吸，放松一下，没什么大不了的。", "neutral", "greet"),
    (r"惊讶|哇|天哪|不会吧", "世界总是充满惊喜，对吧？", "surprised", "greet"),
    (r"谢谢|感谢|thanks|thank", "不客气！能帮到你我很快乐~", "happy", "greet"),
    (r"第一|第二|第三|首先|其次|最后", "你说得很有条理。在技术实现上，我们也分三个阶段：第一，语义锚点提取；第二，韵律特征计算；第三，约束感知动作合成。", "neutral", "enumerate"),
    (r"但是|然而|相比之下|不是.*而是", "你说得对，这里有一个重要对比。传统方案手势随机，而我们的 SPCG 让每个动作都和语义、韵律精确对齐。", "confident", "contrast"),
    (r"帮我|请.*解释|什么是", "好的，让我来解释一下。这项技术的核心是把多个维度的信息——文字的含义、语音的节奏、情绪的状态——统一到一个时间轴上，生成自然协调的数字人行为。", "neutral", "explain"),
]

_FALLBACKS: list[tuple[str, str, str]] = [
    ("neutral", "嗯，我理解了。你可以继续说具体一点，我会尽量直接回应。", "unknown"),
    ("neutral", "这个问题可以从实际需求出发看：先明确目标，再拆成几个可执行的小步骤。", "explain"),
    ("neutral", "我没有实时联网信息，所以新闻、天气、价格这类动态内容可能不准；但我可以帮你做一般分析和思路整理。", "unknown"),
]


# ── Base ───────────────────────────────────────────────────


class AgentBackend(ABC):
    """Agent 后端基类。"""

    @abstractmethod
    async def generate(self, user_text: str, session_id: str) -> AgentResponse:
        """根据用户输入生成回复。"""
        ...

    @abstractmethod
    async def generate_stream(self, user_text: str, session_id: str):
        """流式生成。yield AgentStreamEvent。(默认实现回退到 generate)"""
        ...
        yield


# ── MockAgent ──────────────────────────────────────────────


@register("agent", "mock")
class MockAgent(AgentBackend):
    """基于规则的 Mock Agent。支持多轮记忆。"""

    def __init__(self) -> None:
        self._history: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self._turn_counters: dict[str, int] = defaultdict(int)

    async def generate(self, user_text: str, session_id: str) -> AgentResponse:
        history = self._history[session_id]
        turn = self._turn_counters[session_id]
        self._turn_counters[session_id] = turn + 1

        text = user_text.strip().lower()
        for pattern, reply, emotion, dialogue_act in _RULES:
            if re.search(pattern, text):
                history.append((user_text, reply))
                if len(history) > 20:
                    history.pop(0)
                response = AgentResponse(
                    reply_text=reply,
                    emotion=emotion,
                    dialogue_act=dialogue_act,
                )
                try:
                    from app.services.memory import get_memory

                    get_memory().update_after_turn(session_id, user_text, response.reply_text, response.emotion)
                except Exception:
                    pass
                return response

        idx = turn % len(_FALLBACKS)
        emotion, reply, dialogue_act = _FALLBACKS[idx]
        history.append((user_text, reply))
        if len(history) > 20:
            history.pop(0)

        response = AgentResponse(
            reply_text=reply,
            emotion=emotion,
            dialogue_act=dialogue_act,
        )
        try:
            from app.services.memory import get_memory

            get_memory().update_after_turn(session_id, user_text, response.reply_text, response.emotion)
        except Exception:
            pass
        return response

    async def generate_stream(self, user_text: str, session_id: str):
        from app.schemas import AgentStreamEvent

        result = await self.generate(user_text, session_id)
        yield AgentStreamEvent(
            token=result.reply_text,
            accumulated_text=result.reply_text,
            emotion=result.emotion,
            dialogue_act=result.dialogue_act,
            is_final=True,
        )

    def get_history(self, session_id: str) -> list[tuple[str, str]]:
        return list(self._history.get(session_id, []))

    def clear_session(self, session_id: str) -> None:
        self._history.pop(session_id, None)
        self._turn_counters.pop(session_id, None)


# ── LangGraphAgent ─────────────────────────────────────────


@register("agent", "langgraph")
class LangGraphAgent(AgentBackend):
    """基于 LangGraph 的 LLM Agent。支持情绪感知、安全检测和多轮对话。"""

    def __init__(self) -> None:
        self._graph: Any = None
        self._checkpointer: Any = None
        self._llm: Any = None
        self._history: dict[str, list] = defaultdict(list)
        self._first_turn: set[str] = set()

    # ── LLM ────────────────────────────────────────────

    def _ensure_llm(self) -> Any:
        if self._llm is not None:
            return self._llm

        from langchain_anthropic import ChatAnthropic
        from langchain_openai import ChatOpenAI

        provider = agent_settings.get_llm_provider().strip().lower()
        # Read directly from env — pydantic_settings env_file may fail in daemon contexts
        import os
        key_map = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}
        api_key = agent_settings.agent_llm_api_key or os.getenv(key_map.get(provider, ""))
        if not api_key:
            raise RuntimeError(
                f"No API key found for {provider}. "
                f"Set ANTHROPIC_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY env var."
            )

        model = agent_settings.agent_llm_model
        temperature = agent_settings.agent_llm_temperature
        base_url = agent_settings.agent_llm_base_url or os.getenv(
            {"anthropic": "ANTHROPIC_BASE_URL", "deepseek": "DEEPSEEK_BASE_URL", "openai": "OPENAI_BASE_URL"}.get(provider, "")
        ) or None

        if provider == "anthropic":
            kwargs: dict[str, Any] = {
                "model": model,
                "temperature": temperature,
                "api_key": api_key,
            }
            if base_url:
                kwargs["anthropic_api_url"] = base_url
            self._llm = ChatAnthropic(**kwargs)
        elif provider in ("openai", "deepseek"):
            if provider == "deepseek" and not base_url:
                base_url = "https://api.deepseek.com"
            kwargs: dict[str, Any] = {"model": model, "temperature": temperature}
            if base_url:
                kwargs["base_url"] = base_url
            if api_key:
                kwargs["api_key"] = api_key
            self._llm = ChatOpenAI(**kwargs)
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

        return self._llm

    # ── Graph Construction ──────────────────────────────

    def _ensure_graph(self) -> Any:
        if self._graph is not None:
            return self._graph

        from app.agent.state import AgentState
        from langgraph.graph import END, StateGraph

        graph = StateGraph(AgentState)

        graph.add_node("perceive", self._node_perceive)
        graph.add_node("safety_check", self._node_safety)
        graph.add_node("crisis_response", self._node_crisis)
        graph.add_node("think", self._node_think)
        graph.add_node("classify", self._node_classify)
        graph.add_node("render", self._node_render)

        graph.set_entry_point("perceive")
        graph.add_edge("perceive", "safety_check")
        graph.add_conditional_edges(
            "safety_check",
            self._route_after_safety,
            {
                "crisis_response": "crisis_response",
                "think": "think",
            },
        )
        graph.add_edge("crisis_response", END)
        graph.add_edge("think", "classify")
        graph.add_edge("classify", "render")
        graph.add_edge("render", END)

        # 用内存 checkpointer（无 SQLite 也能跑）
        from langgraph.checkpoint.memory import MemorySaver

        self._checkpointer = MemorySaver()
        self._graph = graph.compile(checkpointer=self._checkpointer)
        return self._graph

    # ── Nodes ───────────────────────────────────────────

    async def _node_perceive(self, state: dict[str, Any]) -> dict[str, str]:
        """识别用户情绪。"""
        from langchain_core.messages import HumanMessage

        user_text = self._latest_human_text(state)
        llm = self._ensure_llm()
        prompt = PERCEIVE_PROMPT.format(user_input=user_text)
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        emotion = self._extract_first_line(self._content(response))
        return {"user_emotion": emotion or "neutral"}

    def _node_safety(self, state: dict[str, Any]) -> dict[str, str]:
        """安全检测。"""
        result = check_safety(self._latest_human_text(state))
        return {"risk_level": result.risk_level}

    def _node_crisis(self, state: dict[str, Any]) -> dict[str, str]:
        """危机干预固定回复。"""
        return {
            "response_text": get_crisis_response(state["risk_level"]),
            "emotion": "sad",
            "dialogue_act": "unknown",
        }

    async def _node_think(self, state: dict[str, Any]) -> dict[str, str]:
        """LLM 生成回复。"""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        today = datetime.now().date().isoformat()
        system_prompt = HERUNITY_SYSTEM_PROMPT.format(date=today)

        # 首次对话加身份披露
        session_id = state.get("session_id", "")
        is_first = session_id not in self._first_turn
        if is_first:
            self._first_turn.add(session_id)
            system_prompt = f"{system_prompt}\n\n[首次对话，请在回复前加上以下身份说明：{IDENTITY_DISCLOSURE}]"
        try:
            from app.services.memory import build_relationship_context, get_memory

            state_rel = get_memory().load(session_id)
            system_prompt = system_prompt + build_relationship_context(state_rel)
        except Exception:
            pass

        messages: list[Any] = [SystemMessage(content=system_prompt)]
        # 最近 20 轮对话历史
        history = self._history.get(session_id, [])
        for h in history[-20:]:
            messages.append(HumanMessage(content=h["user"]))
            if h.get("assistant"):
                messages.append(AIMessage(content=h["assistant"]))

        # 当前用户输入
        messages.append(HumanMessage(content=self._latest_human_text(state)))

        llm = self._ensure_llm()
        response = await llm.ainvoke(messages)
        return {"response_text": self._content(response).strip()}

    async def _node_classify(self, state: dict[str, Any]) -> dict[str, str]:
        """从回复中提取情绪和对话行为标签。"""
        reply = state.get("response_text", "")

        # 先尝试从 LLM 输出末尾解析 [EMOTION: xxx] [ACT: xxx]
        emotion = ""
        dialogue_act = ""
        em_match = re.search(r"\[EMOTION:\s*(\w+)\]", reply, re.IGNORECASE)
        act_match = re.search(r"\[ACT:\s*(\w+)\]", reply, re.IGNORECASE)

        if em_match and act_match:
            emotion = em_match.group(1).lower()
            dialogue_act = act_match.group(1).lower()
            # 从回复中去除标签
            clean_reply = re.sub(r"\s*\[EMOTION:\s*\w+\]\s*", "", reply)
            clean_reply = re.sub(r"\s*\[ACT:\s*\w+\]\s*", "", clean_reply)
            state["response_text"] = clean_reply.strip()
        else:
            # LLM 没有输出标签，用小 LLM 调用分类
            try:
                from langchain_core.messages import HumanMessage

                prompt = CLASSIFY_PROMPT.format(reply=reply)
                llm = self._ensure_llm()
                result = await llm.ainvoke([HumanMessage(content=prompt)])
                lines = self._content(result).strip().splitlines()
                for line in lines:
                    if line.upper().startswith("EMOTION:"):
                        emotion = line.split(":", 1)[1].strip().lower()
                    elif line.upper().startswith("ACT:"):
                        dialogue_act = line.split(":", 1)[1].strip().lower()
            except Exception:
                pass

        return {
            "emotion": emotion or "neutral",
            "dialogue_act": dialogue_act or "unknown",
            "response_text": state["response_text"],
        }

    def _node_render(self, state: dict[str, Any]) -> dict[str, list]:
        """记录回复到历史。"""
        from langchain_core.messages import AIMessage

        return {"messages": [AIMessage(content=state["response_text"])]}

    def _route_after_safety(self, state: dict[str, Any]) -> str:
        if state["risk_level"] != "safe":
            return "crisis_response"
        return "think"

    # ── Public API ──────────────────────────────────────

    async def generate(self, user_text: str, session_id: str) -> AgentResponse:
        """异步生成回复——直接运行 LangGraph workflow。"""
        result = await self._run_graph(user_text, session_id)

        # 保存到历史
        history = self._history[session_id]
        history.append({"user": user_text, "assistant": result.reply_text})
        if len(history) > 40:
            history.pop(0)

        try:
            from app.services.memory import get_memory

            get_memory().update_after_turn(session_id, user_text, result.reply_text, result.emotion)
        except Exception:
            pass

        return result

    async def generate_stream(self, user_text: str, session_id: str):
        """流式生成：调用 LLM astream，逐个 yield token。"""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from app.schemas import AgentStreamEvent

        today = datetime.now().date().isoformat()
        system_prompt = HERUNITY_SYSTEM_PROMPT.format(date=today)

        # 首次对话加身份披露
        is_first = session_id not in self._first_turn
        if is_first:
            self._first_turn.add(session_id)
            system_prompt = f"{system_prompt}\n\n[首次对话，请在回复前加上以下身份说明：{IDENTITY_DISCLOSURE}]"

        try:
            from app.services.memory import build_relationship_context, get_memory

            state_rel = get_memory().load(session_id)
            system_prompt = system_prompt + build_relationship_context(state_rel)
        except Exception:
            pass

        messages: list[Any] = [SystemMessage(content=system_prompt)]
        history = self._history.get(session_id, [])
        for h in history[-20:]:
            messages.append(HumanMessage(content=h["user"]))
            if h.get("assistant"):
                messages.append(AIMessage(content=h["assistant"]))
        messages.append(HumanMessage(content=user_text))

        llm = self._ensure_llm()
        full_text = ""
        async for chunk in llm.astream(messages):
            token = chunk.content if hasattr(chunk, 'content') else str(chunk)
            full_text += token
            yield AgentStreamEvent(
                token=token,
                accumulated_text=full_text,
                is_final=False,
            )

        # Safety check
        safety = check_safety(user_text)
        if safety.risk_level == "crisis":
            full_text = get_crisis_response(safety.risk_level)

        # Parse emotion/act tags from full text
        emotion = "neutral"
        dialogue_act = "unknown"
        em_match = re.search(r"\[EMOTION:\s*(\w+)\]", full_text, re.IGNORECASE)
        act_match = re.search(r"\[ACT:\s*(\w+)\]", full_text, re.IGNORECASE)
        if em_match:
            emotion = em_match.group(1).lower()
        if act_match:
            dialogue_act = act_match.group(1).lower()
        clean_text = re.sub(r"\s*\[EMOTION:\s*\w+\]\s*", "", full_text)
        clean_text = re.sub(r"\s*\[ACT:\s*\w+\]\s*", "", clean_text).strip()

        # Save to history
        if session_id not in self._history:
            self._history[session_id] = []
        self._history[session_id].append({"user": user_text, "assistant": clean_text})
        if len(self._history[session_id]) > 40:
            self._history[session_id] = self._history[session_id][-40:]

        try:
            from app.services.memory import get_memory

            get_memory().update_after_turn(session_id, user_text, clean_text, emotion)
        except Exception:
            pass

        yield AgentStreamEvent(
            token="",
            accumulated_text=clean_text,
            emotion=emotion,
            dialogue_act=dialogue_act,
            is_final=True,
        )

    async def _run_graph(self, user_text: str, session_id: str) -> AgentResponse:
        """运行 LangGraph workflow。"""
        from langchain_core.messages import HumanMessage

        graph = self._ensure_graph()
        config = {"configurable": {"thread_id": session_id}}

        # 初始输入
        initial_state: dict[str, Any] = {
            "messages": [HumanMessage(content=user_text)],
            "session_id": session_id,
        }

        final_state = await graph.ainvoke(initial_state, config)

        return AgentResponse(
            reply_text=final_state.get("response_text", ""),
            emotion=final_state.get("emotion", "neutral"),
            dialogue_act=final_state.get("dialogue_act", "unknown"),
        )

    def get_history(self, session_id: str) -> list[tuple[str, str]]:
        history = self._history.get(session_id, [])
        return [(h["user"], h.get("assistant", "")) for h in history]

    def clear_session(self, session_id: str) -> None:
        self._history.pop(session_id, None)
        self._first_turn.discard(session_id)

    # ── Helpers ─────────────────────────────────────────

    @staticmethod
    def _latest_human_text(state: dict[str, Any]) -> str:
        from langchain_core.messages import HumanMessage

        messages = state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                content = msg.content
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return " ".join(
                        item.get("text", "") if isinstance(item, dict) else str(item)
                        for item in content
                    )
                return str(content)
        return ""

    @staticmethod
    def _content(msg: Any) -> str:
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            return content
        if content is None:
            return ""
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(str(item.get("text", item.get("content", ""))))
                else:
                    parts.append(str(item))
            return " ".join(parts)
        return str(content)

    @staticmethod
    def _extract_first_line(text: str) -> str:
        if not text:
            return ""
        return text.strip().splitlines()[0].strip(" ,。，.")


# ── Agent Factory ─────────────────────────────────────────


_AGENT_INSTANCES: dict[str, AgentBackend] = {}


def _has_llm_keys() -> bool:
    """检查是否有任何 LLM API key 可用。"""
    return bool(
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
    )


def get_agent(backend: Optional[str] = None) -> AgentBackend:
    """获取 Agent 后端单例。

    优先使用真实 LLM agent（langgraph），API key 不可用时退化为 MockAgent。
    """
    from app.config import settings

    backend = backend or settings.agent_backend

    # 自动检测：如果选了 mock 但有 key，升级为 langgraph
    if backend == "mock" and _has_llm_keys():
        backend = "langgraph"

    if backend not in _AGENT_INSTANCES:
        try:
            cls = get_backend("agent", backend)
            _AGENT_INSTANCES[backend] = cls()
        except Exception:
            # langgraph 不可用（缺少依赖或 key）→ 退化为 mock
            cls = get_backend("agent", "mock")
            _AGENT_INSTANCES[backend] = cls()

    return _AGENT_INSTANCES[backend]
