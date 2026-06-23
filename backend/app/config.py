"""HerUnity 后端配置。"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 工作区
    workspace_dir: Path = Path("./workspace")

    # TTS 后端选择：mock | indextts | cloud
    tts_backend: str = "mock"
    tts_sample_rate: int = 24000

    # Agent 后端选择：mock | langgraph | cloud
    agent_backend: str = "mock"

    # OpenAI hosted web search：默认 mock，避免无 key 时影响 JD Demo 主链路
    web_search_backend: str = "mock"
    web_search_model: str = "gpt-5.5"
    web_search_context_size: str = "low"
    web_search_external_web_access: bool = True
    web_search_timeout_sec: float = 12.0
    openai_api_key: str = ""
    openai_base_url: str = ""

    # IndexTTS2（云端运行时配置）
    indextts_api_url: str = ""
    indextts_http_timeout_sec: float = 240.0
    default_speaker_wav: Path = Path("./reference_voice.wav")

    # Server
    server_port: int = 8100

    # WebSocket
    ws_chunk_duration_ms: int = 80  # 每个 audio chunk 的时长
    ws_animation_fps: int = 60  # animation packet 帧率
    call_barge_in_enabled: bool = False
    call_avatar_wait_sec: float = 8.0
    avatar_auto_start_session_sec: float = 0.5
    call_reply_max_chars: int = 56
    agent_response_timeout_sec: float = 30.0
    tts_turn_timeout_sec: float = 45.0
    call_tts_turn_timeout_sec: float = 45.0

    # ASR 后端选择：mock | faster_whisper | cloud_whisper
    asr_backend: str = "mock"
    asr_model: str = "large-v3"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    cloud_asr_api_url: str = ""

    # Viseme
    viseme_smooth_window_ms: int = 40  # coarticulation 平滑窗口

    # Warmup
    warmup_on_start: bool = True
    warmup_text: str = "你好"
    warmup_timeout_sec: float = 60.0
    warmup_tts: bool = True
    warmup_asr: bool = True
    warmup_agent: bool = False


settings = Settings()
