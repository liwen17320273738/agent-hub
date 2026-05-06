"""
Voice Proxy — local Whisper ASR for Agent Hub
===============================================

Uses OpenAI Whisper (local, no API key needed) for speech-to-text.
Runs on MPS (Apple Silicon GPU) when available, CPU fallback otherwise.

Returns structured segments with timing info.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from ..config import settings

logger = logging.getLogger(__name__)

# ── Default model ────────────────────────────────────────────────────
_DEFAULT_MODEL = "medium"      # good balance of speed/accuracy on M5 Pro
_MPS_AVAILABLE = False         # set on first load attempt

# ── Transcription Result ──────────────────────────────────────────────


class TranscriptionSegment:
    """A single transcribed segment with speaker and timing."""

    def __init__(self, speaker: int, start: float, end: float, text: str) -> None:
        self.speaker = speaker
        self.start = start
        self.end = end
        self.text = text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "speaker": self.speaker,
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "text": self.text,
        }


class TranscriptionResult:
    """Full transcription result."""

    def __init__(self, segments: List[TranscriptionSegment], duration_s: float) -> None:
        self.segments = segments
        self.duration_s = duration_s

    @property
    def full_text(self) -> str:
        return "\n".join(s.text for s in self.segments).strip()

    @property
    def speaker_count(self) -> int:
        return len({s.speaker for s in self.segments})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "fullText": self.full_text,
            "durationS": round(self.duration_s, 1),
            "speakerCount": self.speaker_count,
            "segmentCount": len(self.segments),
        }


# ── Proxy Service ─────────────────────────────────────────────────────


class VoiceProxy:
    """Local Whisper ASR service for Agent Hub."""

    def __init__(self) -> None:
        self._model: Any = None
        self._model_name: Optional[str] = None

    # ── Public API ─────────────────────────────────────────────────────

    async def transcribe(
        self,
        audio_path: str,
        prompt: str = "",
        timeout: float = 300.0,
    ) -> TranscriptionResult:
        """Transcribe an audio file to text.

        Args:
            audio_path: Local file path to audio.
            prompt: Optional hint text for the model.
            timeout: Maximum wait time in seconds.

        Returns:
            ``TranscriptionResult`` with segments and full text.
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        loop = asyncio.get_event_loop()
        started = time.monotonic()

        try:
            raw = await asyncio.wait_for(
                loop.run_in_executor(
                    None, self._transcribe_sync, audio_path, prompt
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"Transcription timed out after {timeout}s")

        elapsed = time.monotonic() - started
        logger.info("[voice] transcribed in %.1fs", elapsed)

        segments = []
        for seg in raw.get("segments", []):
            segments.append(TranscriptionSegment(
                speaker=0,   # Whisper doesn't do diarisation by default
                start=float(seg.get("start", 0)),
                end=float(seg.get("end", 0)),
                text=str(seg.get("text", "")).strip(),
            ))

        # Detect duration from the last segment
        duration = 0.0
        if segments:
            duration = segments[-1].end

        return TranscriptionResult(segments=segments, duration_s=duration)

    async def transcribe_bytes(
        self,
        audio_data: bytes,
        filename: str = "audio.wav",
        prompt: str = "",
        timeout: float = 300.0,
    ) -> TranscriptionResult:
        """Transcribe raw audio bytes (e.g. from an upload)."""
        suffix = os.path.splitext(filename)[1] or ".wav"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(audio_data)
            tmp.flush()
            result = await self.transcribe(tmp.name, prompt=prompt, timeout=timeout)
            return result
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def is_available(self) -> bool:
        """Check if Whisper is importable."""
        try:
            import whisper  # noqa: F401
            return True
        except ImportError:
            return False

    # ── Internals ──────────────────────────────────────────────────────

    def _transcribe_sync(self, audio_path: str, prompt: str = "") -> Dict[str, Any]:
        """Synchronous transcription call (runs in executor)."""
        model = self._load_model()

        kwargs: Dict[str, Any] = dict(
            fp16=(_MPS_AVAILABLE),       # fp16 on MPS, fp32 on CPU
            language="zh",               # prefer Chinese
            word_timestamps=True,
        )
        if prompt:
            kwargs["initial_prompt"] = prompt

        return model.transcribe(audio_path, **kwargs)

    def _load_model(self) -> Any:
        """Load (or get cached) Whisper model."""
        model_name = getattr(settings, "whisper_model", None) or _DEFAULT_MODEL

        if self._model is not None and self._model_name == model_name:
            return self._model

        import whisper
        global _MPS_AVAILABLE

        logger.info("[voice] loading whisper model '%s'...", model_name)
        started = time.monotonic()

        try:
            self._model = whisper.load_model(model_name)
        except Exception as e:
            logger.error("[voice] failed to load whisper model: %s", e)
            raise RuntimeError(f"Failed to load Whisper model '{model_name}': {e}")

        self._model_name = model_name
        elapsed = time.monotonic() - started
        logger.info("[voice] whisper model '%s' loaded in %.1fs", model_name, elapsed)

        # Detect MPS
        try:
            self._model.to("mps")
            _MPS_AVAILABLE = True
            logger.info("[voice] MPS (Apple GPU) enabled")
        except Exception:
            _MPS_AVAILABLE = False
            logger.info("[voice] MPS not available, using CPU")

        return self._model


# ── Singleton ─────────────────────────────────────────────────────────

_voice_instance: Optional[VoiceProxy] = None


def get_voice() -> VoiceProxy:
    """Get or create the Voice proxy singleton."""
    global _voice_instance
    if _voice_instance is None:
        _voice_instance = VoiceProxy()
    return _voice_instance


# Backwards-compat alias
def get_vibevoice() -> VoiceProxy:
    return get_voice()
