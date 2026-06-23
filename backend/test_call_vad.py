import math

import numpy as np

from app.services.call_vad import RmsVadBuffer


def _tone(ms: int, amplitude: float = 0.08, sample_rate: int = 16000) -> bytes:
    count = int(sample_rate * ms / 1000)
    t = np.arange(count, dtype=np.float32) / sample_rate
    wave = np.sin(2 * math.pi * 220 * t) * amplitude
    return np.clip(wave * 32767, -32768, 32767).astype(np.int16).tobytes()


def _silence(ms: int, sample_rate: int = 16000) -> bytes:
    return np.zeros(int(sample_rate * ms / 1000), dtype=np.int16).tobytes()


def _feed(vad: RmsVadBuffer, pcm: bytes, chunk_ms: int = 20):
    chunk_bytes = int(vad.sample_rate * chunk_ms / 1000) * 2
    events = []
    for offset in range(0, len(pcm), chunk_bytes):
        events.extend(vad.accept_chunk(pcm[offset : offset + chunk_bytes]))
    return events


def test_silence_does_not_start_utterance():
    vad = RmsVadBuffer()
    events = _feed(vad, _silence(1500))
    assert events == []
    assert not vad.in_speech


def test_short_noise_is_discarded():
    vad = RmsVadBuffer()
    events = _feed(vad, _tone(220) + _silence(760))
    assert [event.type for event in events] == ["speech_start", "speech_discarded"]
    assert not vad.in_speech


def test_valid_speech_commits_after_trailing_silence():
    vad = RmsVadBuffer()
    events = _feed(vad, _tone(620) + _silence(760))
    assert events[0].type == "speech_start"
    assert events[-1].type == "utterance"
    assert 1300 <= events[-1].duration_ms <= 1400
    assert 600 <= events[-1].speech_ms <= 640
    assert events[-1].pcm


def test_short_chinese_greeting_length_commits_after_trailing_silence():
    vad = RmsVadBuffer()
    events = _feed(vad, _tone(280) + _silence(760))
    assert events[0].type == "speech_start"
    assert events[-1].type == "utterance"
    assert 260 <= events[-1].speech_ms <= 300
    assert events[-1].pcm


def test_max_utterance_forces_commit():
    vad = RmsVadBuffer(max_utterance_ms=1000)
    events = _feed(vad, _tone(1200))
    utterances = [event for event in events if event.type == "utterance"]
    assert len(utterances) == 1
    assert 980 <= utterances[0].duration_ms <= 1020
