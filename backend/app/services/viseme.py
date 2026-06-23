"""Phoneme-to-viseme mapping for streaming mouth animation."""
from __future__ import annotations

import re
import unicodedata

from app.config import settings
from app.schemas import AudioWithTimestamps, BlendshapeFrame, VisemeCurve

try:
    from pypinyin import Style, pinyin
except Exception:  # pragma: no cover - dependency fallback for minimal environments
    Style = None  # type: ignore[assignment]
    pinyin = None  # type: ignore[assignment]

_MOUTH_CHANNELS = ("mouse_open", "lip_a", "lip_i", "lip_u", "lip_w", "lip_e", "lip_o")
_SILENCE_CHARS = set(" \t\r\n,.;:!?，。！？、；：…~《》〈〉（）()[]{}“”\"'—-")
_CHINESE_RE = re.compile(r"[\u3400-\u9fff]")
_COMMON_PINYIN = {
    "你": "ni",
    "好": "hao",
    "我": "wo",
    "不": "bu",
    "饿": "e",
    "的": "de",
    "是": "shi",
    "了": "le",
    "吗": "ma",
    "们": "men",
    "今": "jin",
    "天": "tian",
    "吃": "chi",
    "什": "shen",
    "么": "me",
    "大": "da",
    "小": "xiao",
    "开": "kai",
    "心": "xin",
}

_EXPLICIT_VISEMES: dict[str, dict[str, float]] = {
    "a": {"mouse_open": 0.52, "lip_a": 0.86},
    "aa": {"mouse_open": 0.52, "lip_a": 0.86},
    "i": {"mouse_open": 0.18, "lip_i": 0.82},
    "ih": {"mouse_open": 0.18, "lip_i": 0.82},
    "e": {"mouse_open": 0.28, "lip_e": 0.76},
    "ee": {"mouse_open": 0.28, "lip_e": 0.76},
    "o": {"mouse_open": 0.38, "lip_o": 0.82},
    "oh": {"mouse_open": 0.38, "lip_o": 0.82},
    "u": {"mouse_open": 0.20, "lip_u": 0.78},
    "ou": {"mouse_open": 0.20, "lip_u": 0.78},
    "m": {"mouse_open": 0.02, "lip_w": 0.70},
    "b": {"mouse_open": 0.04, "lip_w": 0.62},
    "p": {"mouse_open": 0.04, "lip_w": 0.62},
    "f": {"mouse_open": 0.08, "lip_w": 0.48},
    "v": {"mouse_open": 0.08, "lip_w": 0.48},
}

_A_FINALS = (
    "iang",
    "uang",
    "ang",
    "iao",
    "ian",
    "uan",
    "ai",
    "an",
    "ia",
    "ua",
    "ao",
    "a",
)
_I_FINALS = ("iong", "ing", "ian", "iao", "iu", "ie", "in", "ia", "i", "v", "ve", "vn", "ü", "üe", "ün")
_E_FINALS = ("eng", "ei", "en", "er", "ie", "ue", "ve", "e")
_O_FINALS = ("ong", "ou", "uo", "io", "o")
_U_FINALS = ("uang", "uai", "uan", "un", "ui", "ue", "uo", "ua", "u")
_CLOSED_INITIALS = ("m", "b", "p", "f")


def _zero_weights() -> dict[str, float]:
    return {channel: 0.0 for channel in _MOUTH_CHANNELS}


def _with_channels(weights: dict[str, float]) -> dict[str, float]:
    complete = _zero_weights()
    complete.update({key: max(0.0, min(1.0, float(value))) for key, value in weights.items()})
    return complete


_SILENCE_VISEME = _zero_weights()
_DEFAULT_VISEME = _with_channels({"mouse_open": 0.22, "lip_e": 0.30})


def _is_silence_token(token: str) -> bool:
    if not token:
        return True
    if all(ch in _SILENCE_CHARS or unicodedata.category(ch).startswith("P") for ch in token):
        return True
    return False


def _token_to_pinyin(token: str) -> str:
    raw = token.strip().lower()
    if not raw:
        return ""

    if pinyin is not None and Style is not None and _CHINESE_RE.search(raw):
        syllables = pinyin(raw, style=Style.NORMAL, heteronym=False, errors="default")
        flattened = [item[0].strip().lower() for item in syllables if item and item[0].strip()]
        if flattened:
            return flattened[-1]

    if _CHINESE_RE.search(raw):
        for ch in reversed(raw):
            if ch in _COMMON_PINYIN:
                return _COMMON_PINYIN[ch]

    normalized = unicodedata.normalize("NFKD", raw)
    return "".join(ch for ch in normalized if ch.isascii() and ch.isalpha())


def _final_matches(pinyin_text: str, finals: tuple[str, ...]) -> bool:
    return any(pinyin_text.endswith(final) for final in finals)


def _get_viseme_for_phoneme(phoneme: str) -> dict[str, float]:
    """Return a full mouth-channel weight map for one phoneme or fallback token."""
    token = (phoneme or "").strip()
    if _is_silence_token(token):
        return _SILENCE_VISEME.copy()

    lower = token.lower()
    if lower in _EXPLICIT_VISEMES:
        return _with_channels(_EXPLICIT_VISEMES[lower])

    py = _token_to_pinyin(token)
    if not py:
        return _DEFAULT_VISEME.copy()

    if py[0:1] in _CLOSED_INITIALS:
        if py.startswith(("fu", "fo")):
            return _with_channels({"mouse_open": 0.12, "lip_u": 0.42, "lip_w": 0.46})
        return _with_channels({"mouse_open": 0.04, "lip_w": 0.68})

    if _final_matches(py, _A_FINALS):
        return _with_channels({"mouse_open": 0.52, "lip_a": 0.86})

    if _final_matches(py, _O_FINALS):
        if py.endswith("uo"):
            return _with_channels({"mouse_open": 0.28, "lip_u": 0.36, "lip_o": 0.54})
        return _with_channels({"mouse_open": 0.36, "lip_o": 0.82})

    if _final_matches(py, _U_FINALS):
        return _with_channels({"mouse_open": 0.20, "lip_u": 0.78})

    if _final_matches(py, _I_FINALS):
        return _with_channels({"mouse_open": 0.18, "lip_i": 0.82})

    if _final_matches(py, _E_FINALS):
        return _with_channels({"mouse_open": 0.28, "lip_e": 0.76})

    return _DEFAULT_VISEME.copy()


def _smooth_frames(frames: list[BlendshapeFrame]) -> None:
    if len(frames) < 3 or settings.viseme_smooth_window_ms <= 0:
        return

    frame_duration_ms = max(float(settings.ws_chunk_duration_ms), 1.0)
    radius = max(1, int(round(settings.viseme_smooth_window_ms / frame_duration_ms)))
    original = [frame.weights.copy() for frame in frames]
    for index, frame in enumerate(frames):
        if all(original[index].get(channel, 0.0) <= 0.001 for channel in _MOUTH_CHANNELS):
            frame.weights = _SILENCE_VISEME.copy()
            continue

        start = max(0, index - radius)
        end = min(len(original), index + radius + 1)
        count = end - start
        smoothed: dict[str, float] = {}
        for channel in _MOUTH_CHANNELS:
            smoothed[channel] = sum(original[i].get(channel, 0.0) for i in range(start, end)) / count
        frame.weights = smoothed


def _append_interval_frames(frames: list[BlendshapeFrame], start_ms: float, end_ms: float, weights: dict[str, float]) -> None:
    frame_duration_ms = settings.ws_chunk_duration_ms
    t = max(0.0, start_ms)
    end = max(t, end_ms)
    if end <= t:
        frames.append(BlendshapeFrame(start_ms=t, end_ms=t + frame_duration_ms, weights=weights.copy()))
        return

    while t < end:
        end_t = min(t + frame_duration_ms, end)
        frames.append(BlendshapeFrame(start_ms=t, end_ms=end_t, weights=weights.copy()))
        t = end_t


def compute_viseme_curve(audio_result: AudioWithTimestamps) -> VisemeCurve:
    """Convert TTS phoneme timestamps to full-channel blendshape frames."""
    frame_duration_ms = settings.ws_chunk_duration_ms
    duration_ms = max(0.0, audio_result.duration_ms)
    frames: list[BlendshapeFrame] = []

    if not audio_result.phoneme_intervals:
        if duration_ms <= 0.0:
            return VisemeCurve(frames=[], duration_ms=audio_result.duration_ms)

        t = 0.0
        while t < duration_ms:
            end_t = min(t + frame_duration_ms, duration_ms)
            frames.append(BlendshapeFrame(
                start_ms=t,
                end_ms=end_t,
                weights=_DEFAULT_VISEME.copy(),
            ))
            t = end_t
    else:
        last_end = 0.0
        for interval in audio_result.phoneme_intervals:
            if interval.start_ms > last_end:
                _append_interval_frames(frames, last_end, interval.start_ms, _SILENCE_VISEME.copy())

            viseme = _get_viseme_for_phoneme(interval.phoneme)
            _append_interval_frames(frames, interval.start_ms, interval.end_ms, viseme)
            last_end = max(last_end, interval.end_ms)

    if frames:
        last_end = frames[-1].end_ms
        frames.append(BlendshapeFrame(
            start_ms=last_end,
            end_ms=last_end + frame_duration_ms,
            weights=_SILENCE_VISEME.copy(),
        ))

    _smooth_frames(frames)
    return VisemeCurve(frames=frames, duration_ms=audio_result.duration_ms)
