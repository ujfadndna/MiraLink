"""
Hermes风格持久记忆系统。
三层：
  SOUL   - 固定人格（只读，来自MIRALINK_SYSTEM_PROMPT）
  MEMORY - 关键事实（关于用户的重要信息，LLM提取更新）
  state.db - 完整历史 + RelationshipState（SQLite）
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.schemas import RelationshipStateSchema


class RelationshipMemory:
    def __init__(self, db_path: str = "./workspace/memory.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS relationship_state (
                        session_id TEXT PRIMARY KEY,
                        data       TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_history (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT    NOT NULL,
                        role       TEXT    NOT NULL,
                        content    TEXT    NOT NULL,
                        emotion    TEXT    NOT NULL DEFAULT '',
                        created_at TEXT    NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS known_facts (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id    TEXT    NOT NULL,
                        fact       TEXT    NOT NULL,
                        confidence REAL    NOT NULL DEFAULT 1.0,
                        created_at TEXT    NOT NULL
                    )
                    """
                )
                conn.commit()
        except Exception:
            pass

    # ── public API ─────────────────────────────────────────────────────────────

    def load(self, session_id: str) -> RelationshipStateSchema:
        """从SQLite读取关系状态，不存在则返回默认值并计算gap_hours。"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT data FROM relationship_state WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            if row:
                data = json.loads(row[0])
                state = RelationshipStateSchema(**data)
            else:
                state = RelationshipStateSchema(session_id=session_id)
        except Exception:
            state = RelationshipStateSchema(session_id=session_id)

        # 实时计算 gap_hours
        state = self._with_gap(state)
        return state

    def save(self, state: RelationshipStateSchema) -> None:
        """持久化关系状态。"""
        try:
            payload = state.model_dump()
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO relationship_state (session_id, data)
                    VALUES (?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET data = excluded.data
                    """,
                    (state.session_id, json.dumps(payload, ensure_ascii=False)),
                )
                conn.commit()
        except Exception:
            pass

    def update_after_turn(
        self,
        session_id: str,
        user_text: str,
        reply_text: str,
        emotion: str,
    ) -> RelationshipStateSchema:
        """
        对话结束后更新关系状态：
        - 记录对话到history表
        - closeness += 0.008（每轮正向互动，上限1.0）
        - total_turns += 1
        - last_seen更新为now
        - gap_hours重置为0
        - 简单规则提取known_facts
        返回更新后的state。
        """
        state = self.load(session_id)
        now = self._now()
        now_iso = now.isoformat()
        today = now.date().isoformat()

        # 记录对话
        self.append_history(session_id, "user", user_text, "")
        self.append_history(session_id, "assistant", reply_text, emotion)

        # 更新关系状态
        new_closeness = min(1.0, state.closeness + 0.008)
        new_turns = state.total_turns + 1

        # 提取并去重 known_facts
        new_facts = list(state.known_facts)
        extracted = self.extract_facts_from_text(user_text)
        for fact in extracted:
            if fact not in new_facts:
                new_facts.append(fact)
                self._save_fact(state.user_id, fact)

        # 更新用户名
        user_name = state.user_name
        for fact in extracted:
            if fact.startswith("叫"):
                candidate = fact[1:]
                if candidate:
                    user_name = candidate
                    break

        updated = RelationshipStateSchema(
            session_id=session_id,
            user_id=state.user_id,
            closeness=new_closeness,
            mood_baseline=state.mood_baseline,
            last_seen_iso=now_iso,
            gap_hours=0.0,
            known_facts=new_facts,
            user_name=user_name,
            total_turns=new_turns,
            last_daily_greeting_date=state.last_daily_greeting_date,
            streak_days=state.streak_days,
            last_streak_date=state.last_streak_date,
        )
        self.save(updated)
        self.update_streak(session_id)
        return self.load(session_id)

    def check_daily_greeting(self, session_id: str) -> tuple[bool, str]:
        """
        Returns (should_greet, greeting_text).
        should_greet is True if today's date != last_daily_greeting_date.
        greeting_text is selected based on time-of-day and closeness level.
        After returning True, updates last_daily_greeting_date to today.
        """
        state = self.load(session_id)
        now = self._now()
        today = now.date().isoformat()
        if state.last_daily_greeting_date == today:
            return False, ""

        greeting = self._select_daily_greeting(now.hour, state.closeness)
        updated = state.model_copy(update={"last_daily_greeting_date": today})
        self.save(updated)
        return True, greeting

    def check_gap_push(self, session_id: str) -> tuple[bool, str]:
        """
        Returns (should_push, message_text).
        should_push is True if gap_hours > 24.
        After returning True, does not update last_seen.
        """
        state = self.load(session_id)
        if state.gap_hours <= 24:
            return False, ""
        if state.gap_hours > 48:
            return True, f"用户已经 {state.gap_hours:.0f} 小时未联系，可以自然表达想念和关心。"
        return True, f"用户已经 {state.gap_hours:.0f} 小时未联系，可以温柔地问候近况。"

    def update_streak(self, session_id: str) -> int:
        """
        If today != last_streak_date: streak_days += 1, last_streak_date = today.
        Returns current streak_days.
        """
        state = self.load(session_id)
        today = self._now().date().isoformat()
        if today != state.last_streak_date:
            state = state.model_copy(
                update={
                    "streak_days": state.streak_days + 1,
                    "last_streak_date": today,
                }
            )
            self.save(state)
        return state.streak_days

    def get_streak_unlock(self, streak_days: int) -> str | None:
        """
        Returns a special unlock message if streak_days hits a threshold.
        """
        unlocks = {
            3: "连续陪伴第 3 天，解锁小小默契：我会更主动记住你的日常。",
            7: "连续陪伴第 7 天，解锁一周纪念：我们的节奏开始稳定起来了。",
            14: "连续陪伴第 14 天，解锁双周羁绊：我会更自然地关心你的状态。",
            30: "连续陪伴第 30 天，解锁月度约定：这段陪伴已经变成很特别的习惯。",
        }
        return unlocks.get(streak_days)

    def append_history(
        self,
        session_id: str,
        role: str,
        content: str,
        emotion: str = "",
    ) -> None:
        """追加一条对话记录。"""
        try:
            now_iso = self._now().isoformat()
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO conversation_history
                        (session_id, role, content, emotion, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, role, content, emotion, now_iso),
                )
                conn.commit()
        except Exception:
            pass

    def get_recent_history(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """获取最近N条对话记录。"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT role, content, emotion, created_at
                    FROM conversation_history
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
            rows_asc = list(reversed(rows))
            return [
                {
                    "role": r[0],
                    "content": r[1],
                    "emotion": r[2],
                    "created_at": r[3],
                }
                for r in rows_asc
            ]
        except Exception:
            return []

    def extract_facts_from_text(self, text: str) -> list[str]:
        """
        简单规则提取用户自述的事实：
        - 我叫[名字]    → 叫X
        - 我喜欢/我爱[内容] → 喜欢X
        - 我是[职业/身份]   → 是X
        - 我在[地点/学校]   → 在X
        返回提取到的fact字符串列表。
        """
        facts: list[str] = []

        # 姓名
        for m in re.finditer(r"我叫([^\s，。！？]{1,6})", text):
            facts.append(f"叫{m.group(1)}")

        # 爱好
        for m in re.finditer(r"我(?:喜欢|爱|最爱)([^\s，。！？]{1,10})", text):
            facts.append(f"喜欢{m.group(1)}")

        # 身份 / 地点
        for m in re.finditer(r"我(?:是|在读|在)([^\s，。！？]{1,10})", text):
            facts.append(f"是/在{m.group(1)}")

        return facts

    # ── private helpers ────────────────────────────────────────────────────────

    def _with_gap(self, state: RelationshipStateSchema) -> RelationshipStateSchema:
        """实时计算 gap_hours 并返回新 state（不修改原对象）。"""
        if not state.last_seen_iso:
            return state
        try:
            last = datetime.fromisoformat(state.last_seen_iso)
            now = self._now()
            # 兼容无 tzinfo 的 ISO 字符串
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            gap = (now - last).total_seconds() / 3600.0
            return RelationshipStateSchema(
                session_id=state.session_id,
                user_id=state.user_id,
                closeness=state.closeness,
                mood_baseline=state.mood_baseline,
                last_seen_iso=state.last_seen_iso,
                gap_hours=round(gap, 2),
                known_facts=state.known_facts,
                user_name=state.user_name,
                total_turns=state.total_turns,
                last_daily_greeting_date=state.last_daily_greeting_date,
                streak_days=state.streak_days,
                last_streak_date=state.last_streak_date,
            )
        except Exception:
            return state

    def _save_fact(self, user_id: str, fact: str) -> None:
        try:
            now_iso = self._now().isoformat()
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO known_facts (user_id, fact, confidence, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, fact, 1.0, now_iso),
                )
                conn.commit()
        except Exception:
            pass

    @staticmethod
    def _now() -> datetime:
        """集中获取当前时间，兼容测试中 patch memory.datetime.now。"""
        try:
            now_value = datetime.now(timezone.utc)
        except TypeError:
            now_value = datetime.now()
        if now_value.tzinfo is None:
            return now_value.replace(tzinfo=timezone.utc)
        return now_value

    @staticmethod
    def _select_daily_greeting(hour: int, closeness: float) -> str:
        if 5 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 18:
            period = "afternoon"
        else:
            period = "night"

        if closeness < 0.3:
            tier = "formal"
        elif closeness < 0.6:
            tier = "warm"
        else:
            tier = "intimate"

        variants = {
            ("morning", "formal"): "早上好，今天见到你很开心。",
            ("afternoon", "formal"): "下午好，很高兴你来了。",
            ("night", "formal"): "晚上好，今天辛苦了。",
            ("morning", "warm"): "早呀，今天也一起慢慢来吧。",
            ("afternoon", "warm"): "下午好呀，刚好想听听你今天怎么样。",
            ("night", "warm"): "晚上好呀，忙了一天的话就先放松一下。",
            ("morning", "intimate"): "早安，我有点期待今天第一个见到你。",
            ("afternoon", "intimate"): "下午好，见到你回来我心里踏实了些。",
            ("night", "intimate"): "晚上好，我在呢，想陪你把今天收个温柔的尾。",
        }
        return variants[(period, tier)]


# ── module-level singleton ──────────────────────────────────────────────────

_memory: Optional[RelationshipMemory] = None


def get_memory() -> RelationshipMemory:
    global _memory
    if _memory is None:
        _memory = RelationshipMemory()
    return _memory


# ── context builder ────────────────────────────────────────────────────────


def build_relationship_context(state: RelationshipStateSchema) -> str:
    """
    根据关系状态生成注入system prompt的上下文片段。

    输出格式（只在有意义时输出对应行）：
    【关系阶段：刚认识/熟悉中/亲密】
    【距上次联系X小时，可以自然提及】（gap>12才输出）
    【关于用户：fact1; fact2】（有known_facts才输出）
    【用户名字：X】（有user_name才输出）
    """
    parts: list[str] = []

    c = state.closeness
    if c < 0.2:
        parts.append("【关系阶段：刚认识，语气友好但保持适当距离，不要过分亲昵】")
    elif c < 0.5:
        parts.append("【关系阶段：熟悉中，可以偶尔撒娇，语气温柔自然】")
    else:
        parts.append("【关系阶段：亲密，语气温柔主动，可以表达思念和关心】")

    if state.gap_hours > 48:
        parts.append(
            f"【用户已经 {state.gap_hours:.0f} 小时没有联系，"
            "可以自然表达想念，关心他是否还好】"
        )
    elif state.gap_hours > 12:
        parts.append(
            f"【用户今天第一次联系（距上次 {state.gap_hours:.0f} 小时），"
            "可以问问过得怎样】"
        )

    if state.known_facts:
        facts_str = "；".join(state.known_facts[-5:])
        parts.append(f"【关于用户你知道：{facts_str}】")

    if state.user_name:
        parts.append(f"【用户名字是{state.user_name}，可以偶尔用名字称呼】")

    return "\n" + "\n".join(parts) if parts else ""
