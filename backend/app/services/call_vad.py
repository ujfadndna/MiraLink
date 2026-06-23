"""Lightweight RMS VAD for continuous PCM call audio."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class VadEvent:
    type: str
    pcm: bytes = b""
    duration_ms: float = 0.0
    speech_ms: float = 0.0
    rms: float = 0.0


class RmsVadBuffer:
    """Aggregate 16 kHz PCM chunks into utterances using RMS + trailing silence."""

    def __init__(
        self,
        sample_rate: int = 16000,
        speech_rms: float = 0.008,
        min_speech_ms: float = 250.0,
        silence_tail_ms: float = 700.0,
        max_utterance_ms: float = 12000.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.speech_rms = speech_rms
        self.min_speech_ms = min_speech_ms
        self.silence_tail_ms = silence_tail_ms
        self.max_utterance_ms = max_utterance_ms
        self.reset()

    @property
    def in_speech(self) -> bool:
        return self._recording

    @property
    def current_voiced_ms(self) -> float:
        return self._current_voiced_ms

    def reset(self) -> None:
        self._recording = False
        self._buffer = bytearray()
        self._total_ms = 0.0
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._peak_rms = 0.0
        self._current_voiced_ms = 0.0

    def accept_chunk(self, pcm: bytes) -> list[VadEvent]:
        if not pcm:
            return []
        if len(pcm) % 2 != 0:
            raise ValueError("PCM int16 chunk length must be even")

        duration_ms = len(pcm) / 2 / self.sample_rate * 1000.0
        rms = _pcm_rms(pcm)
        voiced = rms >= self.speech_rms
        events: list[VadEvent] = []

        if voiced:
            self._current_voiced_ms += duration_ms
        else:
            self._current_voiced_ms = 0.0

        if not self._recording:
            if not voiced:
                return events
            self._recording = True
            self._buffer.clear()
            self._total_ms = 0.0
            self._speech_ms = 0.0
            self._silence_ms = 0.0
            self._peak_rms = 0.0
            events.append(VadEvent(type="speech_start", rms=rms))

        self._buffer.extend(pcm)
        self._total_ms += duration_ms
        self._peak_rms = max(self._peak_rms, rms)

        if voiced:
            self._speech_ms += duration_ms
            self._silence_ms = 0.0
        else:
            self._silence_ms += duration_ms

        if self._total_ms >= self.max_utterance_ms:
            events.extend(self._finish(force=True))
        elif self._silence_ms >= self.silence_tail_ms:
            events.extend(self._finish(force=False))

        return events

    def flush(self) -> list[VadEvent]:
        if not self._recording:
            return []
        return self._finish(force=True)

    def _finish(self, force: bool) -> list[VadEvent]:
        pcm = bytes(self._buffer)
        total_ms = self._total_ms
        speech_ms = self._speech_ms
        peak_rms = self._peak_rms
        valid = speech_ms >= self.min_speech_ms and peak_rms >= self.speech_rms
        self.reset()

        if not valid:
            return [VadEvent(type="speech_discarded", duration_ms=total_ms, speech_ms=speech_ms, rms=peak_rms)]
        return [
            VadEvent(
                type="utterance",
                pcm=pcm,
                duration_ms=total_ms,
                speech_ms=speech_ms,
                rms=peak_rms,
            )
        ]


def _pcm_rms(pcm: bytes) -> float:
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    values = samples.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(values * values)))
