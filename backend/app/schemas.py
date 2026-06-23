"""数据契约。TTS + Agent + Session + WebSocket 消息的 schema。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── TTS ────────────────────────────────────────────────────


class PhonemeInterval(BaseModel):
    phoneme: str
    start_ms: float
    end_ms: float


class SynthesizeRequest(BaseModel):
    text: str
    language: str = "zh"
    speaker_id: Optional[str] = None
    emotion: str = "neutral"
    speed: float = 1.0


class AudioWithTimestamps(BaseModel):
    audio_id: str
    audio_path: str
    duration_ms: float
    sample_rate: int
    phoneme_intervals: list[PhonemeInterval] = Field(default_factory=list)
    phoneme_fallback: bool = False


# ── Viseme ─────────────────────────────────────────────────


class BlendshapeFrame(BaseModel):
    start_ms: float
    end_ms: float
    weights: dict[str, float]  # blendshape_name → weight [0,1]


class VisemeCurve(BaseModel):
    frames: list[BlendshapeFrame] = Field(default_factory=list)
    duration_ms: float = 0.0


# ── Gesture ────────────────────────────────────────────────

class GestureEvent(BaseModel):
    gesture_name: str
    start_ms: float
    apex_ms: float
    duration_ms: float
    intensity: float
    anchor_type: str


# ── Agent ──────────────────────────────────────────────────


class AgentResponse(BaseModel):
    reply_text: str
    emotion: str = "neutral"  # neutral, happy, sad, angry, surprised, confident
    dialogue_act: str = "unknown"  # greet, explain, self_intro, farewell, enumerate, contrast, avatar_action, unknown
    avatar_action: Optional["AvatarInteractionCommand"] = None


class AgentStreamEvent(BaseModel):
    """流式输出中的单个 token 事件。"""
    token: str
    accumulated_text: str = ""
    emotion: str = "neutral"
    dialogue_act: str = "unknown"
    is_final: bool = False


# ── Session ────────────────────────────────────────────────

class TurnRecord(BaseModel):
    turn_id: str
    user_text: str
    reply_text: str
    emotion: str
    dialogue_act: str
    created_at: str  # ISO timestamp


class SessionCreate(BaseModel):
    avatar_id: str = "default"
    language: str = "zh"


class SessionInfo(BaseModel):
    session_id: str
    avatar_id: str
    language: str
    status: str = "active"  # active, ended
    turn_count: int = 0
    turns: list[TurnRecord] = Field(default_factory=list)
    created_at: str = ""
    ended_at: Optional[str] = None


# ── WebSocket Messages ─────────────────────────────────────

# Client → Server

class SessionStart(BaseModel):
    type: str = "session.start"
    avatar_id: str = "default"
    language: str = "zh"


class TurnSubmitText(BaseModel):
    type: str = "turn.submit_text"
    session_id: str = ""
    text: str


# Server → Client

class SessionStarted(BaseModel):
    type: str = "session.started"
    session_id: str


class TurnStart(BaseModel):
    type: str = "turn.start"
    turn_id: str
    emotion: str = "neutral"
    dialogue_act: str = "unknown"
    gesture_events: list[GestureEvent] = Field(default_factory=list)
    duration_ms: Optional[float] = None
    sample_rate: Optional[int] = None
    total_samples: Optional[int] = None
    avatar_action: Optional["AvatarInteractionCommand"] = None


class AudioChunk(BaseModel):
    type: str = "audio.chunk"
    turn_id: str
    seq: int
    sample_rate: int
    base64: str  # base64 encoded PCM s16le


class AnimationPacket(BaseModel):
    type: str = "animation.packet"
    turn_id: str
    seq: int
    start_ms: float
    end_ms: float
    blendshapes: dict[str, float]


class TurnEnd(BaseModel):
    type: str = "turn.end"
    turn_id: str


class StateChange(BaseModel):
    type: str = "state.change"
    state: str  # idle, listening, thinking, speaking, interrupted, error
    detail: str = ""


class ErrorMessage(BaseModel):
    type: str = "error"
    message: str


class TurnSubmitAudio(BaseModel):
    type: str = "turn.submit_audio"
    session_id: str = ""
    base64: str
    sample_rate: int = 16000


class AsrResult(BaseModel):
    type: str = "asr.result"
    text: str


# ── Hosted Web Search ─────────────────────────────────────

class WebSearchRequest(BaseModel):
    query: str
    max_sources: int = 5
    language: str = "zh"
    context_size: Optional[str] = None


class WebSearchSource(BaseModel):
    title: str = ""
    url: str
    snippet: str = ""


class WebSearchResult(BaseModel):
    query: str
    answer: str
    sources: list[WebSearchSource] = Field(default_factory=list)
    searched_at: str
    elapsed_ms: float
    provider: str
    model: str


# ── M6 Sensor ──────────────────────────────────────────────

class SensorEventValue(BaseModel):
    beta: Optional[float] = None          # 设备倾斜角
    gamma: Optional[float] = None
    alpha: Optional[float] = None
    accel_magnitude: Optional[float] = None
    net_magnitude: Optional[float] = None
    strength: Optional[float] = None
    confidence: float = 1.0
    touch_x: Optional[float] = None
    touch_y: Optional[float] = None
    dx: Optional[float] = None
    dy: Optional[float] = None
    duration_ms: Optional[float] = None
    direction: Optional[str] = None
    visual_zone: Optional[str] = None
    anatomical_zone: Optional[str] = None
    zone_basis: Optional[str] = None
    anchors_live: Optional[bool] = None
    simulated: Optional[bool] = None
    source: Optional[str] = None

class SensorEvent(BaseModel):
    type: str = "sensor.event"
    session_id: str
    event: str   # shake/tilt/tap/swipe/wave/reset plus M6 legacy events
    zone: Optional[str] = None
    value: SensorEventValue = Field(default_factory=SensorEventValue)
    timestamp_ms: int = 0

class SensorBind(BaseModel):
    type: str = "sensor.bind"
    session_id: str

class SensorReaction(BaseModel):
    type: str = "sensor.reaction"
    event: str
    reply_text: str
    emotion: str

class SensorAck(BaseModel):
    type: str = "sensor.ack"
    session_id: str
    event: str
    accepted: bool = True
    latency_ms: int = 0
    reason: str = ""
    retry_after_ms: int = 0

class AvatarInteractionCommand(BaseModel):
    state: str = "Reacting"
    emotion: str = "neutral"
    gesture: str = ""
    gaze_mode: str = ""
    pose_mode: str = ""
    sound_key: str = ""
    vfx_key: str = ""
    duration_sec: float = 0.9
    priority: int = 10
    interrupt_policy: str = "normal"

class SensorFeedback(BaseModel):
    type: str = "sensor.feedback"
    session_id: str
    event: str
    zone: Optional[str] = None
    value: SensorEventValue = Field(default_factory=SensorEventValue)
    timestamp_ms: int = 0
    received_ms: int = 0
    latency_ms: int = 0
    emotion: str = "neutral"
    jd_state: str = "Reacting"
    energy_delta: int = 0
    affinity_delta: int = 0
    score_delta: int = 0
    feedback_tags: list[str] = Field(default_factory=list)
    command: AvatarInteractionCommand = Field(default_factory=AvatarInteractionCommand)

# ── M7 Relationship ────────────────────────────────────────

class RelationshipStateSchema(BaseModel):
    session_id: str
    user_id: str = "default"
    closeness: float = 0.1           # 0-1，随正向互动增长
    mood_baseline: str = "neutral"   # neutral/happy/sad
    last_seen_iso: str = ""          # ISO时间戳
    gap_hours: float = 0.0           # 距上次互动小时数
    known_facts: list[str] = Field(default_factory=list)
    user_name: str = ""
    total_turns: int = 0
    last_daily_greeting_date: str = ""  # ISO日期 YYYY-MM-DD，上次每日问候日期
    streak_days: int = 0                # 连续互动天数
    last_streak_date: str = ""          # ISO日期 YYYY-MM-DD，上次计入连续天数日期


AgentResponse.model_rebuild()
TurnStart.model_rebuild()
